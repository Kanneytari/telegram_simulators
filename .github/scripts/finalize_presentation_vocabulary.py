from pathlib import Path

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'

# ui_common must only format text, never repair semantic UI labels.
path = APP / 'ui_common.py'
text = path.read_text(encoding='utf-8')
text = text.replace('        text.replace("🚚 Склад", "📦 Склад")\n        .replace("—", "-")', '        text.replace("—", "-")')
path.write_text(text, encoding='utf-8')

# Presentation package intentionally exposes vocabulary as an explicit module,
# rather than growing another wildcard compatibility surface.
(APP / 'presentation/__init__.py').write_text(
    '"""Shared presentation primitives for NIGHTSHIFT."""\n',
    encoding='utf-8',
)

# Canonical commerce section labels and buttons.
path = APP / 'ui_commerce.py'
text = path.read_text(encoding='utf-8')
text = text.replace(
    'from app.presentation.vocabulary import HOME, PRODUCT, SUPPLIERS, WAREHOUSE, button, nav_row',
    'from app.presentation.vocabulary import HOME, PACKAGING, PRODUCT, STOREFRONT, SUPPLIERS, WAREHOUSE, button, nav_row',
)
text = text.replace(
    'tutorial_hint("Нажми на кнопку 📦 Склад")',
    'tutorial_hint(f"Нажми на кнопку {WAREHOUSE.label}")',
)
text = text.replace(
    'InlineKeyboardButton(text="⚙️ Фасовки", callback_data="sales:packaging"),\n        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"),',
    'button(PACKAGING),\n        button(HOME),',
)
text = text.replace(
    '        "<b>🏷 Витрина</b>\\n\\n"',
    '        f"<b>{STOREFRONT.label}</b>\\n\\n"',
)
text = text.replace('rows.append(nav_row("menu:storefront", "Витрина"))', 'rows.append(nav_row(STOREFRONT))')
text = text.replace('    rows.append(nav_row("menu:storefront", "Витрина"))', '    rows.append(nav_row(STOREFRONT))')
text = text.replace(
    '        "<b>⚙️ Фасовки</b>\\n\\n"',
    '        f"<b>{PACKAGING.label}</b>\\n\\n"',
)
path.write_text(text, encoding='utf-8')

# Navigation headings use the same section vocabulary as their buttons.
path = APP / 'ui_navigation.py'
text = path.read_text(encoding='utf-8')
text = text.replace('body = f"<b>📨 Входящие · {total}</b>"', 'body = f"<b>{label(INBOX, total)}</b>"')
path.write_text(text, encoding='utf-8')

# Tutorial UI mentions global sections through vocabulary, not literal repairable strings.
path = APP / 'tutorial/hooks.py'
text = path.read_text(encoding='utf-8')
text = text.replace(
    'from app.presentation.vocabulary import PRODUCT, SUPPLIERS',
    'from app.presentation.vocabulary import PRODUCT, STOREFRONT, SUPPLIERS, WAREHOUSE, button',
)
text = text.replace(
    "tutorial_hint('Нажми [🤝 Поставщики]')",
    "tutorial_hint(f'Нажми [{SUPPLIERS.label}]')",
)
text = text.replace(
    'text = f"<b>🏷 Витрина</b>\\n\\nДоверие:',
    'text = f"<b>{STOREFRONT.label}</b>\\n\\nДоверие:',
)
text = text.replace(
    "rows.append([InlineKeyboardButton(text='Витрина', callback_data='menu:storefront')])",
    'rows.append([button(STOREFRONT)])',
)
text = text.replace(
    "tutorial_hint('Нажми [📦 Склад]')",
    "tutorial_hint(f'Нажми [{WAREHOUSE.label}]')",
)
path.write_text(text, encoding='utf-8')

# Tutorial stage copy owns onboarding copy, and uses vocabulary for button mentions.
path = APP / 'tutorial/copy.py'
text = path.read_text(encoding='utf-8')
text = text.replace(
    'from app.presentation.vocabulary import ANALYTICS, INBOX, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM',
    'from app.presentation.vocabulary import ANALYTICS, INBOX, PACKAGING, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM',
)
text = text.replace('            "[⚙️ Фасовки]\\n"', '            f"[{PACKAGING.label}]\\n"')
path.write_text(text, encoding='utf-8')

# The old test explicitly documented semantic repair of the wrong warehouse emoji.
# Replace it with a contract for canonical input: tutorial_hint formats but does not rename UI items.
path = TESTS / 'test_zz_gameplay_updates.py'
text = path.read_text(encoding='utf-8')
text = text.replace(
    '    assert tutorial_hint("Нажми на кнопку 🚚 Склад") == (\n'
    '        "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>"\n'
    '    )',
    '    assert tutorial_hint("Нажми на кнопку 📦 Склад") == (\n'
    '        "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>"\n'
    '    )',
)
path.write_text(text, encoding='utf-8')

# Expand the permanent vocabulary guardrail from Product-only to every global section/action.
path = TESTS / 'test_ui_vocabulary.py'
text = path.read_text(encoding='utf-8')
old = '''def test_plain_product_button_cannot_return() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        if path.name == "vocabulary.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
            if isinstance(text_kw, ast.Constant) and text_kw.value == "Товар":
                offenders.append(f"{path.relative_to(APP)}:{getattr(node, 'lineno', '?')}")
    assert not offenders, f"plain Product button labels found: {offenders}"
'''
new = '''def test_global_buttons_cannot_reinvent_canonical_labels() -> None:
    bare_labels = {
        "Меню", "Товар", "Поставщики", "Склад", "Витрина", "Команда",
        "Аналитика", "Входящие", "Нанять", "Оплата", "Обновить", "Фасовки",
    }
    canonical_callbacks = {
        "menu:product": PRODUCT.label,
        "proc:suppliers": SUPPLIERS.label,
        "team:batches": WAREHOUSE.label,
        "menu:storefront": STOREFRONT.label,
        "menu:team": TEAM.label,
        "menu:analytics": ANALYTICS.label,
        "menu:inbox": INBOX.label,
        "menu:home": {HOME.label, "🔄 Обновить"},
    }
    offenders: list[str] = []
    for source_path in APP.rglob("*.py"):
        if source_path.name == "vocabulary.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
            callback_kw = next((kw.value for kw in node.keywords if kw.arg == "callback_data"), None)
            line = f"{source_path.relative_to(APP)}:{getattr(node, 'lineno', '?')}"
            if isinstance(text_kw, ast.Constant) and text_kw.value in bare_labels:
                offenders.append(f"{line} bare={text_kw.value!r}")
            if isinstance(callback_kw, ast.Constant) and callback_kw.value in canonical_callbacks and isinstance(text_kw, ast.Constant):
                allowed = canonical_callbacks[callback_kw.value]
                allowed_set = allowed if isinstance(allowed, set) else {allowed}
                if text_kw.value not in allowed_set:
                    offenders.append(f"{line} callback={callback_kw.value!r} text={text_kw.value!r}")
    assert not offenders, "global UI labels bypass vocabulary: " + "; ".join(offenders)


def test_ui_common_does_not_repair_semantic_labels() -> None:
    source = (APP / "ui_common.py").read_text(encoding="utf-8")
    assert "🚚 Склад" not in source
    assert "📦 Склад" not in source
'''
if old not in text:
    raise SystemExit('vocabulary guardrail anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

print('presentation vocabulary final cleanup applied')
