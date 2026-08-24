



def test_inventory_free_ready_courier_is_green_and_has_deposit_without_free_status():
    text = button_text({
        "id": 1,
        "alias": "Крот",
        "role": "courier",
        "deposit": 25_000,
        "exposure": 0,
        "status_text": "свободен",
        "idle_ready": True,
    })

    assert "👤 Крот · 25,000 ₽" in text
    assert "🟢" in text
    assert "🔴" not in text
    assert "свободен" not in text.lower()


def test_zero_exposure_courier_is_not_green_unless_ready_for_new_work():
    text = button_text({
        "id": 5,
        "alias": "Пауза",
        "role": "courier",
        "deposit": 30_000,
        "exposure": 0,
        "status_text": "временная пауза · ~3.0 ч",
        "idle_ready": False,
    })

    assert "🟢" not in text
    assert "временная пауза" in text


def test_covered_inventory_has_no_green_or_red_marker():
    text = button_text({
        "id": 2,
        "alias": "Сова",
        "role": "courier",
        "deposit": 50_000,
        "exposure": 20_000,
        "status_text": "готовит позиции · ~1.2 ч",
        "idle_ready": False,
    })

    assert "👤 Сова · 50,000 ₽" in text
    assert "готовит позиции · ~1.2 ч" in text
    assert "🟢" not in text
    assert "🔴" not in text


def test_uncovered_inventory_is_red_even_when_task_is_active():
    text = button_text({
        "id": 3,
        "alias": "Маяк",
        "role": "warehouse",
        "deposit": 700_000,
        "exposure": 900_000,
        "status_text": "готовит передачу · ~2.0 ч",
        "idle_ready": False,
    })

    assert "🚚 Маяк · 700,000 ₽" in text
    assert "готовит передачу · ~2.0 ч" in text
    assert "🔴" in text
    assert "🟢" not in text


def test_free_prefix_is_removed_but_useful_inventory_hint_remains():
    text = button_text({
        "id": 4,
        "alias": "Гриф",
        "role": "warehouse",
        "deposit": 100_000,
        "exposure": 40_000,
        "status_text": "свободен · к распределению 20 ед.",
        "idle_ready": False,
    })

    assert "свободен" not in text.lower()
    assert "к распределению 20 ед." in text
    assert "🟢" not in text
