from __future__ import annotations

import random

from app.staff.couriers.management import CourierManagementGameService, CourierManagementSimulationEngine
from app.core.database import Database
from app.engine.simulation import utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, rng=random.Random(71))
    simulation.ensure_player(1001, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(72))
    return db, simulation, game


def test_low_loyalty_employee_can_give_resignation_notice(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE retail_positions SET position_count=0 WHERE employee_id=?", (employee["id"],))
        conn.execute("UPDATE retail_allocations SET status='completed' WHERE retail_employee_id=?", (employee["id"],))
        conn.execute("UPDATE employee_tasks SET status='completed' WHERE employee_id=?", (employee["id"],))
        conn.execute(
            "UPDATE employees SET loyalty=0.0, stress=100, available=1 WHERE id=?",
            (employee["id"],),
        )

    class ForcedRng:
        def random(self):
            return 0.0

        def uniform(self, a, b):
            return (a + b) / 2

        def choice(self, values):
            return values[0]

    simulation.rng = ForcedRng()
    with db.connect() as conn:
        created = simulation._simulate_management_events(conn, 1001, 12, utcnow())

    with db.connect() as conn:
        notice = conn.execute(
            """SELECT * FROM inbox
               WHERE player_id=1001 AND kind='resignation_notice' AND status='open'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        updated = conn.execute("SELECT * FROM employees WHERE id=?", (employee["id"],)).fetchone()

    assert created >= 1
    assert notice is not None
    assert updated["active"] == 1
    assert updated["available"] == 0
    assert game._task_status(1001, int(employee["id"])) == "готовится уйти"


def test_resigning_employee_still_requires_normal_deposit_settlement(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE retail_positions SET position_count=0 WHERE employee_id=?", (employee["id"],))
        conn.execute("UPDATE retail_allocations SET status='completed' WHERE retail_employee_id=?", (employee["id"],))
        conn.execute("UPDATE employee_tasks SET status='completed' WHERE employee_id=?", (employee["id"],))
        conn.execute("UPDATE employees SET available=0 WHERE id=?", (employee["id"],))
        conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
               VALUES (1001, 'resignation_notice', 'important', 'Сотрудник хочет уйти', 'test', ?)""",
            (f'{{"employee_id":{int(employee["id"])}}}',),
        )
        balance_before = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        deposit = int(employee["deposit"])
        wages = int(employee["wages_accrued"])

    result = game.fire_employee(1001, int(employee["id"]))

    with db.connect() as conn:
        balance_after = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        updated = conn.execute("SELECT * FROM employees WHERE id=?", (employee["id"],)).fetchone()
        open_notice = int(conn.execute(
            """SELECT COUNT(*) FROM inbox
               WHERE player_id=1001 AND status='open'
                 AND json_extract(payload_json, '$.employee_id')=?""",
            (employee["id"],),
        ).fetchone()[0])

    assert result["status"] == "ok"
    assert balance_before - balance_after == deposit + wages
    assert updated["active"] == 0
    assert updated["deposit"] == 0
    assert open_notice == 0
