from pathlib import Path

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')

# Make dynamic button markers explicit at construction sites, so the guardrail
# proves the rendered button itself rather than relying on flow inference.
patch(APP / 'ui_commerce.py', [
    ('text = f"📦 {product[\'title\']}"', 'text = str(product["title"])'),
    ('                text=text,\n                callback_data=f"proc:product:', '                text=f"📦 {text}",\n                callback_data=f"proc:product:'),
])
patch(APP / 'ui_navigation.py', [
    ('                text=f"{marker}{str(item[\'title\'])[:48]}",', '                text=f"📨 {marker}{str(item[\'title\'])[:48]}",'),
])

# ⚖️ is a deliberate action/entity marker used by disputes.
path = TESTS / 'test_ui_vocabulary.py'
text = path.read_text(encoding='utf-8')
if '"⚖️"' not in text:
    text = text.replace('"🏠", "📦",', '"🏠", "📦", "⚖️",', 1)
path.write_text(text, encoding='utf-8')

# Migrate pre-refactor UI expectations to the explicit emoji contracts.
patch(TESTS / 'test_analytics_navigation.py', [
    ('assert "✓ Обзор" in names', 'assert "✅ 📊 Обзор" in names'),
    ('assert "Товары" in names', 'assert "⚪ 📦 Товары" in names'),
    ('assert "Деньги" in names', 'assert "⚪ 💰 Деньги" in names'),
])
patch(TESTS / 'test_compact_ui.py', [
    ('            "Обычное событие",', '            "📨 ⚪ Обычное событие",'),
    ('            "🔴 Срочное событие",', '            "📨 🔴 Срочное событие",'),
    ('assert more[:3] == ["Переименовать", "Сменить роль", "Уволить"]', 'assert more[:3] == ["✏️ Переименовать", "🔄 Сменить роль", "🗑️ Уволить"]'),
    ('assert labels(markup) == ["Амфетамин", "Кокаин", "📦 Товар", "🏠 Меню"]', 'assert labels(markup) == ["📦 Амфетамин", "📦 Кокаин", "📦 Товар", "🏠 Меню"]'),
    ('        "✓ Обзор",\n        "Товары",\n        "Деньги",\n        "✓ 7 дней",\n        "30 дней",', '        "✅ 📊 Обзор",\n        "⚪ 📦 Товары",\n        "⚪ 💰 Деньги",\n        "✅ 7 дней",\n        "⚪ 30 дней",'),
])
patch(TESTS / 'test_ux_clarity.py', [
    ('<blockquote>Выбери закладчика, которому передашь стафф.</blockquote>', '<blockquote>Выбери 👤 <b>закладчика</b>, которому передашь стафф.</blockquote>'),
])

# Product buttons now intentionally identify the product entity with 📦.
for filename in ('test_zz_gameplay_updates.py', 'test_zzzz_product_ui_final.py'):
    path = TESTS / filename
    text = path.read_text(encoding='utf-8')
    text = text.replace('assert label == product["title"]', 'assert label == f"📦 {product[\'title\']}"')
    text = text.replace('assert label == f"{product[\'title\']} · 🚚 {stock_status}"', 'assert label == f"📦 {product[\'title\']} · 🚚 {stock_status}"')
    path.write_text(text, encoding='utf-8')

print('final entity presentation contracts applied')
