from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot import OneShotCallbackMiddleware
from app.staff.couriers.management import CourierManagementGameService, CourierManagementSimulationEngine
from app.core.database import Database
from app.tutorial import STARTING_FREE_CASH, enable_runtime, enable_runtime


PLAYER_ID = 987654


def make_release_system(tmp_path):

    db = Database(str(tmp_path / "release.db"))
    db.init()
    db.init()
    enable_runtime(db)

            
    simulation = CourierManagementSimulationEngine(
        db, speed=1.0, rng=random.Random(701)
    )
    simulation.seed_catalog()
    created = simulation.ensure_player(PLAYER_ID, "release-audit")
    game = CourierManagementGameService(
        db, simulation, rng=random.Random(702)
    )
    return db, simulation, game, created


def test_fresh_release_start_has_empty_stock_and_current_copy(tmp_path):
    db, _, game, created = make_release_system(tmp_path)
    assert created is True

    with db.connect() as conn:
        batch_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM batches WHERE player_id=?",
                (PLAYER_ID,),
            ).fetchone()[0]
        )
        tutorial = conn.execute(
            """SELECT title, body FROM inbox
               WHERE player_id=? AND kind='tutorial' AND status='open'""",
            (PLAYER_ID,),
        ).fetchone()
        state = conn.execute(
            "SELECT stage, active FROM tutorial_state WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchone()
        free_cash = int(game._free_cash_conn(conn, PLAYER_ID))

    assert batch_count == 0
    assert tutorial is not None
    assert tutorial["title"] == "Первая смена"
    assert "Склад пуст" in tutorial["body"]
    assert "Стартовые партии" not in tutorial["body"]
    assert state["stage"] == "procurement"
    assert int(state["active"]) == 1
    assert free_cash == STARTING_FREE_CASH


def test_compensation_editor_accepts_accumulated_draft_delta(tmp_path):
    _, _, game, _ = make_release_system(tmp_path)
    before = game.compensation_policy(PLAYER_ID, "courier")

    result = game.adjust_compensation_policy(
        PLAYER_ID, "courier", "fixed_fee", 100
    )

    after = game.compensation_policy(PLAYER_ID, "courier")
    assert result["changed"] is True
    assert after["fixed_fee"] == before["fixed_fee"] + 100


def _callback(data: str, message_id: int = 500) -> CallbackQuery:
    return CallbackQuery(
        id=f"cb-{message_id}-{data}",
        from_user=User(id=PLAYER_ID, is_bot=False, first_name="Audit"),
        chat_instance="release-audit",
        data=data,
        message=Message(
            message_id=message_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=PLAYER_ID, type="private"),
        ),
    )


def test_exact_replayed_handoff_confirmation_changes_inventory_once(tmp_path):
    db, _, game, _ = make_release_system(tmp_path)
    with db.connect() as conn:
        warehouse = conn.execute(
            """SELECT id FROM employees
               WHERE player_id=? AND active=1 AND role='warehouse' LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()
        courier = conn.execute(
            """SELECT id FROM employees
               WHERE player_id=? AND active=1 AND role='courier' LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()
        cur = conn.execute(
            """INSERT INTO batches(
                   player_id, supplier_id, product_id, responsible_employee_id,
                   quantity, remaining, unit_cost, quality, status
               ) VALUES (?, 1, 1, ?, 20, 20, 1000, 84, 'warehouse')""",
            (PLAYER_ID, int(warehouse["id"])),
        )
        batch_id = int(cur.lastrowid)

    data = f"team:allocdo:{batch_id}:{int(courier['id'])}:10"
    event = _callback(data)
    middleware = OneShotCallbackMiddleware()
    calls = 0

    async def handler(callback, _data):
        nonlocal calls
        calls += 1
        return game.allocate_to_retail(
            callback.from_user.id,
            batch_id,
            int(courier["id"]),
            10,
        )

    async def run_twice():
        await middleware(handler, event, {})
        await middleware(handler, event, {})

    asyncio.run(run_twice())

    with db.connect() as conn:
        remaining = int(
            conn.execute(
                "SELECT remaining FROM batches WHERE id=?", (batch_id,)
            ).fetchone()[0]
        )
        allocations = int(
            conn.execute(
                """SELECT COUNT(*) FROM retail_allocations
                   WHERE player_id=? AND batch_id=? AND retail_employee_id=?""",
                (PLAYER_ID, batch_id, int(courier["id"])),
            ).fetchone()[0]
        )

    assert calls == 1
    assert remaining == 10
    assert allocations == 1


def test_failed_one_shot_handler_can_be_retried():
    event = _callback("team:roleconfirm:12", message_id=777)
    middleware = OneShotCallbackMiddleware()
    calls = 0

    async def handler(_callback, _data):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient failure")
        return "ok"

    async def run_retry():
        try:
            await middleware(handler, event, {})
        except RuntimeError:
            pass
        return await middleware(handler, event, {})

    assert asyncio.run(run_retry()) == "ok"
    assert calls == 2


def test_role_and_upgrade_confirms_are_one_shot_callbacks():
    assert OneShotCallbackMiddleware._is_one_shot("team:roleconfirm:12")
    assert OneShotCallbackMiddleware._is_one_shot("team:upgradedo:12:transport")
    assert OneShotCallbackMiddleware._is_one_shot("team:allocdo:1:2:10")
    assert not OneShotCallbackMiddleware._is_one_shot("team:termsdraft:fixed_fee:50")
    assert not OneShotCallbackMiddleware._is_one_shot("sales:price:1:5")
