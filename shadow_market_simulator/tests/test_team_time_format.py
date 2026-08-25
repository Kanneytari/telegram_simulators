from app.commerce.workflow import _format_game_duration


def test_team_task_time_uses_hours_and_minutes() -> None:
    assert _format_game_duration(0.5) == "30 м"
    assert _format_game_duration(1.2) == "1 ч 12 м"
    assert _format_game_duration(2.0) == "2 ч"
    assert _format_game_duration(2.01) == "2 ч 1 м"


def test_active_task_never_renders_zero_minutes() -> None:
    assert _format_game_duration(0.0) == "1 м"

def test_final_game_service_uses_precise_runtime_status_formatter() -> None:
    import inspect

    from app.staff.couriers.management import CourierManagementGameService
    from app.staff.insights import StaffInsightGameService

    assert CourierManagementGameService._task_status is StaffInsightGameService._task_status
    source = inspect.getsource(CourierManagementGameService._task_status)
    assert "_format_game_duration" in source
    assert "remaining_game:.1f" not in source
    assert "менее 1 ч" not in source

