from pathlib import Path

path = Path('.github/scripts/refactor_nightshift_ui_vocabulary.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    "copy_path.write_text(\n    '''from __future__ import annotations",
    "copy_path.write_text(\n    r'''from __future__ import annotations",
    1,
)
text = text.replace(
    "(TESTS / \"test_ui_vocabulary.py\").write_text(\n    '''from __future__ import annotations",
    "(TESTS / \"test_ui_vocabulary.py\").write_text(\n    r'''from __future__ import annotations",
    1,
)
path.write_text(text, encoding='utf-8')

Path('shadow_market_simulator/tests/test_refresh_button_emoji.py').write_text(
    '''from app.presentation.vocabulary import REFRESH, button\n\n\ndef test_refresh_button_uses_canonical_refresh_label():\n    refresh = button(REFRESH, callback_data="anything:refresh")\n    assert refresh.text == "🔄 Обновить"\n    assert refresh.callback_data == "anything:refresh"\n\n\ndef test_refresh_label_has_single_emoji_source():\n    assert REFRESH.label == "🔄 Обновить"\n    assert REFRESH.label.count("🔄") == 1\n''',
    encoding='utf-8',
)

patches = {
    'shadow_market_simulator/tests/test_analytics_navigation.py': [
        ('assert "Меню" in names', 'assert "🏠 Меню" in names'),
    ],
    'shadow_market_simulator/tests/test_compact_ui.py': [
        ('"Обновить",\n        "🏠 Меню",', '"🔄 Обновить",\n        "🏠 Меню",'),
        ('["Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
        ('["← Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
    ],
    'shadow_market_simulator/tests/test_product_suppliers_tutorial.py': [
        ('["Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
        ('["← Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
    ],
    'shadow_market_simulator/tests/test_zz_gameplay_updates.py': [
        ('== "← Товар"', '== "📦 Товар"'),
        ('== "Товар"', '== "📦 Товар"'),
    ],
    'shadow_market_simulator/tests/test_zzzz_product_ui_final.py': [
        ('== "← Товар"', '== "📦 Товар"'),
        ('== "Товар"', '== "📦 Товар"'),
        ('["Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
        ('["← Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]'),
    ],
    'shadow_market_simulator/tests/test_tutorial_copy_update.py': [
        ('tutorial._instruction(', 'tutorial.instruction('),
    ],
    'shadow_market_simulator/tests/test_tutorial_nonblocking.py': [
        ('tutorial._instruction(', 'tutorial.instruction('),
    ],
}

for raw_path, replacements in patches.items():
    test_path = Path(raw_path)
    value = test_path.read_text(encoding='utf-8')
    for old, new in replacements:
        value = value.replace(old, new)
    test_path.write_text(value, encoding='utf-8')
