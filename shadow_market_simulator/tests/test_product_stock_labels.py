from __future__ import annotations

from app import ui_commerce
from app.presentation.entities import product_html


class _Row:
    def __getitem__(self, key):
        if key == 0:
            return 17
        raise KeyError(key)


class _Cursor:
    def fetchone(self):
        return _Row()


class _Conn:
    def execute(self, sql, params):
        assert "status='warehouse'" in sql
        assert "orders" not in sql
        assert "retail_allocations" not in sql
        return _Cursor()


class _Context:
    def __enter__(self):
        return _Conn()

    def __exit__(self, exc_type, exc, tb):
        return False


class _Db:
    def connect(self):
        return _Context()


def test_product_entity_has_no_product_section_emoji() -> None:
    assert product_html("LSD") == "<b>LSD</b>"


def test_suppliers_show_actual_warehouse_units_without_product_emoji() -> None:
    db = _Db()
    assert ui_commerce._warehouse_stock_units(db, 1, 2) == 17
    markup = ui_commerce._procurement_products_keyboard(
        db,
        1,
        [{"id": 2, "title": "LSD"}],
    )
    assert markup.inline_keyboard[0][0].text == "LSD · 🚚 17 ед."
    assert markup.inline_keyboard[0][0].callback_data == "proc:product:2"
