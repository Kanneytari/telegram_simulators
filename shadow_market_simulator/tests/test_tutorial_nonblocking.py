from __future__ import annotations

import subprocess
import sys
import textwrap


def test_tutorial_is_nonblocking_and_uses_plain_copy() -> None:
    script = textwrap.dedent(
        r'''
        import asyncio
        import random
        import tempfile
        from pathlib import Path

        from app import tutorial, ui_commerce, ui_navigation
        from app.courier_management import (
            CourierManagementGameService,
            CourierManagementSimulationEngine,
        )
        from app.db import Database
        from app.gameplay_updates import apply_gameplay_updates
        from app.handoff_copy_update import apply_handoff_copy_update
        from app.product_ui_update import apply_product_ui_update
        from app.tutorial_runtime import apply_tutorial_runtime_fixes


        class Target:
            def __init__(self):
                self.text = ""
                self.reply_markup = None
                self.photo = None

            async def edit_text(self, text, **kwargs):
                self.text = text
                self.reply_markup = kwargs.get("reply_markup")

            async def answer(self, text, **kwargs):
                self.text = text
                self.reply_markup = kwargs.get("reply_markup")


        def callbacks(markup):
            return {
                button.callback_data
                for row in markup.inline_keyboard
                for button in row
                if button.callback_data
            }


        apply_gameplay_updates()
        apply_handoff_copy_update()
        apply_product_ui_update()

        with tempfile.TemporaryDirectory() as tmp:
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
            assert {
                "menu:inbox",
                "menu:product",
                "menu:storefront",
                "menu:team",
                "menu:analytics",
            } <= callbacks(target.reply_markup)

            products = game.procurement_products(player_id)
            with db.connect() as conn:
                active_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM products WHERE active=1"
                    ).fetchone()[0]
                )
            assert len(products) == active_count

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

            price = tutorial._instruction(
                {"stage": tutorial.STAGE_PRICE, "data": {}}
            )
            assert price.startswith("Вернись в меню и нажми 🏷 Витрина.")

            team = tutorial._instruction(
                {"stage": tutorial.STAGE_TEAM, "data": {}}
            )
            assert (
                "какая часть нового товара будет продаваться по 1, 2 и 5 единиц"
                in team
            )
            assert "публикац" not in team.lower()

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
            assert {
                "sales:listing:1",
                "sales:listing:2",
                "sales:listing:3",
            } <= callbacks(target.reply_markup)
        '''
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
