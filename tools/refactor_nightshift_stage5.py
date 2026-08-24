from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def fix_procurement_payment() -> None:
    path = APP / "procurement_market.py"
    text = path.read_text(encoding="utf-8")
    block = '''                conn.execute(\n                    """UPDATE employees SET jobs_done=jobs_done+1, wages_accrued=wages_accrued+?,\n                           stress=MIN(100, stress+1.2), last_contact_at=? WHERE id=?""",\n                    (employee["pay_per_job"], iso(now), employee_id),\n                )\n'''
    if block not in text:
        raise RuntimeError("procurement legacy payment block not found")
    text = text.replace(block, '''                conn.execute(\n                    "UPDATE employees SET stress=MIN(100, stress+1.2), last_contact_at=? WHERE id=?",\n                    (iso(now), employee_id),\n                )\n''', 1)
    text = text.replace(
        '            f"Начислено за операцию: {employee[\'pay_per_job\']:,} ₽"\n',
        '            "Оплата будет начислена после успешной передачи товара рознице."\n',
        1,
    )
    write(path, text)


def update_test_compensation_policy() -> None:
    path = TESTS / "test_compensation_policy.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'''\n    with db\.connect\(\) as conn:\n        legacy = conn\.execute\(\n            "SELECT pay_per_job, deposit_contribution_pct FROM employees WHERE player_id=1001"\n        \)\.fetchall\(\)\n    assert legacy\n    assert all\(int\(row\["pay_per_job"\]\) == 0 for row in legacy\)\n    assert all\(int\(row\["deposit_contribution_pct"\]\) == 0 for row in legacy\)''',
        "",
        text,
        count=1,
    )
    write(path, text)


def update_catalog_expectations() -> None:
    path = TESTS / "test_procurement_market.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("assert len(counts) == 3 * len(PROCUREMENT_BATCH_SIZES)", "assert len(counts) == 6 * len(PROCUREMENT_BATCH_SIZES)")
    write(path, text)

    path = TESTS / "test_simulation.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("== 9", "== 18", 1)
    # Historical SimulationEngine tests must exercise the actual runtime engine now.
    text = text.replace("from app.simulation import SimulationEngine", "from app.courier_management import CourierManagementSimulationEngine")
    text = text.replace("SimulationEngine(db", "CourierManagementSimulationEngine(db")
    write(path, text)

    path = TESTS / "test_storefront_disputes.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        'assert [row["title"] for row in products] == ["Амфетамин", "MDMA", "Кокаин"]',
        'assert [row["title"] for row in products] == ["Амфетамин", "MDMA", "Кокаин", "Мефедрон", "Кетамин", "LSD"]',
    )
    write(path, text)


def remove_obsolete_sales_pacing_tests() -> None:
    path = TESTS / "test_sales_pacing.py"
    if path.exists():
        path.unlink()


def remove_legacy_team_keyboard_tests() -> None:
    path = TESTS / "test_team_keyboard.py"
    if path.exists():
        path.unlink()


def update_workflow_tests() -> None:
    path = TESTS / "test_workflow_pipeline.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "from app.workflow_final import FinalWorkflowGameService, FinalWorkflowSimulationEngine",
        "from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine",
    )
    text = text.replace("FinalWorkflowSimulationEngine(db", "CourierManagementSimulationEngine(db")
    text = text.replace("FinalWorkflowGameService(db", "CourierManagementGameService(db")
    text = re.sub(
        r"game\.adjust_packaging_rule\(1001, int\(retail\[\"id\"\]\), 1, 5, 10\)",
        "game.adjust_global_packaging_rule(1001, 5, 10)",
        text,
    )
    # The canonical packaging rule is shop-wide, so inspect that table directly.
    text = text.replace(
        '''SELECT * FROM packaging_rules\n               WHERE player_id=1001 AND employee_id=? AND product_id=1''',
        '''SELECT * FROM shop_packaging_rules\n               WHERE player_id=1001''',
    )
    text = text.replace(',\n            (retail["id"],),\n        ).fetchone()', ',\n        ).fetchone()', 1)
    write(path, text)


def clean_stage4_test_imports() -> None:
    for path in TESTS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("from app.recruitment_runtime import RETAIL_STARTING_DEPOSIT_CAP", "from app.recruitment import RETAIL_STARTING_DEPOSIT_CAP")
        text = text.replace("from app.recruitment_runtime import NightshiftRecruitmentService", "from app.recruitment import RecruitmentService")
        text = text.replace("NightshiftRecruitmentService(", "RecruitmentService(")
        write(path, text)


def main() -> None:
    fix_procurement_payment()
    update_test_compensation_policy()
    update_catalog_expectations()
    remove_obsolete_sales_pacing_tests()
    remove_legacy_team_keyboard_tests()
    update_workflow_tests()
    clean_stage4_test_imports()


if __name__ == "__main__":
    main()
