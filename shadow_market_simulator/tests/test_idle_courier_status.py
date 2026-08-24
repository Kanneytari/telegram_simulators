from __future__ import annotations

import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(71))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(72))
    return db, simulation, game


def clear_courier_work(db, courier_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM employee_tasks WHERE player_id=? AND employee_id=?", (PLAYER_ID, courier_id))
        conn.execute("DELETE FROM retail_positions WHERE player_id=? AND employee_id=?", (PLAYER_ID, courier_id))
        conn.execute("DELETE FROM retail_allocations WHERE player_id=? AND retail_employee_id=?", (PLAYER_ID, courier_id))
        conn.execute(
            "UPDATE employees SET available=1, unavailable_until=NULL WHERE id=? AND player_id=?",
            (courier_id, PLAYER_ID),
        )


def employee_view(game, employee_id: int):
    return next(row for row in game.employees(PLAYER_ID) if int(row["id"]) == employee_id)


def test_green_means_completely_idle_and_ready_for_new_delivery(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        couriers = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY id",
            (PLAYER_ID,),
        ).fetchall()
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=? AND status='warehouse' AND remaining>0 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='warehouse' AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()

    assert len(couriers) >= 2
    first = int(couriers[0]["id"])
    second = int(couriers[1]["id"])
    clear_courier_work(db, first)
    clear_courier_work(db, second)

    assert employee_view(game, first)["idle_ready"] is True

    with db.connect() as conn:
        conn.execute("UPDATE employees SET available=0 WHERE id=?", (first,))
    paused = employee_view(game, first)
    assert paused["exposure"] == 0
    assert paused["idle_ready"] is False

    with db.connect() as conn:
        conn.execute("UPDATE employees SET available=1 WHERE id=?", (first,))
        if batch["responsible_employee_id"] is None:
            conn.execute("UPDATE batches SET responsible_employee_id=? WHERE id=?", (warehouse["id"], batch["id"]))
        conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status
               ) VALUES (?, ?, ?, ?, ?, 5, ?, ?, 'waiting')""",
            (
                PLAYER_ID,
                batch["id"],
                warehouse["id"],
                first,
                batch["product_id"],
                batch["unit_cost"],
                batch["quality"],
            ),
        )

    waiting = employee_view(game, first)
    assert waiting["exposure"] == 0
    assert waiting["idle_ready"] is False

    _, recipients = game.retail_staff_for_batch(PLAYER_ID, int(batch["id"]))
    first_recipient = next(row for row in recipients if int(row["id"]) == first)
    second_recipient = next(row for row in recipients if int(row["id"]) == second)
    assert first_recipient["idle_ready"] is False
    assert second_recipient["idle_ready"] is True


def test_paused_courier_cannot_receive_new_assignment(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            "SELECT id FROM batches WHERE player_id=? AND status='warehouse' AND remaining>0 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        conn.execute("UPDATE employees SET available=0 WHERE id=?", (courier["id"],))

    result = game.allocate_to_retail(PLAYER_ID, int(batch["id"]), int(courier["id"]), 5)
    assert "на паузе" in result
