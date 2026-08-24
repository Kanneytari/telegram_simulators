from __future__ import annotations

import random
import re
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "shadow_market_simulator"
APP = PROJECT / "app"


def assert_static_cleanup() -> None:
    forbidden_tokens = (
        "pay_per_job",
        "desired_pay",
        "offered_pay",
        "raise_request",
        "leave_request",
        "advance_request",
        "recruitment_runtime",
        "catalog_extension",
        "workflow_final",
        "FinalGameService",
        "FinalWorkflow",
        "_sync_legacy_mirrors_conn",
        "ALTER TABLE",
    )
    hits: list[str] = []
    for path in sorted(APP.glob("*")):
        if path.suffix not in {".py", ".sql"}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token.lower() in text.lower():
                hits.append(f"{path.name}: {token}")
        if path.suffix == ".py" and re.search(r"\b(legacy|compatibility|backward[-_ ]compat)\b", text, re.I):
            hits.append(f"{path.name}: legacy/compatibility wording")
    if hits:
        raise AssertionError("Legacy references remain:\n" + "\n".join(hits))

    obsolete_files = (
        "services.py",
        "workflow_final.py",
        "recruitment_runtime.py",
        "catalog_extension.py",
        "detailed_analytics.py",
    )
    present = [name for name in obsolete_files if (APP / name).exists()]
    if present:
        raise AssertionError(f"Obsolete modules still exist: {present}")

    migrations = [
        str(path.relative_to(PROJECT))
        for path in PROJECT.rglob("*")
        if path.is_file() and "migration" in path.name.lower()
    ]
    if migrations:
        raise AssertionError(f"Migration files remain: {migrations}")


def assert_schema(conn) -> None:
    def columns(table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    employee_columns = columns("employees")
    assert "pay_per_job" not in employee_columns
    assert "deposit_contribution_pct" not in employee_columns
    assert {"wages_accrued", "deposit_accrued", "loyalty", "stress"} <= employee_columns

    candidate_columns = columns("candidates")
    assert "desired_pay" not in candidate_columns
    assert "offered_pay" not in candidate_columns
    assert "loyalty" in candidate_columns

    client_columns = columns("clients")
    assert "loyalty" not in client_columns
    assert "review_tendency" in client_columns

    shop_columns = columns("shops")
    assert "rating" not in shop_columns
    assert "balance" in shop_columns

    table_names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "packaging_rules" not in table_names
    assert "shop_packaging_rules" in table_names
    assert "courier_candidate_equipment" not in table_names


def smoke_current_game() -> None:
    import sys

    sys.path.insert(0, str(PROJECT))
    import app.main  # noqa: F401
    from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
    from app.courier_recruitment import CourierRecruitmentService
    from app.db import Database
    from app.simulation import iso, utcnow

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "fresh.db"))
        db.init()
        with db.connect() as conn:
            assert_schema(conn)

        simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(901))
        simulation.seed_catalog()
        assert simulation.ensure_player(1001, "fresh_player") is True
        assert simulation.ensure_player(1001, "fresh_player") is False
        game = CourierManagementGameService(db, simulation, rng=random.Random(902))
        recruitment = CourierRecruitmentService(db, rng=random.Random(903))

        with db.connect() as conn:
            products = conn.execute("SELECT id, title FROM products WHERE active=1 ORDER BY id").fetchall()
            employees = conn.execute("SELECT id, role FROM employees WHERE player_id=1001 AND active=1 ORDER BY id").fetchall()
            auto_candidates = int(conn.execute("SELECT COUNT(*) FROM candidates WHERE player_id=1001").fetchone()[0])
            shop_rules = int(conn.execute("SELECT COUNT(*) FROM shop_packaging_rules WHERE player_id=1001").fetchone()[0])
            trust = conn.execute("SELECT trust_score FROM shop_trust_state WHERE player_id=1001").fetchone()
        assert [row["title"] for row in products] == ["Амфетамин", "MDMA", "Кокаин", "Мефедрон", "Кетамин", "LSD"]
        assert len(employees) == 3
        assert sum(1 for row in employees if row["role"] == "warehouse") == 1
        assert sum(1 for row in employees if row["role"] == "courier") == 2
        assert auto_candidates == 0
        assert shop_rules == 1
        assert trust is not None

        dashboard = game.dashboard(1001)
        assert "Свободные деньги" in dashboard
        assert "Доверие" in dashboard
        rule = game.global_packaging_rule(1001)
        assert rule["pct_1"] + rule["pct_2"] + rule["pct_5"] == 100
        assert game.compensation_policy(1001, "courier")["base_rate_bps"] == 400
        assert game.compensation_policy(1001, "warehouse")["base_rate_bps"] == 200

        with db.connect() as conn:
            warehouse = conn.execute(
                "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1"
            ).fetchone()
            courier = conn.execute(
                "SELECT id FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
            ).fetchone()
            batch = conn.execute(
                """SELECT id FROM batches
                   WHERE player_id=1001 AND responsible_employee_id=? AND status='warehouse' AND remaining>=10
                   ORDER BY id LIMIT 1""",
                (warehouse["id"],),
            ).fetchone()
        allocation = game.allocate_to_retail(1001, int(batch["id"]), int(courier["id"]), 10)
        assert "Назначено" in allocation

        with db.connect() as conn:
            conn.execute(
                "UPDATE employees SET wages_accrued=1000, deposit_accrued=200 WHERE id=?",
                (courier["id"],),
            )
            conn.execute("UPDATE shops SET balance=10000000 WHERE player_id=1001")
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
                (iso(utcnow() - timedelta(hours=25)),),
            )
        payroll = game.process_payroll(1001)
        assert payroll["status"] == "paid"
        assert payroll["gross"] >= 1000

        draft = recruitment.ensure_draft(1001)
        assert draft["role"] in {"courier", "warehouse"}
        quote = recruitment.quote(1001, draft)
        assert quote["policy"]["deposit_contribution_pct"] >= 0
        recruitment.start_campaign(1001)
        recruitment.fast_forward(1001, 30)
        candidates = recruitment.candidates(1001)
        assert candidates
        hire_result = game.hire_candidate(1001, int(candidates[0]["id"]))
        assert "принят" in hire_result.lower()

        with db.connect() as conn:
            hired = conn.execute(
                "SELECT * FROM employees WHERE player_id=1001 AND alias=? AND active=1",
                (candidates[0]["alias"],),
            ).fetchone()
        assert hired is not None
        assert "pay_per_job" not in hired.keys()


def main() -> None:
    assert_static_cleanup()
    smoke_current_game()
    print("STATIC_CLEANUP=OK")
    print("FRESH_DB=OK")
    print("APP_IMPORT=OK")
    print("CORE_SCENARIOS=OK")


if __name__ == "__main__":
    main()
