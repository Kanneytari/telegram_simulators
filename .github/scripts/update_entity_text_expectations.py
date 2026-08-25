from pathlib import Path

ROOT = Path('shadow_market_simulator/tests')


def patch(name: str, replacements: list[tuple[str, str]]) -> None:
    path = ROOT / name
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')


patch('test_tutorial_copy_update.py', [
    (
        '"После продаж появляются оценки товара и закладчика.\\n\\n"',
        '"После продаж появляются оценки товара и 👤 <b>закладчика</b>.\\n\\n"',
    ),
])

patch('test_tutorial_flow.py', [
    (
        'assert "Складмен забирает первую партию" in onboarding["body"], repr(onboarding["body"])',
        'assert "🚚 <b>Складмен</b> забирает первую партию" in onboarding["body"], repr(onboarding["body"])',
    ),
])

patch('test_zz_gameplay_updates.py', [
    (
        'assert "Выберите кладмена" in target.text',
        'assert "Выберите 👤 <b>кладмена</b>" in target.text',
    ),
])

print('entity text expectations updated')
