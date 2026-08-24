from pathlib import Path

path = Path(__file__).resolve().parents[1] / "shadow_market_simulator" / "tests" / "test_compact_ui.py"
text = path.read_text(encoding="utf-8")
old = '''    assert labels(inbox_keyboard(items)) == [\n        "🔴 Срочное событие",\n        "Обычное событие",\n        "🔄 Обновить",\n        "Меню",\n    ]'''
new = '''    assert labels(inbox_keyboard(items)) == [\n        "🔴 Срочное событие",\n        "Обычное событие",\n        "Обновить",\n        "Меню",\n    ]'''
if old not in text:
    raise RuntimeError("inbox expectation not found")
path.write_text(text.replace(old, new), encoding="utf-8")
