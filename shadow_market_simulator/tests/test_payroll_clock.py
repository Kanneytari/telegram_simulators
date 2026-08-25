import random

from app.staff.couriers.management import CourierManagementGameService, CourierManagementSimulationEngine
from app.core.database import Database


def test_new_player_initializes_payroll_clock_on_creation(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(1))
    simulation.ensure_player(1001, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(2))

    with db.connect() as conn:
        before = conn.execute(
            "SELECT last_payroll_at FROM settings WHERE player_id=1001"
        ).fetchone()[0]
    assert before is not None

    assert game.process_payroll(1001) is None

    with db.connect() as conn:
        after = conn.execute(
            "SELECT last_payroll_at FROM settings WHERE player_id=1001"
        ).fetchone()[0]
    assert after == before
