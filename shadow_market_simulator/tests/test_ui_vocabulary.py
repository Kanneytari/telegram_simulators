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
    monkeypatch.setattr(ui_commerce, "_stock_status", lambda *_args: "нет запаса")
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


def test_plain_product_button_cannot_return() -> None:
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
