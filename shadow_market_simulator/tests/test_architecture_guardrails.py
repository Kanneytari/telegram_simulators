from __future__ import annotations

import ast
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"

# Transitional allow-list. Files may disappear from this set during the refactor,
# but new flat modules must not be added: new functionality belongs in packages.
ALLOWED_FLAT_MODULES = {
    "__init__.py",
    "analytics_handlers.py",
    "analytics_log.py",
    "bootstrap.py",
    "business_analytics.py",
    "compensation.py",
    "config.py",
    "courier_core.py",
    "courier_idle.py",
    "courier_management.py",
    "courier_model.py",
    "courier_recruitment.py",
    "customer_trust.py",
    "db.py",
    "dispute_payments.py",
    "employee_rename.py",
    "game.py",
    "gameplay_updates.py",
    "global_packaging.py",
    "inbox_lifecycle.py",
    "main.py",
    "nightshift.py",
    "operations.py",
    "procurement_market.py",
    "recruitment.py",
    "runtime.py",
    "simulation.py",
    "staff_idle.py",
    "staff_insights.py",
    "staff_relationships.py",
    "tutorial.py",
    "tutorial_copy_update.py",
    "tutorial_runtime.py",
    "ui_admin.py",
    "ui_commerce.py",
    "ui_common.py",
    "ui_disputes.py",
    "ui_navigation.py",
    "ui_staff.py",
    "ui_staff_handlers.py",
    "workflow.py",
}

# Existing runtime overlays are migration debt, not an extension mechanism.
# This exact set can only shrink.
LEGACY_OVERLAY_MODULES = {
    "gameplay_updates.py",
    "tutorial.py",
    "tutorial_copy_update.py",
    "tutorial_runtime.py",
}

# The existing inheritance staircase is frozen. The migration may relocate or
# remove entries, but a new feature must not extend it with another layer.
LEGACY_ENGINE_INHERITANCE = {
    ("runtime.py", "PlayerSimulationEngine"),
    ("nightshift.py", "NightshiftSimulationEngine"),
    ("operations.py", "OperationsSimulationEngine"),
    ("workflow.py", "WorkflowSimulationEngine"),
    ("staff_insights.py", "StaffInsightSimulationEngine"),
    ("procurement_market.py", "ProcurementMarketSimulationEngine"),
    ("compensation.py", "CompensationSimulationEngine"),
    ("staff_relationships.py", "StaffRelationshipSimulationEngine"),
    ("customer_trust.py", "CustomerTrustSimulationEngine"),
    ("courier_core.py", "CourierCoreSimulationEngine"),
    ("courier_management.py", "CourierManagementSimulationEngine"),
}

LEGACY_SERVICE_INHERITANCE = {
    ("dispute_payments.py", "DisputePaymentGameService"),
    ("operations.py", "OperationsGameService"),
    ("workflow.py", "WorkflowGameService"),
    ("staff_insights.py", "StaffInsightGameService"),
    ("procurement_market.py", "ProcurementMarketGameService"),
    ("compensation.py", "CompensationGameService"),
    ("staff_relationships.py", "StaffRelationshipGameService"),
    ("commerce/packaging.py", "GlobalPackagingGameService"),
    ("customer_trust.py", "CustomerTrustGameService"),
    ("courier_core.py", "CourierCoreGameService"),
    ("courier_management.py", "CourierManagementGameService"),
}


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_new_code_goes_into_packages_not_flat_app_modules() -> None:
    actual = {path.name for path in APP.glob("*.py")}
    unexpected = sorted(actual - ALLOWED_FLAT_MODULES)
    assert not unexpected, f"new flat app modules are not allowed: {unexpected}"


def test_runtime_overlay_debt_can_only_shrink() -> None:
    candidates = {
        path.name
        for path in APP.rglob("*.py")
        if path.name.endswith("_update.py")
        or path.name.endswith("_updates.py")
        or path.name.endswith("_fixes.py")
        or path.name == "tutorial.py"
    }
    unexpected = sorted(candidates - LEGACY_OVERLAY_MODULES)
    assert not unexpected, f"new runtime overlay modules are not allowed: {unexpected}"


def test_engine_and_game_service_inheritance_staircases_are_frozen() -> None:
    unexpected: list[str] = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {_base_name(base) for base in node.bases}
            key = (relative, node.name)
            if node.name.endswith("SimulationEngine") and any(
                base.endswith("SimulationEngine") for base in bases
            ):
                if key not in LEGACY_ENGINE_INHERITANCE:
                    unexpected.append(f"{relative}:{node.name}")
            if node.name.endswith("GameService") and any(
                base.endswith("GameService") for base in bases
            ):
                if key not in LEGACY_SERVICE_INHERITANCE:
                    unexpected.append(f"{relative}:{node.name}")
    assert not unexpected, (
        "do not extend the legacy inheritance staircase; use feature composition: "
        f"{sorted(unexpected)}"
    )


def test_new_packages_do_not_monkey_patch_imported_modules() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if path.name in LEGACY_OVERLAY_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module is None:
                imported_modules.update(alias.asname or alias.name for alias in node.names)

        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                root = target
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in imported_modules:
                    offenders.append(f"{relative}:{getattr(node, 'lineno', '?')}")

    assert not offenders, (
        "assigning into imported modules is runtime monkey-patching; "
        f"offenders: {sorted(offenders)}"
    )
