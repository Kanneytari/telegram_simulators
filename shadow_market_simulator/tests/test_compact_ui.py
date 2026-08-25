from app.analytics.analytics_handlers import analytics_view_keyboard
from app import ui_commerce
from app.ui_commerce import _product_root_keyboard, packaging_keyboard
from app.ui_navigation import home_keyboard, inbox_keyboard
from app.ui_staff import _profile_keyboard, more_keyboard


def labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_home_uses_only_canonical_sections():
    assert labels(home_keyboard(5, 2)) == [
        "📨 Входящие · 5 · 🔴 2",
        "📦 Товар",
        "🏷 Витрина",
        "👥 Команда",
        "📊 Аналитика",
        "🔄 Обновить",
    ]


def test_inbox_is_flat_without_category_screen():
    items = [
        {"id": 1, "priority": "urgent", "title": "Срочное событие"},
        {"id": 2, "priority": "normal", "title": "Обычное событие"},
    ]
    assert labels(inbox_keyboard(items)) == [
        "🔴 Срочное событие",
        "Обычное событие",
        "🔄 Обновить",
        "🏠 Меню",
    ]


def test_courier_profile_separates_frequent_and_rare_actions():
    profile = labels(_profile_keyboard(42, "courier"))
    assert "Премия · 5 000 ₽" in profile
    assert "Отдых" in profile
    assert "Развитие" in profile
    assert "Ещё" in profile
    assert "Переименовать" not in profile
    assert "Уволить" not in profile

    more = labels(more_keyboard(42))
    assert more[:3] == ["Переименовать", "Сменить роль", "Уволить"]


def test_packaging_is_nested_under_sales():
    markup = packaging_keyboard({"pct_1": 60, "pct_2": 30, "pct_5": 10})
    assert "menu:storefront" in callbacks(markup)
    assert "menu:team" not in callbacks(markup)



def test_product_root_nests_procurement_under_suppliers():
    markup = _product_root_keyboard(3)
    assert labels(markup) == [
        "🤝 Поставщики",
        "📦 Склад · 3",
        "🏠 Меню",
    ]
    assert callbacks(markup) == ["proc:suppliers", "team:batches", "menu:home"]


def test_suppliers_screen_contains_product_categories(monkeypatch):
    monkeypatch.setattr(ui_commerce, "_stock_status", lambda *_args: "нет запаса")
    markup = ui_commerce._procurement_products_keyboard(
        object(),
        1,
        [
            {"id": 1, "title": "Амфетамин"},
            {"id": 3, "title": "Кокаин"},
        ],
    )
    assert labels(markup) == ["Амфетамин", "Кокаин", "📦 Товар", "🏠 Меню"]
    assert callbacks(markup) == [
        "proc:product:1", "proc:product:3", "menu:product", "menu:home"
    ]

def test_analytics_uses_same_compact_navigation_language():
    assert labels(analytics_view_keyboard("overview", "7")) == [
        "✓ Обзор",
        "Товары",
        "Деньги",
        "✓ 7 дней",
        "30 дней",
        "🏠 Меню",
    ]
