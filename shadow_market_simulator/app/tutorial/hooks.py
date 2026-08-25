from __future__ import annotations

from app.presentation.vocabulary import PRODUCT, STOREFRONT, SUPPLIERS, WAREHOUSE, button
from functools import wraps

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import core as tutorial
from .core import (
    STARTING_CAPITAL,
    STARTING_RESERVE,
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_HANDOFF_WAIT,
    STAGE_PICKUP_WAIT,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_SALE_WAIT,
    STAGE_TEAM,
    _append_tutorial_action,
    _ensure_schema_conn,
    _free_cash,
    _set_stage,
    runtime_enabled,
    sync_tutorial_state,
    tutorial_active,
    tutorial_state,
)
from .copy import RETURN_TO_MENU, instruction
from ..ui_common import clean, money, notice, present, rating, tutorial_hint


def _runtime_db(args, kwargs):
    for key in ("db", "game"):
        value = kwargs.get(key)
        if value is not None:
            if hasattr(value, "connect"):
                return value
            db = getattr(value, "db", None)
            if db is not None and hasattr(db, "connect"):
                return db
    for value in args:
        if hasattr(value, "connect"):
            return value
        db = getattr(value, "db", None)
        if db is not None and hasattr(db, "connect"):
            return db
    return None


def _handoff_state(db, player_id: int) -> bool:
    state = sync_tutorial_state(db, player_id)
    return bool(state and state["active"] and state["stage"] == STAGE_HANDOFF)


class _HintTarget:
    def __init__(self, target, hint: str):
        self._target = target
        self._hint = hint
        self.photo = getattr(target, "photo", None)

    def _text(self, text: str) -> str:
        return f"{text}\n\n{self._hint}"

    async def edit_text(self, text, **kwargs):
        return await self._target.edit_text(self._text(text), **kwargs)

    async def answer(self, text, **kwargs):
        return await self._target.answer(self._text(text), **kwargs)

    async def delete(self):
        delete = getattr(self._target, "delete", None)
        if delete is not None:
            return await delete()
        return None


def _return_target(target):
    return _HintTarget(target, tutorial_hint(RETURN_TO_MENU))


