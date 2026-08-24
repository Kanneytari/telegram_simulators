from __future__ import annotations

import random
from datetime import timedelta

from app.db import Database
from app.simulation import utcnow
from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, rng=random.Random(31))
    simulation.ensure_player(1001, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(32))
    return db, simulation, game


def test_starter_state_keeps_stock_with_wholesale_until_manual_distribution(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        wholesale = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1"
        ).fetchone()
        published = int(conn.execute(
            "SELECT COALESCE(SUM(position_count),0) FROM retail_positions WHERE player_id=1001"
        ).fetchone()[0])
    assert wholesale is not None
    assert game._employee_exposure(1001, int(wholesale["id"])) > 0
    assert published == 0


def test_purchase_may_exceed_deposit_and_creates_receiving_task(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE employees SET deposit=10000 WHERE id=?", (employee["id"],))
        conn.execute("UPDATE shops SET balance=3000000 WHERE player_id=1001")
        conn.execute("UPDATE suppliers SET reliability=1.0 WHERE id=1")
        cur = conn.execute(
            """INSERT INTO supplier_offers(
                   player_id, supplier_id, product_id, quantity, unit_cost,
                   quality_hint, expires_at
               ) VALUES (1001, 1, 1, 100, 3000, 'стабильное', datetime('now','+1 day'))"""
        )
        offer_id = cur.lastrowid

    staff = game.warehouse_staff_for_offer(1001, offer_id)
    selected = next(row for row in staff if row["id"] == employee["id"])
    assert selected["eligible"] is True
    assert selected["unsecured_after"] > 0

    result = game.buy_offer_for_employee(1001, offer_id, int(employee["id"]))
    with db.connect() as conn:
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id DESC LIMIT 1").fetchone()
        task = conn.execute(
            "SELECT * FROM employee_tasks WHERE batch_id=? AND kind='receive_batch'",
            (batch["id"],),
        ).fetchone()
    assert "Не покрыто депозитом" in result
    assert batch["status"] == "receiving"
    assert task is not None


def test_manual_allocation_flows_to_packaging_and_storefront(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        wholesale = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
        retail = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            """SELECT * FROM batches WHERE player_id=1001 AND responsible_employee_id=?
               AND status='warehouse' AND remaining>=20 LIMIT 1""",
            (wholesale["id"],),
        ).fetchone()
        before_positions = int(conn.execute(
            """SELECT COALESCE(SUM(position_count),0) FROM retail_positions
               WHERE player_id=1001 AND employee_id=? AND product_id=?""",
            (retail["id"], batch["product_id"]),
        ).fetchone()[0])

    result = game.allocate_to_retail(1001, int(batch["id"]), int(retail["id"]), 20)
    assert "Назначено" in result
    assert "ожидает товар" in game._task_status(1001, int(retail["id"]))

    with db.connect() as conn:
        conn.execute(
            "UPDATE employee_tasks SET completes_at=datetime('now','-1 minute') WHERE player_id=1001 AND status='active'"
        )
    simulation.advance(1001, utcnow() + timedelta(minutes=2))
    with db.connect() as conn:
        conn.execute(
            "UPDATE employee_tasks SET completes_at=datetime('now','-1 minute') WHERE player_id=1001 AND status='active'"
        )
    simulation.advance(1001, utcnow() + timedelta(minutes=4))

    with db.connect() as conn:
        allocation = conn.execute(
            "SELECT * FROM retail_allocations WHERE player_id=1001 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        after_positions = int(conn.execute(
            """SELECT COALESCE(SUM(position_count),0) FROM retail_positions
               WHERE player_id=1001 AND employee_id=? AND product_id=?""",
            (retail["id"], batch["product_id"]),
        ).fetchone()[0])
    assert allocation["status"] == "published"
    assert after_positions > before_positions


def test_packaging_rule_always_sums_to_100(tmp_path):
    db, _, game = make_system(tmp_path)
    game.adjust_global_packaging_rule(1001, 5, 10)
    rule = game.global_packaging_rule(1001)
    assert rule["pct_1"] + rule["pct_2"] + rule["pct_5"] == 100
    assert rule["pct_5"] == 20


def test_role_change_requires_no_inventory_or_pending_assignment(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        wholesale = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
        retail = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' LIMIT 1"
        ).fetchone()
    blocked = game.change_employee_role(1001, int(wholesale["id"]))
    assert "не иметь назначенного товара" in blocked or "не иметь товара" in blocked

    with db.connect() as conn:
        conn.execute("UPDATE retail_positions SET position_count=0 WHERE employee_id=?", (retail["id"],))
        conn.execute("UPDATE retail_allocations SET status='completed' WHERE retail_employee_id=?", (retail["id"],))
    changed = game.change_employee_role(1001, int(retail["id"]))
    assert "оптовый" in changed


def test_manual_firing_returns_remaining_deposit(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        retail = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE retail_positions SET position_count=0 WHERE employee_id=?", (retail["id"],))
        conn.execute("UPDATE retail_allocations SET status='completed' WHERE retail_employee_id=?", (retail["id"],))
        conn.execute("UPDATE employee_tasks SET status='completed' WHERE employee_id=?", (retail["id"],))
        balance_before = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        deposit = int(retail["deposit"])
        wages = int(retail["wages_accrued"])

    result = game.fire_employee(1001, int(retail["id"]))
    with db.connect() as conn:
        balance_after = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        employee_after = conn.execute("SELECT * FROM employees WHERE id=?", (retail["id"],)).fetchone()
    assert result["status"] == "ok"
    assert balance_before - balance_after == deposit + wages
    assert employee_after["deposit"] == 0
    assert employee_after["active"] == 0
def test_overexposed_dishonest_employee_can_abscond_and_deposit_is_forfeited(tmp_path):
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
    assert "Потерянный товар вернуть нельзя" in event["body"]
