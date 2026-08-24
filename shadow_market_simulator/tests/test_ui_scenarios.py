from __future__ import annotations

import asyncio
import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database
from app.ui_commerce import render_procurement_root, render_sales_root
from app.ui_navigation import _home_snapshot, render_inbox
from app.ui_staff import render_batches, render_profile, render_recruitment_root, render_team


PLAYER_ID = 99101


class FakeMessage:
    def __init__(self):
        self.text = None
        self.markup = None

    async def edit_text(self, text, reply_markup=None):
        self.text = text
        self.markup = reply_markup

    async def answer(self, text, reply_markup=None):
        self.text = text
        self.markup = reply_markup


def make_system(tmp_path):
    db = Database(str(tmp_path / "ui.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(3301))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "ui_tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(3302))
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(3303))
    return db, simulation, game, recruitment


def test_primary_ui_screens_render_from_real_state(tmp_path):
    db, simulation, game, recruitment = make_system(tmp_path)

    home, opened, urgent = _home_snapshot(db, game, simulation, PLAYER_ID)
    assert "NIGHTSHIFT" in home
    assert isinstance(opened, int)
    assert isinstance(urgent, int)

    target = FakeMessage()
    asyncio.run(render_inbox(target, game, simulation, PLAYER_ID))
    assert "Входящие" in target.text
    assert target.markup is not None

    asyncio.run(render_procurement_root(target, db, game, PLAYER_ID))
    assert "Товар" in target.text
    assert target.markup is not None

    asyncio.run(render_sales_root(target, db, game, simulation, PLAYER_ID))
    assert "Витрина" in target.text
    assert target.markup is not None

    asyncio.run(render_team(target, game, simulation, PLAYER_ID))
    assert "Команда" in target.text
    assert target.markup is not None

    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND active=1 AND role='courier' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
    assert courier is not None
    asyncio.run(render_profile(target, game, PLAYER_ID, int(courier["id"])))
    assert "закладчик" in target.text
    assert "Развитие" in [button.text for row in target.markup.inline_keyboard for button in row]

    asyncio.run(render_batches(target, game, PLAYER_ID))
    assert "Склад" in target.text

    asyncio.run(render_recruitment_root(target, recruitment, PLAYER_ID))
    assert "Найм" in target.text
    assert target.markup is not None


def test_no_primary_screen_uses_old_home_symbol_or_storefront_name(tmp_path):
    db, simulation, game, recruitment = make_system(tmp_path)
    target = FakeMessage()

    async def collect():
        screens = []
        await render_inbox(target, game, simulation, PLAYER_ID)
        screens.append((target.text, target.markup))
        await render_procurement_root(target, db, game, PLAYER_ID)
        screens.append((target.text, target.markup))
        await render_sales_root(target, db, game, simulation, PLAYER_ID)
        screens.append((target.text, target.markup))
        await render_team(target, game, simulation, PLAYER_ID)
        screens.append((target.text, target.markup))
        await render_recruitment_root(target, recruitment, PLAYER_ID)
        screens.append((target.text, target.markup))
        return screens

    screens = asyncio.run(collect())
    for text, markup in screens:
        names = [button.text for row in markup.inline_keyboard for button in row]
        assert all("⌂" not in name for name in names)
        assert "Продажа" not in text
