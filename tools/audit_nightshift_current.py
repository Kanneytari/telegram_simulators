from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "shadow_market_simulator"
APP = PROJECT / "app"


def main() -> None:
    import sys
    sys.path.insert(0, str(PROJECT))
    from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
    from app.courier_recruitment import CourierRecruitmentService

    for cls in (CourierManagementSimulationEngine, CourierManagementGameService, CourierRecruitmentService):
        print(f"\n=== MRO {cls.__name__} ===")
        for base in cls.__mro__:
            if base is object:
                continue
            source = inspect.getsourcefile(base)
            print(f"{base.__module__}.{base.__name__} :: {Path(source).name if source else '?'}")

    fields = [
        "pay_per_job", "deposit_contribution_pct", "desired_pay", "offered_pay",
        "reliability", "attention", "honesty", "has_car", "shops.rating",
        "rating", "clients.loyalty", "loyalty", "raise_request", "leave_request",
        "advance_request", "employee_theft", "packaging_rules", "backward", "legacy",
        "ALTER TABLE", "executescript(",
    ]
    print("\n=== FIELD / LEGACY REFERENCES ===")
    for field in fields:
        print(f"\n-- {field} --")
        pattern = re.compile(re.escape(field))
        for path in sorted(APP.glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            hits = [(i, line.strip()) for i, line in enumerate(lines, 1) if pattern.search(line)]
            if hits:
                print(path.name, len(hits))
                for i, line in hits[:12]:
                    print(f"  {i}: {line[:180]}")
                if len(hits) > 12:
                    print("  ...")

    print("\n=== CLASS METHOD SHADOWING ===")
    cls = CourierManagementSimulationEngine
    seen: dict[str, list[str]] = {}
    for base in cls.__mro__:
        if base is object:
            continue
        for name, value in base.__dict__.items():
            if callable(value) and not name.startswith("__"):
                seen.setdefault(name, []).append(base.__name__)
    for name, owners in sorted(seen.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(owners) > 1:
            print(f"{name}: {' -> '.join(owners)}")

    print("\n=== MODULE SIZES ===")
    for path in sorted(APP.glob("*.py"), key=lambda p: p.stat().st_size, reverse=True):
        print(f"{path.name}: {path.stat().st_size}")

    print("\n=== IMPORT GRAPH EDGES (local) ===")
    for path in sorted(APP.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        deps = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                deps.append(node.module.split(".")[0])
        if deps:
            print(f"{path.stem}: {', '.join(sorted(set(deps)))}")


if __name__ == "__main__":
    main()
