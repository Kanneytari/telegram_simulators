from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "shadow_market_simulator" / "tests"


def replace(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path.name}: pattern not found")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def replace_function(path: Path, name: str, source: str | None) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    target = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), None)
    if target is None:
        raise RuntimeError(f"{path.name}: function {name} not found")
    lines = text.splitlines()
    start = target.lineno - 1
    end = target.end_lineno
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    replacement = [] if source is None else source.strip("\n").splitlines()
    lines[start:end] = replacement
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# Courier core tests: keep behavioural coverage, use the current employee schema.
path = TESTS / "test_courier_core.py"
replace(
    path,
    '''            """INSERT INTO employees(\n                   player_id, alias, role, pay_per_job, deposit, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (?, ?, 'courier', 0, 50000, 0, ?, ?, ?, 0.60, ?)""",''',
    '''            """INSERT INTO employees(\n                   player_id, alias, role, deposit, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (?, ?, 'courier', 50000, 0, ?, ?, ?, 0.60, ?)""",''',
)

# Candidate phone equipment now lives in the canonical candidate profile.
path = TESTS / "test_courier_management.py"
replace(path, "def test_candidate_phone_is_visible_and_transfers_on_hire", "def test_candidate_phone_profile_transfers_on_hire")
replace(path, "SELECT * FROM courier_candidate_equipment WHERE candidate_id=?", "SELECT * FROM courier_candidate_profiles WHERE candidate_id=?")
replace(path, '    assert "Телефон:" in candidate["summary"]\n', '    assert equipment is not None\n    assert int(equipment["phone_level"]) in {0, 1, 2}\n')

# Individual leave requests were removed from the game; timer scaling remains covered separately.
replace_function(TESTS / "test_extended_systems.py", "test_leave_request_uses_game_time_not_real_time", None)

# Global packaging is shop-wide and independent from removed per-job compensation fields.
path = TESTS / "test_global_packaging.py"
replace(
    path,
    '''            """INSERT INTO employees(\n                   player_id, alias, role, pay_per_job, deposit,\n                   deposit_contribution_pct, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (?, 'Новый', 'courier', 0, 50000, 0, 0,\n                         0.8, 0.8, 0.8, 0.7, 10)""",''',
    '''            """INSERT INTO employees(\n                   player_id, alias, role, deposit, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (?, 'Новый', 'courier', 50000, 0,\n                         0.8, 0.8, 0.8, 0.7, 10)""",''',
)

# Core simulation tests must exercise the final runtime facade and current starter-state semantics.
path = TESTS / "test_simulation.py"
replace(path, "from app.game import GameService\nfrom app.courier_management import CourierManagementSimulationEngine, iso, utcnow", "from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine\nfrom app.simulation import iso, utcnow")
replace(path, "game = GameService(db, simulation, rng=rng)", "game = CourierManagementGameService(db, simulation, rng=rng)")
replace_function(
    path,
    "test_time_advance_creates_orders_and_updates_stock",
    '''def test_time_advance_without_retail_stock_creates_no_orders(tmp_path):
    db, simulation, _ = make_game(tmp_path)
    before = utcnow() - timedelta(hours=4)
    with db.connect() as conn:
        conn.execute("UPDATE shops SET last_simulated_at=? WHERE player_id=1001", (iso(before),))
        initial_stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    result = simulation.advance(1001, utcnow())
    with db.connect() as conn:
        orders = conn.execute("SELECT COUNT(*) FROM orders WHERE player_id=1001").fetchone()[0]
        stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    assert result.orders_created == 0
    assert orders == 0
    assert stock == initial_stock''',
)
replace_function(
    path,
    "test_procurement_spends_cash_and_creates_ledger_entry",
    '''def test_procurement_spends_cash_and_creates_ledger_entry(tmp_path):
    db, _, game = make_game(tmp_path)
    offer = game.offers(1001)[0]
    total = int(offer["quantity"] * offer["unit_cost"])
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=100000000 WHERE player_id=1001")
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 LIMIT 1"
        ).fetchone()
        before = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        ledger_before = int(conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE player_id=1001 AND kind='procurement'"
        ).fetchone()[0])
    game.buy_offer_for_employee(1001, int(offer["id"]), int(warehouse["id"]))
    with db.connect() as conn:
        after = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        ledger_after = int(conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE player_id=1001 AND kind='procurement'"
        ).fetchone()[0])
    assert after == before - total
    assert ledger_after == ledger_before + 1''',
)

# Staff insight helpers are implementation layers; player-facing profile behaviour is tested through the final facade.
path = TESTS / "test_staff_insights.py"
replace(path, "from app.staff_insights import StaffInsightGameService, StaffInsightSimulationEngine", "from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine")
replace(path, "simulation = StaffInsightSimulationEngine(db, speed=1.0, rng=random.Random(41))", "simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(41))")
replace(path, "game = StaffInsightGameService(db, simulation, rng=random.Random(42))", "game = CourierManagementGameService(db, simulation, rng=random.Random(42))")

# Starter retail stock is intentionally empty until the player distributes it.
path = TESTS / "test_workflow_pipeline.py"
replace(path, "def test_starter_state_has_wholesale_stock_and_published_retail_positions", "def test_starter_state_keeps_stock_with_wholesale_until_manual_distribution")
replace(path, "    assert published > 0\n", "    assert published == 0\n", count=1)
replace_function(
    path,
    "test_overexposed_dishonest_employee_can_abscond_and_deposit_is_forfeited",
    '''def test_overexposed_dishonest_employee_can_abscond_and_deposit_is_forfeited(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute(
            "UPDATE employees SET deposit=1, honesty=0.0, loyalty=0.0, stress=100 WHERE id=?",
            (employee["id"],),
        )
        before = game._employee_exposure(1001, int(employee["id"]))
        assert before > 1

    class ForcedRisk:
        def random(self):
            return 0.0

        def choice(self, values):
            return values[-1]

    simulation.rng = ForcedRisk()
    with db.connect() as conn:
        created = simulation._check_overexposure_risk(conn, 1001, 24, utcnow())
    with db.connect() as conn:
        updated = conn.execute("SELECT * FROM employees WHERE id=?", (employee["id"],)).fetchone()
        event = conn.execute(
            "SELECT * FROM inbox WHERE player_id=1001 AND kind='employee_exit' AND priority='urgent' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert created == 1
    assert updated["active"] == 0
    assert updated["deposit"] == 0
    assert event is not None
    assert "Потерянный товар вернуть нельзя" in event["body"]''',
)
