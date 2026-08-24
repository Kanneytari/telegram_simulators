from __future__ import annotations

from datetime import timedelta

from . import procurement_market, tutorial, workflow
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


def _install_final_procurement_protection() -> None:
    current = procurement_market.ProcurementMarketGameService.buy_offer_for_employee
    if getattr(current, "_nightshift_tutorial_final", False):
        return

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        state = tutorial.tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != tutorial.STAGE_PROCUREMENT:
            return current(self, player_id, offer_id, employee_id)

        # The tutorial implementation attached to WorkflowGameService uses the
        # real batch/task pipeline, but deliberately removes first-run RNG failure.
        result = workflow.WorkflowGameService.buy_offer_for_employee(
            self,
            player_id,
            offer_id,
            employee_id,
        )
        self.simulation.ensure_procurement_bounds(player_id, utcnow())
        return result.replace(
            "На этот раз сделка точно дойдёт до следующего этапа. ",
            "",
        )

    buy_offer_for_employee._nightshift_tutorial_final = True
    procurement_market.ProcurementMarketGameService.buy_offer_for_employee = buy_offer_for_employee


def _install_affordable_product_filter() -> None:
    current = procurement_market.ProcurementMarketGameService.procurement_products
    if getattr(current, "_nightshift_tutorial_final", False):
        return

    def procurement_products(self, player_id: int):
        rows = list(current(self, player_id))
        state = tutorial.tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != tutorial.STAGE_PROCUREMENT:
            return rows
        affordable_product_ids = {
            int(offer["product_id"])
            for offer in self.offers(player_id)
        }
        return [row for row in rows if int(row["id"]) in affordable_product_ids]

    procurement_products._nightshift_tutorial_final = True
    procurement_market.ProcurementMarketGameService.procurement_products = procurement_products


def apply_tutorial_runtime_fixes() -> None:
    tutorial.skip_tutorial_wait = _safe_skip_tutorial_wait
    _install_final_procurement_protection()
    _install_affordable_product_filter()


_ORIGINAL_SKIP = tutorial.skip_tutorial_wait
