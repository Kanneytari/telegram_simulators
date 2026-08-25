from __future__ import annotations

import subprocess
import sys
import textwrap


def test_guided_first_cycle_end_to_end() -> None:
    script = textwrap.dedent(
        r'''
        import random
        import tempfile
        from pathlib import Path

        from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
        from app.db import Database
        from app.gameplay_updates import apply_gameplay_updates
        from app.handoff_copy_update import apply_handoff_copy_update
        from app.product_ui_update import apply_product_ui_update
        from app.release_fixes import apply_release_fixes
        from app.tutorial import (
            STAGE_DISPUTE,
            STAGE_HANDOFF,
            STAGE_HANDOFF_WAIT,
            STAGE_PICKUP_WAIT,
            STAGE_PREP_WAIT,
            STAGE_PRICE,
            STAGE_REVIEW,
            STAGE_SALE_WAIT,
            STAGE_TEAM,
            _finish_tutorial,
            create_tutorial_dispute,
            tutorial_state,
        )
        from app.tutorial_copy_update import apply_tutorial_copy_update
        from app.tutorial_runtime import apply_tutorial_runtime_fixes
        import app.tutorial as tutorial

        apply_gameplay_updates()
        apply_handoff_copy_update()
        apply_product_ui_update()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "tutorial.db"))
            db.init()

            tutorial.apply_tutorial_updates()
            apply_tutorial_runtime_fixes()
            apply_tutorial_copy_update()
            apply_release_fixes()

            simulation = CourierManagementSimulationEngine(
                db,
                speed=60.0,
                rng=random.Random(101),
            )
            simulation.seed_catalog()
            game = CourierManagementGameService(
                db,
                simulation,
                rng=random.Random(202),
            )

            player_id = 991337
            assert simulation.ensure_player(player_id, "tutorial") is True

            state = tutorial_state(db, player_id)
            assert state and state["active"] and state["stage"] == "procurement"
            with db.connect() as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM batches WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0] == 0
                assert game._free_cash_conn(conn, player_id) == 500_000
                onboarding = conn.execute(
                    """SELECT body FROM inbox
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (player_id,),
                ).fetchone()
                assert onboarding and "Склад пуст" in onboarding["body"]

            products = game.procurement_products(player_id)
            assert products
            offer = None
            for product in products:
                offers = game.offers(player_id, int(product["id"]))
                if offers:
                    offer = offers[0]
                    break
            assert offer is not None

            warehouse = game.warehouse_staff_for_offer(player_id, int(offer["id"]))
            assert warehouse
            result = game.buy_offer_for_employee(
                player_id,
                int(offer["id"]),
                int(warehouse[0]["id"]),
            )
            assert "точно дойдёт" not in result
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_PICKUP_WAIT
            batch_id = int(state["data"]["batch_id"])
            with db.connect() as conn:
                batch = conn.execute(
                    "SELECT status FROM batches WHERE id=? AND player_id=?",
                    (batch_id, player_id),
                ).fetchone()
                assert batch and batch["status"] == "receiving"

            tutorial.skip_tutorial_wait(game, simulation, player_id)
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_HANDOFF
            with db.connect() as conn:
                assert conn.execute(
                    "SELECT status FROM batches WHERE id=?",
                    (batch_id,),
                ).fetchone()[0] == "warehouse"

            batch, couriers = game.retail_staff_for_batch(player_id, batch_id)
            assert batch and couriers
            courier = couriers[0]
            quantity = min(10, int(batch["remaining"]))
            assert quantity > 0
            game.allocate_to_retail(
                player_id,
                batch_id,
                int(courier["id"]),
                quantity,
            )
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_HANDOFF_WAIT

            tutorial.skip_tutorial_wait(game, simulation, player_id)
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_PREP_WAIT

            tutorial.skip_tutorial_wait(game, simulation, player_id)
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_PRICE
            with db.connect() as conn:
                ready = conn.execute(
                    """SELECT l.id
                       FROM retail_positions rp
                       JOIN listings l
                         ON l.player_id=rp.player_id
                        AND l.product_id=rp.product_id
                        AND l.pack_size=rp.pack_size
                       WHERE rp.player_id=? AND rp.position_count>0 AND l.active=1
                       ORDER BY l.id LIMIT 1""",
                    (player_id,),
                ).fetchone()
            assert ready

            listing_id = int(ready["id"])
            game.change_listing_price(player_id, listing_id, 5)
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_SALE_WAIT

            tutorial.skip_tutorial_wait(game, simulation, player_id)
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_REVIEW
            order_id = int(state["data"]["order_id"])
            with db.connect() as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE id=? AND player_id=?",
                    (order_id, player_id),
                ).fetchone()[0] == 1
                assert conn.execute(
                    "SELECT COUNT(*) FROM disputes WHERE order_id=?",
                    (order_id,),
                ).fetchone()[0] == 0

            created = create_tutorial_dispute(game, simulation, player_id)
            assert created is not None
            dispute_id, _ = created
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_DISPUTE

            game.resolve_dispute_with_source(
                player_id,
                dispute_id,
                "partial",
                "shop",
            )
            state = tutorial_state(db, player_id)
            assert state["stage"] == STAGE_TEAM

            _finish_tutorial(db, player_id)
            state = tutorial_state(db, player_id)
            assert state and not state["active"]
        '''
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
