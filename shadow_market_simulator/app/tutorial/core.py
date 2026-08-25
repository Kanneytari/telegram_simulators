from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup


TUTORIAL_RUNTIME_ATTR = "_nightshift_tutorial_runtime_enabled"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def enable_runtime(db) -> None:
    setattr(db, TUTORIAL_RUNTIME_ATTR, True)


def runtime_enabled(db) -> bool:
    return bool(db is not None and getattr(db, TUTORIAL_RUNTIME_ATTR, False))


STARTING_FREE_CASH = 500_000
STARTING_RESERVE = 30_000
STARTING_CAPITAL = STARTING_FREE_CASH + STARTING_RESERVE

STAGE_PROCUREMENT = "procurement"
STAGE_PICKUP_WAIT = "pickup_wait"
STAGE_HANDOFF = "handoff"
STAGE_HANDOFF_WAIT = "handoff_wait"
STAGE_PREP_WAIT = "prep_wait"
STAGE_PRICE = "price"
STAGE_SALE_WAIT = "sale_wait"
STAGE_REVIEW = "review"
STAGE_DISPUTE = "dispute"
STAGE_TEAM = "team"
STAGE_COMPLETE = "complete"

WAIT_STAGES = {
    STAGE_PICKUP_WAIT,
    STAGE_HANDOFF_WAIT,
    STAGE_PREP_WAIT,
    STAGE_SALE_WAIT,
}

CONTINUE_LABEL = "▶️ Продолжить обучение"


