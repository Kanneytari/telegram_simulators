from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "shadow_market_simulator"
APP = PROJECT / "app"
TESTS = PROJECT / "tests"


def replace(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path.name}: pattern not found: {old!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def remove_method(path: Path, class_name: str, method_name: str) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    lines = text.splitlines()
                    start = child.lineno - 1
                    end = child.end_lineno
                    while start > node.lineno and not lines[start - 1].strip():
                        start -= 1
                    lines[start:end] = []
                    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
                    return
    raise RuntimeError(f"{path.name}: {class_name}.{method_name} not found")


replace(APP / "courier_core.py", "from .simulation import clamp, iso, utcnow", "from .simulation import clamp, iso")
replace(APP / "courier_management.py", "from .compensation import _deposit_part, _policy_conn", "from .compensation import _deposit_part")
replace(APP / "courier_recruitment.py", "from .recruitment import RecruitmentService, ROLE_TITLES", "from .recruitment import RecruitmentService")
replace(APP / "courier_recruitment.py", '        phone_text = {0: "старый", 1: "нормальный", 2: "хороший"}[phone_level]\n', "")
replace(
    APP / "courier_recruitment.py",
    '''        experience_text = {\n            0: "без подтверждённого опыта",\n            1: "есть опыт",\n            2: "опыт выглядит сильным",\n        }[experience_level]\n''',
    "",
)
replace(
    APP / "customer_trust.py",
    '''        relationship = self._relationship_conn(\n            conn, int(order["player_id"]), int(order["client_id"])\n        )\n''',
    '''        self._relationship_conn(\n            conn, int(order["player_id"]), int(order["client_id"])\n        )\n''',
)

remove_method(APP / "procurement_market.py", "ProcurementMarketSimulationEngine", "__init__")
remove_method(APP / "staff_insights.py", "StaffInsightSimulationEngine", "__init__")
remove_method(APP / "staff_insights.py", "StaffInsightGameService", "__init__")
remove_method(APP / "staff_relationships.py", "StaffRelationshipSimulationEngine", "__init__")
remove_method(APP / "staff_relationships.py", "StaffRelationshipGameService", "__init__")
remove_method(APP / "workflow.py", "WorkflowSimulationEngine", "__init__")
remove_method(APP / "workflow.py", "WorkflowGameService", "__init__")

replace(APP / "staff_insights.py", "from datetime import timedelta\n\n", "")
replace(APP / "staff_insights.py", "from .simulation import iso, parse_dt, utcnow", "from .simulation import parse_dt, utcnow")
replace(APP / "ui_staff.py", "import json\n\n", "")
replace(APP / "ui_staff_handlers.py", "    development_keyboard,\n", "")
replace(TESTS / "test_courier_management.py", "import pytest\n\n", "")
replace(
    APP / "main.py",
    '''    # One canonical presentation layer. Legacy UI routers are intentionally not\n    # registered, so every entity has one screen tree and one navigation contract.\n''',
    '''    # Every player-facing entity has one screen tree and one navigation contract.\n''',
)
