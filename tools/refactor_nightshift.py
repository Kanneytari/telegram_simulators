from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"

DELETED_UI_MODULES = {
    "app.action_handlers",
    "app.compensation_handlers",
    "app.courier_idle_handlers",
    "app.courier_management_handlers",
    "app.customer_trust_handlers",
    "app.dispute_handlers",
    "app.employee_profile_handlers",
    "app.extended_handlers",
    "app.global_packaging_handlers",
    "app.handlers",
    "app.inbox_close_handlers",
    "app.keyboards",
    "app.procurement_handlers",
    "app.recruitment_handlers",
    "app.storefront_handlers",
    "app.team_keyboard",
    "app.time_handlers",
    "app.workflow_allocation_handlers",
    "app.workflow_dashboard_handlers",
    "app.workflow_handlers",
    "app.workflow_reassign_handlers",
}


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_class_method(path: Path, class_name: str, method_name: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    lines = text.splitlines(keepends=True)
                    lines[child.lineno - 1 : child.end_lineno] = [replacement.rstrip() + "\n"]
                    write(path, "".join(lines))
                    return
    raise RuntimeError(f"{path}: {class_name}.{method_name} not found")


def remove_legacy_ui_tests() -> None:
    for path in TESTS.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported: set[str] = set()
        import_spans: list[tuple[int, int]] = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module in DELETED_UI_MODULES:
                imported.update(alias.asname or alias.name for alias in node.names)
                import_spans.append((node.lineno, node.end_lineno))
        if not imported:
            continue

        spans = list(import_spans)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            segment = ast.get_source_segment(text, node) or ""
            if any(re.search(rf"\b{re.escape(name)}\b", segment) for name in imported):
                spans.append((node.lineno, node.end_lineno))

        lines = text.splitlines(keepends=True)
        for start, end in sorted(spans, reverse=True):
            del lines[start - 1 : end]
        cleaned = "".join(lines)
        cleaned_tree = ast.parse(cleaned)
        has_tests = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
            or isinstance(node, ast.ClassDef) and node.name.startswith("Test")
            for node in cleaned_tree.body
        )
        if has_tests:
            write(path, cleaned)
        else:
            path.unlink()


def simplify_operations_layer() -> None:
    workflow = APP / "workflow.py"
    text = workflow.read_text(encoding="utf-8")
    text = text.replace(
        "from .operations_final import FinalOperationsGameService, FinalOperationsSimulationEngine",
        "from .operations import OperationsGameService, OperationsSimulationEngine",
    )
    text = text.replace(
        "class WorkflowSimulationEngine(FinalOperationsSimulationEngine):",
        "class WorkflowSimulationEngine(OperationsSimulationEngine):",
    )
    text = text.replace(
        "class WorkflowGameService(FinalOperationsGameService):",
        "class WorkflowGameService(OperationsGameService):",
    )
    write(workflow, text)
    (APP / "operations_final.py").unlink(missing_ok=True)


