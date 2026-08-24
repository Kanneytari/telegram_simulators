from __future__ import annotations

import asyncio
import random
import tempfile
from pathlib import Path

from app.courier_management import (
    CourierManagementGameService,
    CourierManagementSimulationEngine,
)
from app.db import Database
from app.gameplay_updates import apply_gameplay_updates
from app.handoff_copy_update import apply_handoff_copy_update
from app.product_ui_update import apply_product_ui_update
from app import tutorial, ui_commerce, ui_navigation
from app.tutorial_runtime import apply_tutorial_runtime_fixes


class Target:
    def __init__(self) -> None:
        self.text = ""
        self.reply_markup = None

    async def edit_text(self, text, **kwargs) -> None:
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")

    async def answer(self, text, **kwargs) -> None:
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")


def _callbacks(markup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def _build_game(tmp: str):
    apply_gameplay_updates()
    apply_handoff_copy_update()
    apply_product_ui_update()

    db = Database(str(Path(tmp) / "tutorial-nonblocking.db"))
    db.init()
    tutorial.apply_tutorial_updates()
    apply_tutorial_runtime_fixes()

    simulation = CourierManagementSimulationEngine(
        db,
        speed=1.0,
        rng=random.Random(41),
    )
    simulation.seed_catalog()
    game = CourierManagementGameService(
        db,
        simulation,
        rng=random.Random(42),
    )
    return db, simulation, game


def test_tutorial_keeps_normal_main_menu_and_all_products() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db, simulation, game = _build_game(tmp)
        player_id = 77001
        assert simulation.ensure_player(player_id, "soft-guide") is True

        target = Target()
        asyncio.run(
            ui_navigation.render_home(
                target,
                db,
                game,
                simulation,
                frozenset(),
                player_id,
            )
        )
        callbacks = _callbacks(target.reply_markup)
        assert {
            "menu:inbox",
            "menu:product",
            "menu:storefront",
            "menu:team",
            "menu:analytics",
        } <= callbacks

        products = game.procurement_products(player_id)
        with db.connect() as conn:
            active_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM products WHERE active=1"
                ).fetchone()[0]
            )
        assert len(products) == active_count


def test_tutorial_copy_is_plain_and_uses_current_terms() -> None:
    stages = (
        tutorial.STAGE_PROCUREMENT,
        tutorial.STAGE_PICKUP_WAIT,
        tutorial.STAGE_HANDOFF,
        tutorial.STAGE_HANDOFF_WAIT,
        tutorial.STAGE_PREP_WAIT,
        tutorial.STAGE_PRICE,
        tutorial.STAGE_SALE_WAIT,
        tutorial.STAGE_REVIEW,
        tutorial.STAGE_DISPUTE,
        tutorial.STAGE_TEAM,
    )
    for stage in stages:
        text = tutorial._instruction({"stage": stage, "data": {}})
        assert "—" not in text
        assert ";" not in text
        assert "«" not in text and "»" not in text
        assert "позици" not in text.lower()

    price = tutorial._instruction({"stage": tutorial.STAGE_PRICE, "data": {}})
    assert price.startswith("Вернись в меню и нажми 🏷 Витрина.")

    team = tutorial._instruction({"stage": tutorial.STAGE_TEAM, "data": {}})
    assert "какая часть нового товара будет продаваться по 1, 2 и 5 единиц" in team
    assert "публикац" not in team.lower()


def test_storefront_tutorial_says_only_choose_packaging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db, simulation, game = _build_game(tmp)
        player_id = 77002
        assert simulation.ensure_player(player_id, "pack-copy") is True
        tutorial._set_stage(db, player_id, tutorial.STAGE_PRICE)

        original = ui_commerce._product_listings
        ui_commerce._product_listings = lambda _db, _pid, _product_id: (
            {"title": "MDMA"},
            [
                {"id": 1, "pack_size": 1, "price": 9000, "positions": 2},
                {"id": 2, "pack_size": 2, "price": 17000, "positions": 1},
                {"id": 3, "pack_size": 5, "price": 40000, "positions": 0},
            ],
            4,
            4.5,
            2,
        )
        try:
            target = Target()
            asyncio.run(
                ui_commerce.render_sales_product(
                    target,
                    db,
                    player_id,
                    2,
                )
            )
        finally:
            ui_commerce._product_listings = original

        assert "Выбери фасовку." in target.text
        assert "Выбери фасовку, у которой" not in target.text
        assert {"sales:listing:1", "sales:listing:2", "sales:listing:3"} <= _callbacks(
            target.reply_markup
        )
