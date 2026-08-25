from app.analytics.analytics_handlers import analytics_payroll_keyboard, analytics_view_keyboard


def labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_overview_navigation_is_compact_and_has_only_agreed_sections():
    markup = analytics_view_keyboard("overview", "7")
    names = labels(markup)

    assert "✓ 📊 Обзор" in names
    assert "📦 Товары" in names
    assert "💰 Деньги" in names
    assert "✓ 7 дней" in names
    assert "30 дней" in names
    assert "🏠 Меню" in names
    assert "👥 Команда" not in names
    assert "📅 По дням" not in names
    assert "🧪 Качество" not in names
    assert "🤝 Клиенты" not in names
    assert "Всё время" not in names
    assert len(names) == 6


def test_money_and_payroll_keep_selected_period():
    money = analytics_view_keyboard("finance", "30")
    assert "analytics:payroll:30" in callbacks(money)

    payroll = analytics_payroll_keyboard("30")
    assert "analytics:view:finance:30" in callbacks(payroll)
