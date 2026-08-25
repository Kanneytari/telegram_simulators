from app.commerce.workflow import _format_game_duration


def test_team_task_time_uses_hours_and_minutes() -> None:
    assert _format_game_duration(0.5) == "30 м"
    assert _format_game_duration(1.2) == "1 ч 12 м"
    assert _format_game_duration(2.0) == "2 ч"
    assert _format_game_duration(2.01) == "2 ч 1 м"


def test_active_task_never_renders_zero_minutes() -> None:
    assert _format_game_duration(0.0) == "1 м"
