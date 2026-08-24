from __future__ import annotations

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

    tokens = [
        "pay_per_job", "deposit_contribution_pct", "desired_pay", "offered_pay",
        "raise_request", "leave_request", "advance_request", "employee_theft",
        "shops SET rating", "shops.rating", "clients SET loyalty", "clients.loyalty",
        "legacy", "backward", "ALTER TABLE", "executescript(",
    ]
    print("\n=== LEGACY REFERENCES ===")
    for token in tokens:
        print(f"\n-- {token} --")
        pattern = re.compile(re.escape(token), re.I)
        found = False
        for path in sorted(APP.glob("*.py")):
            hits = [
                (i, line.strip())
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if pattern.search(line)
            ]
            if hits:
                found = True
                print(path.name)
                for line_no, line in hits:
                    print(f"  {line_no}: {line[:220]}")
        if not found:
            print("  none")

    print("\n=== VERSION-LIKE MODULES / CLASSES ===")
    for path in sorted(APP.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(word in path.stem for word in ("final", "runtime", "extension")) or re.search(r"class\s+(Final|Nightshift|Player)", text):
            print(path.name)
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"class\s+(Final|Nightshift|Player)", line):
                    print(f"  {i}: {line.strip()}")

    print("\n=== LARGE MODULES ===")
    for path in sorted(APP.glob("*.py"), key=lambda p: p.stat().st_size, reverse=True):
        if path.stat().st_size >= 15000:
            print(f"{path.name}: {path.stat().st_size}")


if __name__ == "__main__":
    main()
