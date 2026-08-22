from app import keyboards


def test_expedition_keyboard_has_only_explore_and_return() -> None:
    markup = keyboards.expedition()
    buttons = [button for row in markup.inline_keyboard for button in row]

    assert [button.text for button in buttons] == [
        "🔎 Исследовать сектор",
        "↩️ Вернуться",
    ]
    assert all(button.callback_data != "expedition:inventory" for button in buttons)
