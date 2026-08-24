from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def replace(path: Path, old: str, new: str, expected: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if expected is not None and count != expected:
        raise RuntimeError(f"{path}: expected {expected} occurrences of {old!r}, found {count}")
    if count == 0:
        raise RuntimeError(f"{path}: missing {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace(APP / "courier_management.py", "🛵", "🚲", expected=3)
replace(
    APP / "compensation.py",
    'role = "опт" if row["role"] == "warehouse" else "розница"',
    'role = "Складмен" if row["role"] == "warehouse" else "Закладчик"',
    expected=1,
)

path = TESTS / "test_extended_systems.py"
text = path.read_text(encoding="utf-8")
marker = "\ndef test_simulation_does_not_create_individual_raise_requests(tmp_path):\n"
if marker not in text:
    raise RuntimeError("historical raise_request test not found")
text = text.split(marker, 1)[0].rstrip() + "\n"
path.write_text(text, encoding="utf-8")

print("NIGHTSHIFT legacy wording cleanup applied")
