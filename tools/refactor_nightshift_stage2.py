from __future__ import annotations

import ast
import random
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "shadow_market_simulator"
APP = PROJECT / "app"


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def flatten_catalog() -> None:
    simulation = APP / "simulation.py"
    text = simulation.read_text(encoding="utf-8")
    old = '''PRODUCTS = (\n    (1, "NEON", "Neon", 1450, 18.0, 0.9),\n    (2, "AMBER", "Amber", 2050, 10.0, 1.1),\n    (3, "ECHO", "Echo", 3100, 6.0, 1.3),\n)'''
    new = '''PRODUCTS = (\n    (1, "NEON", "Neon", 1450, 18.0, 0.9),\n    (2, "AMBER", "Amber", 2050, 10.0, 1.1),\n    (3, "ECHO", "Echo", 3100, 6.0, 1.3),\n    (4, "MEPHEDRONE", "Мефедрон", 7000, 15.0, 1.00),\n    (5, "KETAMINE", "Кетамин", 7500, 9.0, 1.15),\n    (6, "LSD", "LSD", 9000, 7.0, 0.85),\n)'''
    if old not in text:
        raise RuntimeError("base PRODUCTS block changed")
    write(simulation, text.replace(old, new, 1))

    customer_trust = APP / "customer_trust.py"
    text = customer_trust.read_text(encoding="utf-8")
    text = text.replace("from .catalog_extension import ExpandedCatalogSimulationEngine\n", "")
    text = text.replace(
        "from .staff_relationships import SALES_ACTIVITY_MULTIPLIER",
        "from .staff_relationships import SALES_ACTIVITY_MULTIPLIER, StaffRelationshipSimulationEngine",
    )
    text = text.replace(
        "class CustomerTrustSimulationEngine(ExpandedCatalogSimulationEngine):",
        "class CustomerTrustSimulationEngine(StaffRelationshipSimulationEngine):",
    )
    write(customer_trust, text)
    (APP / "catalog_extension.py").unlink(missing_ok=True)


def materialize_current_schema() -> str:
    sys.path.insert(0, str(PROJECT))
    from app.analytics_log import AnalyticsLogger
    from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
    from app.courier_recruitment import CourierRecruitmentService
    from app.db import Database
    from app.inbox_lifecycle import install_inbox_lifecycle

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fresh.db"
        db = Database(str(path))
        db.init()
        simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(901))
        simulation.seed_catalog()
        simulation.ensure_player(1, "schema")
        CourierManagementGameService(db, simulation, rng=random.Random(902))
        CourierRecruitmentService(db, speed=1.0, rng=random.Random(903))
        install_inbox_lifecycle(db)
        analytics = AnalyticsLogger(db)
        analytics.install()

        with db.connect() as conn:
            rows = conn.execute(
                """SELECT type, name, sql
                   FROM sqlite_master
                   WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
                   ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,
                            name"""
            ).fetchall()

    statements = ["PRAGMA journal_mode = WAL;", "PRAGMA foreign_keys = ON;"]
    for row in rows:
        sql = str(row["sql"]).strip().rstrip(";")
        statements.append(sql + ";")
    return "\n\n".join(statements) + "\n"


def schema_constant_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        else:
            continue
        if not (name == "SCHEMA" or name.endswith("_SCHEMA")):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and "CREATE " in value.value:
            names.add(name)
    return names


def remove_spans(text: str, spans: list[tuple[int, int]], replacement: str = "") -> str:
    lines = text.splitlines(keepends=True)
    for start, end in sorted(spans, reverse=True):
        indent = re.match(r"\s*", lines[start - 1]).group(0) if replacement else ""
        lines[start - 1 : end] = [indent + replacement + "\n"] if replacement else []
    return "".join(lines)


def strip_schema_constants_and_executescripts() -> None:
    files = [path for path in APP.glob("*.py") if path.name != "db.py"]
    all_names: set[str] = set()
    local_names: dict[Path, set[str]] = {}
    for path in files:
        names = schema_constant_names(path)
        local_names[path] = names
        all_names.update(names)

    for path in files:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        spans: list[tuple[int, int]] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in local_names[path]:
                    spans.append((node.lineno, node.end_lineno))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in local_names[path]:
                    spans.append((node.lineno, node.end_lineno))
        text = remove_spans(text, spans)
        write(path, text)

    for path in files:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)
        replacements: list[tuple[int, int, str]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                removed = [alias for alias in node.names if alias.name in all_names]
                if not removed:
                    continue
                kept = [alias for alias in node.names if alias.name not in all_names]
                if kept:
                    dots = "." * node.level
                    names = ", ".join(
                        f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                        for alias in kept
                    )
                    replacement = f"from {dots}{node.module or ''} import {names}"
                else:
                    replacement = ""
                replacements.append((node.lineno, node.end_lineno, replacement))

            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "executescript" or not call.args:
                continue
            arg = call.args[0]
            if isinstance(arg, ast.Name) and arg.id in all_names:
                replacements.append((node.lineno, node.end_lineno, "pass"))

        for start, end, replacement in sorted(replacements, reverse=True):
            indent = re.match(r"\s*", lines[start - 1]).group(0)
            lines[start - 1 : end] = [indent + replacement + "\n"] if replacement else []
        write(path, "".join(lines))


def rewrite_database_module() -> None:
    write(
        APP / "db.py",
        '''from __future__ import annotations\n\nimport sqlite3\nfrom pathlib import Path\n\n\nSCHEMA_PATH = Path(__file__).with_name("schema.sql")\n\n\nclass ClosingConnection(sqlite3.Connection):\n    def __exit__(self, exc_type, exc, tb):\n        try:\n            return super().__exit__(exc_type, exc, tb)\n        finally:\n            self.close()\n\n\nclass Database:\n    def __init__(self, path: str):\n        self.path = path\n        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)\n\n    def connect(self) -> sqlite3.Connection:\n        conn = sqlite3.connect(self.path, factory=ClosingConnection)\n        conn.row_factory = sqlite3.Row\n        conn.execute("PRAGMA foreign_keys = ON")\n        return conn\n\n    def init(self) -> None:\n        schema = SCHEMA_PATH.read_text(encoding="utf-8")\n        with self.connect() as conn:\n            conn.executescript(schema)\n''',
    )


def report_remaining_schema_magic() -> None:
    hits: list[str] = []
    for path in APP.glob("*.py"):
        if path.name == "db.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("ALTER TABLE", "executescript("):
            if token in text:
                hits.append(f"{path.name}: {token}")
    if hits:
        print("Remaining runtime schema operations:")
        for hit in hits:
            print(" -", hit)


def main() -> None:
    flatten_catalog()
    schema = materialize_current_schema()
    write(APP / "schema.sql", schema)
    strip_schema_constants_and_executescripts()
    rewrite_database_module()
    report_remaining_schema_magic()


if __name__ == "__main__":
    main()