def simplify_packaging() -> None:
    workflow = APP / "workflow.py"
    text = workflow.read_text(encoding="utf-8")
    text, count = re.subn(
        r"CREATE TABLE IF NOT EXISTS packaging_rules \(.*?\n\);",
        """CREATE TABLE IF NOT EXISTS shop_packaging_rules (\n    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,\n    pct_1 INTEGER NOT NULL DEFAULT 60,\n    pct_2 INTEGER NOT NULL DEFAULT 30,\n    pct_5 INTEGER NOT NULL DEFAULT 10,\n    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);""",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("packaging_rules schema block not found")
    write(workflow, text)

    replace_class_method(
        workflow,
        "WorkflowSimulationEngine",
        "_ensure_packaging_rules",
        '''    def _ensure_packaging_rules(self, player_id: int) -> None:\n        with self.db.connect() as conn:\n            conn.execute(\n                "INSERT OR IGNORE INTO shop_packaging_rules(player_id) VALUES (?)",\n                (player_id,),\n            )''',
    )

    replace_class_method(
        workflow,
        "WorkflowSimulationEngine",
        "_publish_allocation",
        '''    def _publish_allocation(self, conn, player_id: int, allocation_id: int) -> None:\n        allocation = conn.execute(\n            "SELECT * FROM retail_allocations WHERE id=? AND player_id=?",\n            (allocation_id, player_id),\n        ).fetchone()\n        if not allocation or allocation["quantity"] <= 0:\n            return\n\n        conn.execute(\n            "INSERT OR IGNORE INTO shop_packaging_rules(player_id) VALUES (?)",\n            (player_id,),\n        )\n        rule = conn.execute(\n            "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",\n            (player_id,),\n        ).fetchone()\n\n        qty = int(allocation["quantity"])\n        units5 = int(qty * int(rule["pct_5"]) / 100)\n        count5 = units5 // 5\n        remaining = qty - count5 * 5\n        units2 = min(remaining, int(qty * int(rule["pct_2"]) / 100))\n        count2 = units2 // 2\n        remaining -= count2 * 2\n        count1 = remaining\n        for pack_size, count in ((1, count1), (2, count2), (5, count5)):\n            if count <= 0:\n                continue\n            conn.execute(\n                """INSERT INTO retail_positions(\n                       player_id, allocation_id, batch_id, employee_id, product_id,\n                       pack_size, position_count, unit_cost, quality\n                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n                   ON CONFLICT(allocation_id, pack_size)\n                   DO UPDATE SET position_count=excluded.position_count""",\n                (\n                    player_id,\n                    allocation_id,\n                    allocation["batch_id"],\n                    allocation["retail_employee_id"],\n                    allocation["product_id"],\n                    pack_size,\n                    count,\n                    allocation["unit_cost"],\n                    allocation["quality"],\n                ),\n            )\n        conn.execute(\n            "UPDATE retail_allocations SET status='published', completed_at=CURRENT_TIMESTAMP WHERE id=?",\n            (allocation_id,),\n        )''',
    )

    global_packaging = APP / "global_packaging.py"
    write(
        global_packaging,
        '''from __future__ import annotations\n\nfrom .staff_idle import IdleAwareGameService\n\n\nclass GlobalPackagingGameService(IdleAwareGameService):\n    def global_packaging_rule(self, player_id: int) -> dict[str, int]:\n        self.simulation._ensure_packaging_rules(player_id)\n        with self.db.connect() as conn:\n            row = conn.execute(\n                "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",\n                (player_id,),\n            ).fetchone()\n        return {\n            "pct_1": int(row["pct_1"]),\n            "pct_2": int(row["pct_2"]),\n            "pct_5": int(row["pct_5"]),\n        }\n\n    def adjust_global_packaging_rule(self, player_id: int, pack_size: int, delta: int) -> str:\n        if pack_size not in {1, 2, 5} or delta not in {-10, 10}:\n            raise ValueError("Unsupported packaging adjustment")\n\n        self.simulation._ensure_packaging_rules(player_id)\n        with self.db.connect() as conn:\n            row = conn.execute(\n                "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",\n                (player_id,),\n            ).fetchone()\n            values = {1: int(row["pct_1"]), 2: int(row["pct_2"]), 5: int(row["pct_5"])}\n\n            if delta > 0:\n                needed = min(delta, 100 - values[pack_size])\n                for other in sorted(\n                    (value for value in values if value != pack_size),\n                    key=lambda value: values[value],\n                    reverse=True,\n                ):\n                    take = min(needed, values[other])\n                    values[other] -= take\n                    values[pack_size] += take\n                    needed -= take\n                    if needed <= 0:\n                        break\n            else:\n                amount = min(-delta, values[pack_size])\n                values[pack_size] -= amount\n                other = max(\n                    (value for value in values if value != pack_size),\n                    key=lambda value: values[value],\n                )\n                values[other] += amount\n\n            conn.execute(\n                """UPDATE shop_packaging_rules\n                   SET pct_1=?, pct_2=?, pct_5=?, updated_at=CURRENT_TIMESTAMP\n                   WHERE player_id=?""",\n                (values[1], values[2], values[5], player_id),\n            )\n\n        return f"×1 {values[1]}% · ×2 {values[2]}% · ×5 {values[5]}%"\n\n    def change_employee_role(self, player_id: int, employee_id: int) -> str:\n        result = super().change_employee_role(player_id, employee_id)\n        self.simulation._ensure_packaging_rules(player_id)\n        return result\n''',
    )

    customer_trust = APP / "customer_trust.py"
    text = customer_trust.read_text(encoding="utf-8")
    text = text.replace(
        "from .global_packaging import GlobalPackagingGameService, GlobalPackagingSimulationEngine",
        "from .catalog_extension import ExpandedCatalogSimulationEngine\nfrom .global_packaging import GlobalPackagingGameService",
    )
    text = text.replace(
        "class CustomerTrustSimulationEngine(GlobalPackagingSimulationEngine):",
        "class CustomerTrustSimulationEngine(ExpandedCatalogSimulationEngine):",
    )
    write(customer_trust, text)

    workflow_final = APP / "workflow_final.py"
    text = workflow_final.read_text(encoding="utf-8")
    text, _ = re.subn(
        r"\n            if new_role == \"courier\":\n                products = conn\.execute\(\"SELECT id FROM products WHERE active=1\"\)\.fetchall\(\)\n                for product in products:\n                    conn\.execute\(\n                        \"INSERT OR IGNORE INTO packaging_rules\(player_id, employee_id, product_id\) VALUES \(\?, \?, \?\)\",\n                        \(player_id, employee_id, product\[\"id\"\]\),\n                    \)",
        "",
        text,
        count=1,
    )
    write(workflow_final, text)


def assert_no_deleted_ui_imports() -> None:
    failures: list[str] = []
    for path in APP.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = f"app.{node.module.lstrip('.')}" if node.level else node.module
                if module in DELETED_UI_MODULES:
                    failures.append(f"{path.name}: {module}")
    if failures:
        raise RuntimeError("legacy UI imports remain: " + ", ".join(failures))


def main() -> None:
    remove_legacy_ui_tests()
    simplify_operations_layer()
    simplify_packaging()
    assert_no_deleted_ui_imports()


if __name__ == "__main__":
    main()
