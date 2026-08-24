from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def update(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path}: missing {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


update(APP / "ui_commerce.py", 'text=f"Склад · {batch_count} партий"', 'text=f"Склад · {batch_count}"')
update(APP / "ui_staff.py", 'body = f"<b>📦 Склад · {len(rows)} партий</b>"', 'body = f"<b>📦 Склад · {len(rows)}</b>"')
update(TESTS / "test_ui_scenarios.py", 'assert "Партии" in target.text', 'assert "Склад" in target.text')

print("last UX alignment ok")
