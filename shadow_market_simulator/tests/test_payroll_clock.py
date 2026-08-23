import random

from app.db import Database
from app.nightshift import NightshiftSimulationEngine
from app.services import FinalGameService


def test_new_player_initializes_payroll_clock_on_first_check(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = NightshiftSimulationEngine(db, speed=1.0, rng=random.Random(1))
    simulation.ensure_player(1001, "tester")
    game = FinalGameService(db, simulation, rng=random.Random(2))

    with db.connect() as conn:
        before = conn.execute(
            "SELECT last_payroll_at FROM settings WHERE player_id=1001"
        ).fetchone()[0]
    assert before is None

    assert game.process_payroll(1001) is None

    with db.connect() as conn:
        after = conn.execute(
            "SELECT last_payroll_at FROM settings WHERE player_id=1001"
        ).fetchone()[0]
    assert after is not None