def _ensure_schema_conn(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS tutorial_state (\n               player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,\n               stage TEXT NOT NULL DEFAULT 'procurement',\n               data_json TEXT NOT NULL DEFAULT '{}',\n               active INTEGER NOT NULL DEFAULT 1,\n               created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n               updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n           )")


def tutorial_state(db, player_id: int) -> dict | None:
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        row = conn.execute('SELECT * FROM tutorial_state WHERE player_id=?', (player_id,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row['data_json'] or '{}')
    except (TypeError, ValueError):
        data = {}
    return {'player_id': player_id, 'stage': str(row['stage']), 'active': bool(row['active']), 'data': data}


def tutorial_active(db, player_id: int) -> bool:
    state = tutorial_state(db, player_id)
    return bool(state and state['active'])


def _set_stage(db, player_id: int, stage: str, **data) -> None:
    current = tutorial_state(db, player_id)
    merged = dict(current['data'] if current else {})
    merged.update({key: value for key, value in data.items() if value is not None})
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        conn.execute('INSERT INTO tutorial_state(player_id, stage, data_json, active)\n               VALUES (?, ?, ?, 1)\n               ON CONFLICT(player_id) DO UPDATE SET\n                   stage=excluded.stage,\n                   data_json=excluded.data_json,\n                   active=1,\n                   updated_at=CURRENT_TIMESTAMP', (player_id, stage, json.dumps(merged, ensure_ascii=False)))


def _finish_tutorial(db, player_id: int) -> None:
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        conn.execute('UPDATE tutorial_state\n               SET stage=?, active=0, updated_at=CURRENT_TIMESTAMP\n               WHERE player_id=?', (STAGE_COMPLETE, player_id))


def _free_cash(game, player_id: int) -> int:
    if hasattr(game, '_free_cash_conn'):
        with game.db.connect() as conn:
            return int(game._free_cash_conn(conn, player_id))
    with game.db.connect() as conn:
        shop = conn.execute('SELECT balance, reserve_target FROM shops WHERE player_id=?', (player_id,)).fetchone()
        deposits = int(conn.execute('SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1', (player_id,)).fetchone()[0])
    return int(shop['balance']) - int(shop['reserve_target']) - deposits


def _append_tutorial_action(markup: InlineKeyboardMarkup, state: dict) -> InlineKeyboardMarkup:
    rows = [list(row) for row in markup.inline_keyboard]
    stage = state['stage']
    extra: list[InlineKeyboardButton] = []
    if stage in WAIT_STAGES:
        extra.append(InlineKeyboardButton(text='⏩ Пропустить ожидание', callback_data='tutorial:skip'))
    elif stage == STAGE_REVIEW:
        extra.append(InlineKeyboardButton(text='▶️ Продолжить обучение', callback_data='tutorial:continue'))
    elif stage == STAGE_TEAM:
        extra.append(InlineKeyboardButton(text='✅ Завершить обучение', callback_data='tutorial:finish'))
    if extra:
        rows.insert(0, extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _active_task_for_stage(conn, player_id: int, state: dict):
    data = state['data']
    if state['stage'] == STAGE_PICKUP_WAIT:
        return conn.execute("SELECT * FROM employee_tasks\n               WHERE player_id=? AND kind='receive_batch' AND batch_id=? AND status='active'\n               ORDER BY id DESC LIMIT 1", (player_id, int(data.get('batch_id', 0)))).fetchone()
    if state['stage'] == STAGE_HANDOFF_WAIT:
        return conn.execute("SELECT * FROM employee_tasks\n               WHERE player_id=? AND kind='handoff' AND allocation_id=? AND status='active'\n               ORDER BY id DESC LIMIT 1", (player_id, int(data.get('allocation_id', 0)))).fetchone()
    if state['stage'] == STAGE_PREP_WAIT:
        return conn.execute("SELECT * FROM employee_tasks\n               WHERE player_id=? AND kind='place_stashes' AND allocation_id=? AND status='active'\n               ORDER BY id DESC LIMIT 1", (player_id, int(data.get('allocation_id', 0)))).fetchone()
    return None


def sync_tutorial_state(db, player_id: int) -> dict | None:
    state = tutorial_state(db, player_id)
    if not state or not state['active']:
        return state
    stage = state['stage']
    data = state['data']
    next_stage: str | None = None
    next_data: dict = {}
    with db.connect() as conn:
        if stage == STAGE_PICKUP_WAIT:
            batch = conn.execute('SELECT status FROM batches WHERE id=? AND player_id=?', (int(data.get('batch_id', 0)), player_id)).fetchone()
            if batch and batch['status'] == 'warehouse':
                next_stage = STAGE_HANDOFF
        elif stage in {STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT}:
            allocation = conn.execute('SELECT status, product_id FROM retail_allocations WHERE id=? AND player_id=?', (int(data.get('allocation_id', 0)), player_id)).fetchone()
            if allocation:
                if allocation['status'] == 'published':
                    next_stage = STAGE_PRICE
                    next_data['product_id'] = int(allocation['product_id'])
                elif stage == STAGE_HANDOFF_WAIT and allocation['status'] == 'preparing':
                    next_stage = STAGE_PREP_WAIT
        elif stage == STAGE_SALE_WAIT:
            floor = int(data.get('order_floor', 0) or 0)
            order = conn.execute('SELECT id, product_id FROM orders\n                   WHERE player_id=? AND id>?\n                   ORDER BY id LIMIT 1', (player_id, floor)).fetchone()
            if order:
                next_stage = STAGE_REVIEW
                next_data.update(order_id=int(order['id']), product_id=int(order['product_id']))
    if next_stage:
        _set_stage(db, player_id, next_stage, **next_data)
        return tutorial_state(db, player_id)
    return state


def skip_tutorial_wait(game, simulation_engine, player_id: int) -> str:
    state = sync_tutorial_state(game.db, player_id)
    if not state or not state['active']:
        return 'Обучение уже завершено.'
    if state['stage'] in {STAGE_PICKUP_WAIT, STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT}:
        now = utcnow()
        with game.db.connect() as conn:
            task = _active_task_for_stage(conn, player_id, state)
            if task:
                conn.execute('UPDATE employee_tasks SET completes_at=? WHERE id=?', (iso(now - timedelta(seconds=1)), int(task['id'])))
                simulation_engine._process_tasks(conn, player_id, now)
        updated = sync_tutorial_state(game.db, player_id)
        if updated and updated['stage'] != state['stage']:
            return 'Ожидание пропущено.'
        return 'Задача ещё не готова к следующему этапу.'
    if state['stage'] == STAGE_SALE_WAIT:
        listing_id = int(state['data'].get('listing_id', 0) or 0)
        with game.db.connect() as conn:
            listing = None
            if listing_id:
                listing = conn.execute('SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier\n                       FROM listings l JOIN products p ON p.id=l.product_id\n                       WHERE l.id=? AND l.player_id=? AND l.active=1', (listing_id, player_id)).fetchone()
            if not listing:
                listing = conn.execute("SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier\n                       FROM listings l JOIN products p ON p.id=l.product_id\n                       WHERE l.player_id=? AND l.active=1\n                         AND EXISTS (\n                             SELECT 1\n                             FROM retail_positions rp\n                             JOIN employees e ON e.id=rp.employee_id\n                             WHERE rp.player_id=l.player_id\n                               AND rp.product_id=l.product_id\n                               AND rp.pack_size=l.pack_size\n                               AND rp.position_count>0\n                               AND e.active=1 AND e.available=1 AND e.role='courier'\n                         )\n                       ORDER BY l.id LIMIT 1", (player_id,)).fetchone()
            if not listing:
                return 'На витрине пока нет товара для продажи.'
            before = int(conn.execute('SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?', (player_id,)).fetchone()[0])
            result = simulation_engine._create_retail_order(conn, player_id, listing, utcnow())
            if result is None:
                return 'Пока не удалось создать первый заказ.'
            order = conn.execute('SELECT id, product_id FROM orders\n                   WHERE player_id=? AND id>?\n                   ORDER BY id DESC LIMIT 1', (player_id, before)).fetchone()
        if order:
            _set_stage(game.db, player_id, STAGE_REVIEW, order_id=int(order['id']), product_id=int(order['product_id']), listing_id=int(listing['id']))
            return 'Первая продажа завершена.'
    return 'Сейчас нечего проматывать.'


def create_tutorial_dispute(game, simulation_engine, player_id: int) -> tuple[int, int] | None:
    state = sync_tutorial_state(game.db, player_id)
    if not state or not state['active'] or state['stage'] != STAGE_REVIEW:
        return None
    order_id = int(state['data'].get('order_id', 0) or 0)
    if not order_id:
        return None
    now = utcnow()
    with game.db.connect() as conn:
        existing = conn.execute("SELECT id FROM disputes\n               WHERE player_id=? AND order_id=? AND status='open'\n               LIMIT 1", (player_id, order_id)).fetchone()
        if existing:
            dispute_id = int(existing['id'])
            inbox = conn.execute("SELECT id FROM inbox\n                   WHERE player_id=? AND status='open' AND kind='dispute'\n                     AND json_extract(payload_json, '$.dispute_id')=?\n                   ORDER BY id DESC LIMIT 1", (player_id, dispute_id)).fetchone()
            inbox_id = int(inbox['id']) if inbox else 0
        else:
            order = conn.execute('SELECT o.*, c.alias client_alias\n                   FROM orders o\n                   JOIN clients c ON c.id=o.client_id\n                   WHERE o.id=? AND o.player_id=?', (order_id, player_id)).fetchone()
            if not order:
                return None
            message = 'Описание оказалось недостаточно понятным. Не могу уверенно найти заказ и хочу решить вопрос.'
            evidence = {'description_present': True, 'extra_material_present': False, 'client_tone': 'спокойный', 'order_value': int(order['revenue']), 'tutorial': True}
            deadline = now + timedelta(hours=2 / max(0.1, simulation_engine.effective_speed(player_id)))
            cur = conn.execute("INSERT INTO disputes(\n                       player_id, order_id, true_cause, message, evidence_json, deadline_at\n                   ) VALUES (?, ?, 'DESCRIPTION_ERROR', ?, ?, ?)", (player_id, order_id, message, json.dumps(evidence, ensure_ascii=False), iso(deadline)))
            dispute_id = int(cur.lastrowid)
            conn.execute("UPDATE orders SET status='disputed' WHERE id=?", (order_id,))
            conn.execute('UPDATE employees SET disputes=disputes+1 WHERE id=?', (order['employee_id'],))
            conn.execute('UPDATE clients SET disputes_total=disputes_total+1 WHERE id=?', (order['client_id'],))
            inbox_cur = conn.execute("INSERT INTO inbox(\n                       player_id, kind, priority, title, body,\n                       payload_json, expires_at, notified_at\n                   ) VALUES (?, 'dispute', 'important', ?, ?, ?, ?, ?)", (player_id, f'Диспут #{dispute_id}', f"Клиент {order['client_alias']}: {message}", json.dumps({'dispute_id': dispute_id, 'tutorial': True}, ensure_ascii=False), iso(deadline), iso(now)))
            inbox_id = int(inbox_cur.lastrowid)
    _set_stage(game.db, player_id, STAGE_DISPUTE, dispute_id=dispute_id, inbox_id=inbox_id)
    return (dispute_id, inbox_id)


def build_tutorial_router(db, game, simulation_engine) -> Router:
    from .. import ui_navigation
    router = Router(name='guided-first-cycle')

    @router.callback_query(F.data == 'tutorial:skip')
    async def skip(callback: CallbackQuery) -> None:
        result = skip_tutorial_wait(game, simulation_engine, callback.from_user.id)
        await callback.answer(result[:180])
        await ui_navigation.render_home(callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id)

    @router.callback_query(F.data == 'tutorial:continue')
    async def continue_tutorial(callback: CallbackQuery) -> None:
        created = create_tutorial_dispute(game, simulation_engine, callback.from_user.id)
        await callback.answer('Следующий этап' if created else 'Этап уже пройден')
        await ui_navigation.render_home(callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id)

    @router.callback_query(F.data == 'tutorial:open_dispute')
    async def open_dispute(callback: CallbackQuery) -> None:
        await callback.answer()
        state = tutorial_state(db, callback.from_user.id)
        if not state or state['stage'] != STAGE_DISPUTE:
            await ui_navigation.render_home(callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id)
            return
        from ..ui_disputes import render_dispute
        dispute_id = int(state['data'].get('dispute_id', 0) or 0)
        if not dispute_id or not await render_dispute(callback.message, game, callback.from_user.id, dispute_id):
            await ui_navigation.render_home(callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id)

    @router.callback_query(F.data == 'tutorial:finish')
    async def finish(callback: CallbackQuery) -> None:
        _finish_tutorial(db, callback.from_user.id)
        await callback.answer('Обучение завершено')
        await ui_navigation.render_home(callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id)
    return router
