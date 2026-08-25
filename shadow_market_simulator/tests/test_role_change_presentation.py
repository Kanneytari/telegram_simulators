from pathlib import Path


def test_role_change_screen_uses_entity_helpers() -> None:
    source = Path("app/ui_staff_handlers.py").read_text(encoding="utf-8")
    assert 'Сейчас: {role_html(current_role)}' in source
    assert 'Новая роль: {role_html(new_role)}' in source
    assert 'Сменить на {role_label(new_role)}' in source
    assert 'Сменить на {new}' not in source