def new_player_setup(original):
    @wraps(original)
    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = original(self, player_id, username)
        if not created:
            return False
        with self.db.connect() as conn:
            _ensure_schema_conn(conn)
            conn.execute('DELETE FROM batches WHERE player_id=?', (player_id,))
            conn.execute('UPDATE shops SET balance=?, reserve_target=? WHERE player_id=?', (STARTING_CAPITAL, STARTING_RESERVE, player_id))
            conn.execute("UPDATE ledger\n                   SET amount=?, note='Стартовый капитал'\n                   WHERE player_id=? AND kind='capital'", (STARTING_CAPITAL, player_id))
            conn.execute("UPDATE inbox\n                   SET title='Первая смена',\n                       body='Сейчас у тебя нет товара. Начни с первой закупки в разделе «Товар».'\n                   WHERE player_id=? AND kind='tutorial'", (player_id,))
            conn.execute("INSERT OR REPLACE INTO tutorial_state(player_id, stage, data_json, active)\n                   VALUES (?, ?, '{}', 1)", (player_id, STAGE_PROCUREMENT))
        return True
    decorated = ensure_player

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def first_purchase_protection(original):
    @wraps(original)
    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        state = tutorial_state(self.db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            return original(self, player_id, offer_id, employee_id)
        with self.db.connect() as conn:
            offer = conn.execute("SELECT product_id, offer_reliability\n                   FROM supplier_offers\n                   WHERE id=? AND player_id=? AND status='open'", (offer_id, player_id)).fetchone()
            if not offer:
                return original(self, player_id, offer_id, employee_id)
            old_reliability = offer['offer_reliability']
            conn.execute('UPDATE supplier_offers SET offer_reliability=1.0 WHERE id=?', (offer_id,))
        try:
            result = original(self, player_id, offer_id, employee_id)
        finally:
            with self.db.connect() as conn:
                conn.execute('UPDATE supplier_offers SET offer_reliability=? WHERE id=?', (old_reliability, offer_id))
        if not result.startswith('✅ Куплено'):
            return result
        with self.db.connect() as conn:
            batch = conn.execute("SELECT id, product_id FROM batches\n                   WHERE player_id=? AND responsible_employee_id=? AND status='receiving'\n                   ORDER BY id DESC LIMIT 1", (player_id, employee_id)).fetchone()
        if batch:
            _set_stage(self.db, player_id, STAGE_PICKUP_WAIT, batch_id=int(batch['id']), product_id=int(batch['product_id']), warehouse_employee_id=employee_id)
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE inbox
                       SET body='Складмен забирает первую партию. Обычно это занимает игровое время.'
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (player_id,),
                )
            result += '\n\n' + tutorial_hint('Складмен забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.')
        return result
    decorated = buy_offer_for_employee

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_progress(original):
    @wraps(original)
    def allocate_to_retail(self, player_id: int, batch_id: int, retail_employee_id: int, quantity: int) -> str:
        result = original(self, player_id, batch_id, retail_employee_id, quantity)
        state = sync_tutorial_state(self.db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_HANDOFF:
            return result
        with self.db.connect() as conn:
            allocation = conn.execute('SELECT id FROM retail_allocations\n                   WHERE player_id=? AND batch_id=? AND retail_employee_id=?\n                   ORDER BY id DESC LIMIT 1', (player_id, batch_id, retail_employee_id)).fetchone()
        if allocation:
            _set_stage(self.db, player_id, STAGE_HANDOFF_WAIT, batch_id=batch_id, allocation_id=int(allocation['id']), retail_employee_id=retail_employee_id)
            result += '\n\n' + tutorial_hint('Передача занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.')
        return result
    decorated = allocate_to_retail

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def price_progress(original):
    @wraps(original)
    def change_listing_price(self, player_id: int, listing_id: int, percent: int) -> str:
        result = original(self, player_id, listing_id, percent)
        state = sync_tutorial_state(self.db, player_id)
        if state and state['active'] and (state['stage'] == STAGE_PRICE) and result.startswith('Цена изменена'):
            with self.db.connect() as conn:
                floor = int(conn.execute('SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?', (player_id,)).fetchone()[0])
            _set_stage(self.db, player_id, STAGE_SALE_WAIT, listing_id=listing_id, order_floor=floor)
        return result
    decorated = change_listing_price

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def management_event_protection(original):
    @wraps(original)
    def protected_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        if tutorial_active(self.db, player_id):
            self._ensure_courier_profiles_conn(conn, player_id)
            self._recover_courier_state_conn(conn, player_id, sim_hours)
            return 0
        return original(self, conn, player_id, sim_hours, now)
    decorated = protected_events

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def dispute_probability_protection(original):
    @wraps(original)
    def protected_dispute(self, client, employee, quality: float, modifier: float) -> float:
        employee_id = self._employee_id(employee)
        if employee_id:
            with self.db.connect() as conn:
                owner = conn.execute('SELECT player_id FROM employees WHERE id=?', (employee_id,)).fetchone()
            if owner:
                state = tutorial_state(self.db, int(owner['player_id']))
                if state and state['active'] and (state['stage'] == STAGE_SALE_WAIT):
                    return 0.0
        return original(self, client, employee, quality, modifier)
    decorated = protected_dispute

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def dispute_progress(original):
    @wraps(original)
    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        result = original(self, player_id, dispute_id, decision, source)
        state = tutorial_state(self.db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_DISPUTE:
            return result
        expected = int(state['data'].get('dispute_id', 0) or 0)
        if expected and expected != dispute_id:
            return result
        with self.db.connect() as conn:
            row = conn.execute('SELECT status FROM disputes WHERE id=? AND player_id=?', (dispute_id, player_id)).fetchone()
        if row and row['status'] == 'resolved':
            _set_stage(self.db, player_id, STAGE_TEAM)
        return result
    decorated = resolve_dispute_with_source

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_tutorial_flag(original):
    @wraps(original)
    def needs_first_handoff_tutorial(self, player_id: int) -> bool:
        state = sync_tutorial_state(self.db, player_id)
        if state and state['active'] and (state['stage'] == STAGE_HANDOFF):
            return True
        return original(self, player_id)
    decorated = needs_first_handoff_tutorial

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_home(original):
    @wraps(original)
    async def render_home(target, db, game, simulation_engine, admin_ids, player_id: int, *, edit: bool=True) -> None:
        from .. import ui_navigation
        text, opened, urgent = ui_navigation._home_snapshot(db, game, simulation_engine, player_id)
        state = sync_tutorial_state(db, player_id)
        markup = ui_navigation.home_keyboard(opened, urgent, is_admin=player_id in admin_ids)
        if state and state['active']:
            text += '\n\n' + tutorial_hint(instruction(state))
            markup = _append_tutorial_action(markup, state)
        await present(target, text, markup, edit=edit)
    decorated = render_home

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            await original(target, db, game, player_id, flash=flash)
            return
        body = f'<b>{PRODUCT.label}</b>\n\nСвободно: <b>{money(_free_cash(game, player_id))}</b>\n\n' + tutorial_hint(f'Нажми [{SUPPLIERS.label}]')
        if flash:
            body = f'{flash}\n\n{body}'
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, body, markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded

def soft_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            await original(target, db, game, player_id, flash=flash)
            return
        products = game.procurement_products(player_id)
        body = f'<b>{SUPPLIERS.label}</b>\n\n' + tutorial_hint('Выбери товар для первой закупки.')
        if flash:
            body = f'{flash}\n\n{body}'
        await present(target, body, ui_commerce._procurement_products_keyboard(db, player_id, products))
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_procurement_product(original):
    @wraps(original)
    async def render_procurement_product(target, game, player_id: int, product_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(game.db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            await original(target, game, player_id, product_id, flash=flash)
            return
        offers = game.offers(player_id, product_id)
        with game.db.connect() as conn:
            product = conn.execute('SELECT title FROM products WHERE id=? AND active=1', (product_id,)).fetchone()
        if not product:
            from .. import ui_commerce
            await ui_commerce.render_product_root(target, game.db, game, player_id, flash=flash)
            return
        body = f"<b>📦 {clean(product['title'])}</b>\n\nДоступно: {len(offers)} предложений.\n\n" + tutorial_hint('Выбери предложение.')
        if flash:
            body = f'{flash}\n\n{body}'
        await present(target, body, ui_commerce._offers_keyboard(product_id, offers))
    decorated = render_procurement_product

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_storefront(original):
    @wraps(original)
    async def render_storefront_root(target, db, game, simulation_engine, player_id: int) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] not in {STAGE_PRICE, STAGE_SALE_WAIT}:
            await original(target, db, game, simulation_engine, player_id)
            return
        simulation_engine.advance(player_id)
        state = sync_tutorial_state(db, player_id)
        rows = ui_commerce._sales_products(db, player_id)
        trust = game.customer_metrics(player_id)
        text = f"<b>{STOREFRONT.label}</b>\n\nДоверие: {trust['trust_score']:.0f}/100\nНаценка до ~+{trust['premium_allowance'] * 100:.0f}% обычно не снижает спрос."
        if state and state['active'] and (state['stage'] == STAGE_PRICE):
            text += '\n\n' + tutorial_hint('Выбери товар.')
        elif state and state['active'] and (state['stage'] == STAGE_SALE_WAIT):
            text += '\n\n' + tutorial_hint('Теперь дождись первой продажи. Можешь продолжать играть как обычно или вернуться в меню и нажать ⏩ Пропустить ожидание.')
        markup = ui_commerce._sales_root_keyboard(rows)
        if state and state['active']:
            markup = _append_tutorial_action(markup, state)
        await present(target, text, markup)
    decorated = render_storefront_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_sales_product(original):
    @wraps(original)
    async def render_sales_product(target, db, player_id: int, product_id: int) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PRICE:
            await original(target, db, player_id, product_id)
            return
        product, listings, published, avg, n = ui_commerce._product_listings(db, player_id, product_id)
        if not product:
            return
        rows = [[InlineKeyboardButton(text=f"×{listing['pack_size']} · {money(listing['price'])} · доступно {int(listing['positions'])}", callback_data=f"sales:listing:{listing['id']}")] for listing in listings]
        rows.append([button(STOREFRONT)])
        text = f"<b>{clean(product['title'])}</b>\n\n{published} ед. готовы к продаже · оценка {rating(avg, n)}\n\n" + tutorial_hint('Выбери фасовку.')
        await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))
    decorated = render_sales_product

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def soft_listing(original):
    @wraps(original)
    async def render_listing(target, db, game, player_id: int, listing_id: int) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] not in {STAGE_PRICE, STAGE_SALE_WAIT}:
            await original(target, db, game, player_id, listing_id)
            return
        row = ui_commerce._listing_context(db, player_id, listing_id)
        if not row:
            return
        trust = game.customer_metrics(player_id)
        unit_price = float(row['price']) / max(1, int(row['pack_size']))
        delta = (unit_price / float(row['base_market_price']) - 1.0) * 100.0
        allowance = float(trust['premium_allowance']) * 100.0
        status = 'нормально' if delta <= allowance + 0.01 else 'спрос будет снижаться'
        text = f"<b>{clean(row['title'])} · ×{row['pack_size']}</b>\n\nЦена: <b>{money(row['price'])}</b> · рынок ~{money(row['base_market_price'] * row['pack_size'])}\nНаценка: {delta:+.0f}%\n\nПри текущем доверии до ~+{allowance:.0f}% переносится нормально · <b>{status}</b>.\n\nДоступно: {int(row['positions'])}"
        if state['stage'] == STAGE_PRICE:
            text += '\n\n' + tutorial_hint('Измени цену на −5% или +5%.')
        else:
            text += '\n\n' + tutorial_hint('Цена выставлена. Теперь дождись первой продажи или нажми ⏩ Пропустить ожидание.')
        rows = [[InlineKeyboardButton(text='−5%', callback_data=f'sales:price:{listing_id}:-5'), InlineKeyboardButton(text='+5%', callback_data=f'sales:price:{listing_id}:5')], [InlineKeyboardButton(text=f"{str(row['title'])[:18]}", callback_data=f"sales:product:{row['product_id']}")]]
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        markup = _append_tutorial_action(markup, state)
        await present(target, text, markup)
    decorated = render_listing

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded



