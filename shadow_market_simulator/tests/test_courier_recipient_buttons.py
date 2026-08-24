from app.courier_idle_handlers import recipient_button_text


def test_idle_courier_has_green_marker_next_to_name():
    text = recipient_button_text({
        "id": 1,
        "alias": "Крот",
        "deposit": 50_000,
        "exposure": 0,
        "status_text": "свободен",
        "idle_ready": True,
    })

    assert text.startswith("🟢 Крот · депозит 50,000 ₽")
    assert "свободен" not in text.lower()


def test_waiting_courier_has_no_green_marker():
    text = recipient_button_text({
        "id": 2,
        "alias": "Сова",
        "deposit": 60_000,
        "exposure": 0,
        "status_text": "ожидает товар · 20 ед.",
        "idle_ready": False,
    })

    assert "🟢" not in text
    assert "ожидает товар · 20 ед." in text
