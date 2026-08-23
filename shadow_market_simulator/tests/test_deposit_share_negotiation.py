from __future__ import annotations

import random

from app.db import Database
from app.wholesale_compensation import (
    DEPOSIT_SHARE_COOLDOWN_GAME_HOURS,
    WholesaleCompensationGameService,
    WholesaleCompensationSimulationEngine,
)


class FixedRng:
    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = WholesaleCompensationSimulationEngine(db, speed=1.0, rng=random.Random(201))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = WholesaleCompensationGameService(db, simulation)
    return db, simulation, game


def first_courier(db: Database):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()


def test_accepted_higher_deposit_share_changes_terms_and_hidden_state(tmp_path):
    db, simulation, game = make_system(tmp_path)
    employee = first_courier(db)
    with db.connect() as conn:
        conn.execute(
            """UPDATE employees
               SET deposit_contribution_pct=10, loyalty=0.90, stress=5
               WHERE id=?""",
            (employee["id"],),
        )

    game.rng = FixedRng(0.0)
    result = game.propose_deposit_share(1001, int(employee["id"]), 20)

    assert result["status"] == "accepted"
    with db.connect() as conn:
        updated = conn.execute(
            "SELECT deposit_contribution_pct, loyalty, stress FROM employees WHERE id=?",
            (employee["id"],),
        ).fetchone()
        negotiation = conn.execute(
            "SELECT * FROM deposit_share_negotiations WHERE employee_id=? ORDER BY id DESC LIMIT 1",
            (employee["id"],),
        ).fetchone()
    assert int(updated["deposit_contribution_pct"]) == 20
    assert float(updated["loyalty"]) < 0.90
    assert float(updated["stress"]) > 5.0
    assert negotiation["outcome"] == "accepted"
    assert int(negotiation["from_pct"]) == 10
    assert int(negotiation["to_pct"]) == 20


def test_lower_deposit_share_is_positive_for_hidden_state(tmp_path):
    db, simulation, game = make_system(tmp_path)
    employee = first_courier(db)
    with db.connect() as conn:
        conn.execute(
            """UPDATE employees
               SET deposit_contribution_pct=30, loyalty=0.50, stress=50
               WHERE id=?""",
            (employee["id"],),
        )

    game.rng = FixedRng(0.0)
    result = game.propose_deposit_share(1001, int(employee["id"]), 10)

    assert result["status"] == "accepted"
    with db.connect() as conn:
        updated = conn.execute(
            "SELECT deposit_contribution_pct, loyalty, stress FROM employees WHERE id=?",
            (employee["id"],),
        ).fetchone()
    assert int(updated["deposit_contribution_pct"]) == 10
    assert float(updated["loyalty"]) > 0.50
    assert float(updated["stress"]) < 50.0


def test_low_loyalty_can_reject_higher_deposit_share(tmp_path):
    db, simulation, game = make_system(tmp_path)
    employee = first_courier(db)
    with db.connect() as conn:
        conn.execute(
            """UPDATE employees
               SET deposit_contribution_pct=10, loyalty=0.10, stress=70
               WHERE id=?""",
            (employee["id"],),
        )

    game.rng = FixedRng(0.50)
    result = game.propose_deposit_share(1001, int(employee["id"]), 20)

    assert result["status"] == "rejected"
    with db.connect() as conn:
        updated = conn.execute(
            "SELECT deposit_contribution_pct, loyalty, stress FROM employees WHERE id=?",
            (employee["id"],),
        ).fetchone()
    assert int(updated["deposit_contribution_pct"]) == 10
    assert float(updated["loyalty"]) < 0.10
    assert float(updated["stress"]) > 70.0


def test_negotiation_has_game_time_cooldown(tmp_path):
    db, simulation, game = make_system(tmp_path)
    employee = first_courier(db)
    game.rng = FixedRng(0.0)

    first = game.propose_deposit_share(1001, int(employee["id"]), 20)
    assert first["status"] == "accepted"

    blocked = game.propose_deposit_share(1001, int(employee["id"]), 25)
    assert blocked["status"] == "cooldown"
    assert 0 < float(blocked["cooldown_game_hours"]) <= DEPOSIT_SHARE_COOLDOWN_GAME_HOURS

    with db.connect() as conn:
        conn.execute(
            "UPDATE game_clock SET game_hours=game_hours+? WHERE player_id=1001",
            (DEPOSIT_SHARE_COOLDOWN_GAME_HOURS + 0.1,),
        )

    after = game.deposit_share_context(1001, int(employee["id"]), 25)
    assert after is not None
    assert after["cooldown_game_hours"] <= 0.001
    assert after["can_propose"] is True


def test_deposit_share_is_clamped_to_supported_range_and_step(tmp_path):
    db, simulation, game = make_system(tmp_path)
    employee = first_courier(db)

    high = game.deposit_share_context(1001, int(employee["id"]), 99)
    low = game.deposit_share_context(1001, int(employee["id"]), -10)
    odd = game.deposit_share_context(1001, int(employee["id"]), 17)

    assert high["target_pct"] == 50
    assert low["target_pct"] == 0
    assert odd["target_pct"] == 15
