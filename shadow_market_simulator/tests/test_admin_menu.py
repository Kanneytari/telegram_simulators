from app.keyboards import main_menu


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_admin_button_hidden_for_regular_player():
    markup = main_menu(0, 0, is_admin=False)
    assert "admin:panel" not in _callbacks(markup)


def test_admin_button_visible_for_admin():
    markup = main_menu(0, 0, is_admin=True)
    callbacks = _callbacks(markup)
    assert "admin:panel" in callbacks
    button = next(
        button
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data == "admin:panel"
    )
    assert button.text == "🛠 Админ"
