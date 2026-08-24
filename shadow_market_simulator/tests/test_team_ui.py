from app.team_keyboard import employee_list


def test_team_buttons_show_role_icons_before_names():
    markup = employee_list([
        {
            "id": 1,
            "alias": "Маяк",
            "role": "warehouse",
            "deposit": 500000,
            "exposure": 100000,
            "status_text": "готово к распределению · 20 ед.",
            "idle_ready": False,
        },
        {
            "id": 2,
            "alias": "Крот",
            "role": "courier",
            "deposit": 50000,
            "exposure": 10000,
            "status_text": "свободен",
            "idle_ready": False,
        },
    ])

    assert markup.inline_keyboard[0][0].text.startswith("🚚 Маяк ·")
    assert markup.inline_keyboard[1][0].text.startswith("👤 Крот ·")
    assert "опт" not in markup.inline_keyboard[0][0].text
    assert "розница" not in markup.inline_keyboard[1][0].text
    assert "свободен" not in markup.inline_keyboard[1][0].text.lower()
