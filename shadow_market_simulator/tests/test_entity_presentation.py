from app.presentation.entities import employee_html, product_html, role_html, role_label


def test_role_entity_styles_are_canonical() -> None:
    assert role_label("courier") == "👤 закладчик"
    assert role_label("warehouse") == "🚚 складмен"
    assert role_html("courier") == "👤 <b>закладчик</b>"
    assert role_html("warehouse") == "🚚 <b>складмен</b>"
    assert role_html("warehouse", form="складмена") == "🚚 <b>складмена</b>"


def test_named_entities_have_icon_and_bold_text() -> None:
    assert employee_html("Сова", "courier") == "👤 <b>Сова</b>"
    assert employee_html("Маяк", "warehouse") == "🚚 <b>Маяк</b>"
    assert product_html("Кокаин") == "<b>Кокаин</b>"