def affordable_empty_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        products = game.procurement_products(player_id)
        if any((int(product.get('total', 0)) > 0 for product in products)):
            await original(target, db, game, player_id, flash=flash)
            return
        with db.connect() as conn:
            free_cash = game._free_cash_conn(conn, player_id)
        body = f'<b>{PRODUCT.label}</b>\n\nСвободно: <b>{money(free_cash)}</b>\n\nДоступных предложений нет.'
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, notice(flash, body), markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded

def affordable_empty_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        products = game.procurement_products(player_id)
        if any((int(product.get('total', 0)) > 0 for product in products)):
            await original(target, db, game, player_id, flash=flash)
            return
        body = f'<b>{SUPPLIERS.label}</b>\n\nДоступных предложений нет.'
        await present(target, notice(flash, body), ui_commerce._procurement_products_keyboard(db, player_id, products))
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def affordable_empty_procurement_product(original):
    @wraps(original)
    async def render_procurement_product(target, game, player_id: int, product_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        offers = game.offers(player_id, product_id)
        if offers:
            await original(target, game, player_id, product_id, flash=flash)
            return
        with game.db.connect() as conn:
            product = conn.execute('SELECT title FROM products WHERE id=? AND active=1', (product_id,)).fetchone()
        if not product:
            await ui_commerce.render_product_root(target, game.db, game, player_id, flash=flash)
            return
        body = f"<b>📦 {clean(product['title'])}</b>\n\nДоступных предложений нет."
        await present(target, notice(flash, body), ui_commerce._offers_keyboard(product_id, offers))
    decorated = render_procurement_product

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        if not _handoff_state(db, player_id):
            await original(target, db, game, player_id, flash=flash)
            return
        free_cash = tutorial._free_cash(game, player_id)
        body = f'<b>{PRODUCT.label}</b>\n\nСвободно: <b>{money(free_cash)}</b>\n\n' + tutorial_hint(f'Нажми [{WAREHOUSE.label}]')
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, notice(flash, body), markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded

def handoff_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        wrapped = _return_target(target) if _handoff_state(db, player_id) else target
        await original(wrapped, db, game, player_id, flash=flash)
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_procurement_product(original):
    @wraps(original)
    async def render_procurement_product(target, game, player_id: int, product_id: int, *, flash: str | None=None) -> None:
        if not _handoff_state(game.db, player_id):
            await original(target, game, player_id, product_id, flash=flash)
            return
        await original(_return_target(target), game, player_id, product_id, flash=flash)
    decorated = render_procurement_product

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_storefront(original):
    @wraps(original)
    async def render_storefront_root(target, db, game, simulation_engine, player_id: int) -> None:
        wrapped = _return_target(target) if _handoff_state(db, player_id) else target
        await original(wrapped, db, game, simulation_engine, player_id)
    decorated = render_storefront_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_sales_product(original):
    @wraps(original)
    async def render_sales_product(target, db, player_id: int, product_id: int) -> None:
        wrapped = _return_target(target) if _handoff_state(db, player_id) else target
        await original(wrapped, db, player_id, product_id)
    decorated = render_sales_product

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_listing(original):
    @wraps(original)
    async def render_listing(target, db, game, player_id: int, listing_id: int) -> None:
        wrapped = _return_target(target) if _handoff_state(db, player_id) else target
        await original(wrapped, db, game, player_id, listing_id)
    decorated = render_listing

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_inbox(original):
    @wraps(original)
    async def render_inbox(target, game, simulation_engine, player_id: int, *, flash: str | None=None, page: int=0) -> None:
        wrapped = _return_target(target) if _handoff_state(game.db, player_id) else target
        await original(wrapped, game, simulation_engine, player_id, flash=flash, page=page)
    decorated = render_inbox

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_team(original):
    @wraps(original)
    async def render_team(target, game, simulation_engine, player_id: int, *, flash: str | None=None) -> None:
        wrapped = _return_target(target) if _handoff_state(game.db, player_id) else target
        await original(wrapped, game, simulation_engine, player_id, flash=flash)
    decorated = render_team

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def first_batch_quality_protection(original):
    @wraps(original)
    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        state = tutorial.tutorial_state(self.db, player_id)
        if not state or not state['active'] or state['stage'] != tutorial.STAGE_PROCUREMENT:
            return original(self, player_id, offer_id, employee_id)
        with self.db.connect() as conn:
            offer = conn.execute("SELECT offer_quality_mean, offer_quality_sigma\n                   FROM supplier_offers\n                   WHERE id=? AND player_id=? AND status='open'", (offer_id, player_id)).fetchone()
            if not offer:
                return original(self, player_id, offer_id, employee_id)
            previous_mean = offer['offer_quality_mean']
            previous_sigma = offer['offer_quality_sigma']
            conn.execute('UPDATE supplier_offers\n                   SET offer_quality_mean=84.0, offer_quality_sigma=0.0\n                   WHERE id=?', (offer_id,))
        try:
            return original(self, player_id, offer_id, employee_id)
        finally:
            with self.db.connect() as conn:
                conn.execute('UPDATE supplier_offers\n                       SET offer_quality_mean=?, offer_quality_sigma=?\n                       WHERE id=?', (previous_mean, previous_sigma, offer_id))
    decorated = buy_offer_for_employee

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


def handoff_analytics(original):
    @wraps(original)
    def render_analytics(db, player_id: int, period: str):
        text = original(db, player_id, period)
        if _handoff_state(db, player_id):
            text += "\n\n" + tutorial_hint(RETURN_TO_MENU)
        return text

    return render_analytics
