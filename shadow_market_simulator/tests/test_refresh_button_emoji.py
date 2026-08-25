from app.presentation.vocabulary import REFRESH, button


def test_refresh_button_uses_canonical_refresh_label():
    refresh = button(REFRESH, callback_data="anything:refresh")
    assert refresh.text == "🔄 Обновить"
    assert refresh.callback_data == "anything:refresh"


def test_refresh_label_has_single_emoji_source():
    assert REFRESH.label == "🔄 Обновить"
    assert REFRESH.label.count("🔄") == 1
