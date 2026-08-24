from __future__ import annotations

from .staff_insights import StaffInsightGameService


def apply_handoff_copy_update() -> None:
    original_status = StaffInsightGameService._task_status
    if not getattr(original_status, "_master_stash_copy", False):
        def _task_status(self, player_id: int, employee_id: int) -> str:
            return original_status(self, player_id, employee_id).replace(
                "готовит передачу",
                "готовит мастер-клад",
            )

        _task_status._master_stash_copy = True
        StaffInsightGameService._task_status = _task_status

    original_activity = StaffInsightGameService._activity_details
    if not getattr(original_activity, "_master_stash_copy", False):
        def _activity_details(self, player_id: int, employee_id: int) -> list[str]:
            return [
                line.replace(
                    "Подготовка передачи закладчику",
                    "Подготовка мастер-клада",
                )
                for line in original_activity(self, player_id, employee_id)
            ]

        _activity_details._master_stash_copy = True
        StaffInsightGameService._activity_details = _activity_details
