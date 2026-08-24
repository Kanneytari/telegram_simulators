from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import procurement_market, tutorial, workflow
from .simulation import utcnow
from .ui_common import tutorial_hint


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


def _install_management_tour() -> None:
    current_markup = tutorial._tutorial_home_markup
    current_text = tutorial._home_text
    if getattr(current_markup, "_nightshift_management_tour", False):
        return

    def tutorial_home_markup(stage: str) -> InlineKeyboardMarkup:
        if stage != tutorial.STAGE_TEAM:
            return current_markup(stage)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="👥 Команда", callback_data="menu:team"),
                    InlineKeyboardButton(text="🔎 Найм", callback_data="team:recruit"),
                ],
                [
                    InlineKeyboardButton(text="💰 Оплата", callback_data="team:terms"),
                    InlineKeyboardButton(text="⚙️ Фасовки", callback_data="sales:packaging"),
                ],
                [
                    InlineKeyboardButton(text="📊 Аналитика", callback_data="menu:analytics"),
                    InlineKeyboardButton(text="📨 Входящие", callback_data="menu:inbox"),
                ],
                [
                    InlineKeyboardButton(
                        text="✅ Завершить обучение",
                        callback_data="tutorial:finish",
                    )
                ],
            ]
        )

    def home_text(game, player_id: int, state: dict) -> str:
        text = current_text(game, player_id, state)
        if state["stage"] != tutorial.STAGE_TEAM:
            return text
        return text + "\n\n" + tutorial_hint(
            "Перед завершением загляни в остальные рабочие экраны. В Команде видны состояние, "
            "история и риск сотрудников; в Найме задаются требования к кандидатам; в Оплате — "
            "условия ролей; Фасовки управляют будущей публикацией товара; Аналитика показывает "
            "результаты бизнеса; во Входящих появляются события, требующие решения."
        )

    tutorial_home_markup._nightshift_management_tour = True
    tutorial._tutorial_home_markup = tutorial_home_markup
    tutorial._home_text = home_text


def apply_tutorial_runtime_fixes() -> None:
    _install_final_procurement_protection()
    _install_affordable_product_filter()
    _install_management_tour()
