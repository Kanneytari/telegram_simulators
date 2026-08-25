from __future__ import annotations

import ast
from pathlib import Path

from app.presentation.vocabulary import (
    ANALYTICS,
    HOME,
    INBOX,
    PRODUCT,
    STOREFRONT,
    SUPPLIERS,
    TEAM,
    WAREHOUSE,
    button,
)
from app import ui_commerce


APP = Path(__file__).resolve().parents[1] / "app"


def test_canonical_section_vocabulary() -> None:
    assert PRODUCT.label == "📦 Товар"
    assert PRODUCT.callback_data == "menu:product"
    assert SUPPLIERS.label == "🤝 Поставщики"
    assert WAREHOUSE.label == "📦 Склад"
    assert STOREFRONT.label == "🏷 Витрина"
    assert TEAM.label == "👥 Команда"
    assert ANALYTICS.label == "📊 Аналитика"
    assert INBOX.label == "📨 Входящие"
    assert HOME.label == "🏠 Меню"
    assert button(PRODUCT).text == PRODUCT.label


def test_product_back_button_uses_canonical_product_label(monkeypatch) -> None:
    monkeypatch.setattr(ui_commerce, "_warehouse_stock_units", lambda *_args: 0)
    markup = ui_commerce._procurement_products_keyboard(
        object(),
        1,
        [{"id": 1, "title": "Амфетамин"}],
    )
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert labels[-2:] == [PRODUCT.label, HOME.label]


def test_no_post_hoc_button_normalizer_or_hidden_back_arrows() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in APP.rglob("*.py"))
    assert "_normalize_menu_buttons" not in source
    assert "_normalize_button_text" not in source
    assert "← " not in source


def test_global_buttons_cannot_reinvent_canonical_labels() -> None:
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
            line = f"{source_path.relative_to(APP)}:{getattr(node, 'lineno', '?')}"
            if name == "nav_row":
                first_arg = node.args[0] if node.args else None
                if isinstance(first_arg, ast.Constant) and first_arg.value in canonical_callbacks:
                    offenders.append(
                        f"{line} raw canonical nav callback={first_arg.value!r}; use UiItem"
                    )
                continue
            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
            callback_kw = next((kw.value for kw in node.keywords if kw.arg == "callback_data"), None)
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


def test_gameplay_entity_buttons_keep_semantic_markers() -> None:
    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")
    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")
    staff_handlers = (APP / "ui_staff_handlers.py").read_text(encoding="utf-8")
    disputes = (APP / "ui_disputes.py").read_text(encoding="utf-8")

    assert 'text=f"{product[\'title\']} · 🚚 {warehouse_units} ед."' in commerce
    assert 'text=f"🚚 {employee[\'alias\']}{suffix}"' in commerce
    assert 'text=f"📦 {batch[\'product_title\']} · {batch[\'remaining\']} ед. · 🚚 {batch[\'employee_alias\']} · {state}"' in staff
    assert 'text=f"Сменить на {role_label(new_role)}"' in staff_handlers
    assert 'nav_row(f"dispute:view:{dispute_id}:{page}", "⚖️ Диспут")' in disputes


def test_local_numeric_controls_do_not_require_decorative_emoji() -> None:
    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")
    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")
    assert 'text="−5%"' in commerce
    assert 'text="+5%"' in commerce
    assert 'text="−5"' in staff
    assert 'text="+5"' in staff
