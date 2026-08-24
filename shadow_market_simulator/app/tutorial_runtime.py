from __future__ import annotations

from . import procurement_market, tutorial, workflow
from .simulation import utcnow


def _install_final_procurement_protection() -> None:
    current = procurement_market.ProcurementMarketGameService.buy_offer_for_employee
    if getattr(current, "_nightshift_tutorial_final", False):
        return

    def buy_offer_for_employee(
        self,
        player_id: int,
        offer_id: int,
        employee_id: int,
    ) -> str:
        state = tutorial.tutorial_state(self.db, player_id)
        if (
            not state
            or not state["active"]
            or state["stage"] != tutorial.STAGE_PROCUREMENT
        ):
            return current(self, player_id, offer_id, employee_id)

        result = workflow.WorkflowGameService.buy_offer_for_employee(
            self,
            player_id,
            offer_id,
            employee_id,
        )
        self.simulation.ensure_procurement_bounds(player_id, utcnow())
        return result

    buy_offer_for_employee._nightshift_tutorial_final = True
    procurement_market.ProcurementMarketGameService.buy_offer_for_employee = (
        buy_offer_for_employee
    )


def _install_affordable_product_filter() -> None:
    current = procurement_market.ProcurementMarketGameService.procurement_products
    if getattr(current, "_nightshift_tutorial_final", False):
        return

    def procurement_products(self, player_id: int):
        rows = list(current(self, player_id))
        state = tutorial.tutorial_state(self.db, player_id)
        if (
            not state
            or not state["active"]
            or state["stage"] != tutorial.STAGE_PROCUREMENT
        ):
            return rows
        affordable_product_ids = {
            int(offer["product_id"])
            for offer in self.offers(player_id)
        }
        return [
            row
            for row in rows
            if int(row["id"]) in affordable_product_ids
        ]

    procurement_products._nightshift_tutorial_final = True
    procurement_market.ProcurementMarketGameService.procurement_products = (
        procurement_products
    )


def apply_tutorial_runtime_fixes() -> None:
    _install_final_procurement_protection()
    _install_affordable_product_filter()
