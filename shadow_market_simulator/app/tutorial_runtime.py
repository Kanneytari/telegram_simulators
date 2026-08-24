from __future__ import annotations

from datetime import timedelta

from . import tutorial
from .simulation import iso, utcnow


def _safe_skip_tutorial_wait(game, simulation_engine, player_id: int) -> str:
    state = tutorial.tutorial_state(game.db, player_id)
    if not state or not state["active"]:
        return "Обучение уже завершено."

    if state["stage"] not in {
        tutorial.STAGE_PICKUP_WAIT,
        tutorial.STAGE_HANDOFF_WAIT,
        tutorial.STAGE_PREP_WAIT,
    }:
        # The sale step in the original implementation already commits before
        # changing tutorial_state, so it is transaction-safe as written.
        return _ORIGINAL_SKIP(game, simulation_engine, player_id)

    now = utcnow()
    next_stage: str | None = None
    next_data: dict = {}
    message = "Задача ещё не готова к следующему этапу."

    with game.db.connect() as conn:
        task = tutorial._active_task_for_stage(conn, player_id, state)
        if task:
            conn.execute(
                "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                (iso(now - timedelta(seconds=1)), int(task["id"])),
            )
            simulation_engine._process_tasks(conn, player_id, now)

        if state["stage"] == tutorial.STAGE_PICKUP_WAIT:
            batch = conn.execute(
                "SELECT status FROM batches WHERE id=? AND player_id=?",
                (int(state["data"].get("batch_id", 0)), player_id),
            ).fetchone()
            if batch and batch["status"] == "warehouse":
                next_stage = tutorial.STAGE_HANDOFF
                message = "Партия получена."

        elif state["stage"] == tutorial.STAGE_HANDOFF_WAIT:
            allocation = conn.execute(
                "SELECT status FROM retail_allocations WHERE id=? AND player_id=?",
                (int(state["data"].get("allocation_id", 0)), player_id),
            ).fetchone()
            if allocation and allocation["status"] == "preparing":
                next_stage = tutorial.STAGE_PREP_WAIT
                message = "Передача завершена. Закладчик начал подготовку."

        else:
            allocation = conn.execute(
                "SELECT status, product_id FROM retail_allocations WHERE id=? AND player_id=?",
                (int(state["data"].get("allocation_id", 0)), player_id),
            ).fetchone()
            if allocation and allocation["status"] == "published":
                next_stage = tutorial.STAGE_PRICE
                next_data["product_id"] = int(allocation["product_id"])
                message = "Товар появился на витрине."

    if next_stage:
        tutorial._set_stage(game.db, player_id, next_stage, **next_data)
    return message


def apply_tutorial_runtime_fixes() -> None:
    tutorial.skip_tutorial_wait = _safe_skip_tutorial_wait


_ORIGINAL_SKIP = tutorial.skip_tutorial_wait
