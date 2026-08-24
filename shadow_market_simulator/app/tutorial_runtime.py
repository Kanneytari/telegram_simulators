from __future__ import annotations

from . import procurement_market, simulation, tutorial, ui_commerce
from .ui_common import clean, money, notice, present


def _instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]

    if stage == tutorial.STAGE_PROCUREMENT:
        return (
            "Привет, бро! Рад видеть.\n"
            "Поздравляю, теперь у тебя свой шоп.\n\n"
            "Самое время закупиться первой партией товара.\n"
            "Нажми [📦 Товар] и выбери стафф, с которого хочешь начать.\n"
            "Обрати внимание на цену, качество и надежность поставки.\n\n"
            "Мы тут не конфеты продаем. Случиться может что угодно.\n"
            "Смотри в оба.\n"
            "Обнял."
        )
    if stage == tutorial.STAGE_PICKUP_WAIT:
        return (
            "Складмен забирает товар. Обычно это занимает игровое время. "
            "Можешь заниматься другими делами, дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_HANDOFF:
        return (
            "Вернись в меню, нажми 📦 Товар, затем 📦 Склад. "
            "Открой партию и выбери закладчика, которому передашь стафф."
        )
    if stage == tutorial.STAGE_HANDOFF_WAIT:
        return (
            "Складмен передаёт товар закладчику. Можешь продолжать заниматься магазином, "
            "дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_PREP_WAIT:
        return (
            "Закладчик готовит товар к витрине. "
            "Можешь дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_PRICE:
        return (
            "Вернись в меню и нажми 🏷 Витрина. Выбери товар, затем выбери фасовку и измени цену. "
            "Цена влияет на спрос и ожидания покупателей."
        )
    if stage == tutorial.STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи. Можешь продолжать играть как обычно "
            "или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошёл. Выручка ещё не равна чистой прибыли. "
            "Есть себестоимость товара и выплаты команде. После продаж появляются оценки товара и закладчика. "
            "Нажми кнопку Продолжить обучение, чтобы познакомиться с диспутами."
        )
    if stage == tutorial.STAGE_DISPUTE:
        return (
            "Открой 📨 Входящие и разбери диспут. Можно запросить пояснение сотрудника, "
            "изучить ситуацию и решить, компенсировать заказ или отказать."
        )
    if stage == tutorial.STAGE_TEAM:
        return (
            "Перед завершением посмотри остальные разделы. "
            "В 👥 Команде можно проверить сотрудников, их нагрузку, депозит и результаты работы. "
            "В Найме можно искать новых сотрудников и задавать требования к кандидатам. "
            "В Оплате можно менять условия выплат для складменов и закладчиков. "
            "В 🏷 Фасовках можно настроить, какая часть нового товара будет продаваться по 1, 2 и 5 единиц. "
            "В 📊 Аналитике можно посмотреть продажи, расходы и прибыль. "
            "В 📨 Входящих появляются сообщения и ситуации, которые требуют твоего решения. "
            "Когда разберёшься, заверши обучение."
        )
    return "Обучение завершено."


def _install_copy_rules() -> None:
    tutorial._instruction = _instruction

    current = simulation.SimulationEngine.ensure_player
    if getattr(current, "_nightshift_tutorial_copy_rules", False):
        return

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = current(self, player_id, username)
        if created:
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE inbox
                       SET body='Склад пуст. Начни с первой закупки в разделе Товар.'
                       WHERE player_id=? AND kind='tutorial'""",
                    (player_id,),
                )
        return created

    ensure_player._nightshift_tutorial_copy_rules = True
    simulation.SimulationEngine.ensure_player = ensure_player


def _install_procurement_empty_state() -> None:
    current_root = ui_commerce.render_product_root
    if not getattr(current_root, "_nightshift_affordable_empty", False):

        async def render_product_root(
            target,
            db,
            game,
            player_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            products = game.procurement_products(player_id)
            if products:
                await current_root(target, db, game, player_id, flash=flash)
                return
            with db.connect() as conn:
                free_cash = game._free_cash_conn(conn, player_id)
            body = (
                f"<b>📦 Товар</b>\n\n"
                f"Свободно: <b>{money(free_cash)}</b>\n\n"
                "Доступных предложений нет."
            )
            await present(
                target,
                notice(flash, body),
                ui_commerce._procurement_products_keyboard(db, player_id, products),
            )

        render_product_root._nightshift_affordable_empty = True
        ui_commerce.render_product_root = render_product_root

    current_product = ui_commerce.render_procurement_product
    if not getattr(current_product, "_nightshift_affordable_empty", False):

        async def render_procurement_product(
            target,
            game,
            player_id: int,
            product_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            offers = game.offers(player_id, product_id)
            if offers:
                await current_product(
                    target,
                    game,
                    player_id,
                    product_id,
                    flash=flash,
                )
                return
            with game.db.connect() as conn:
                product = conn.execute(
                    "SELECT title FROM products WHERE id=? AND active=1",
                    (product_id,),
                ).fetchone()
            if not product:
                await ui_commerce.render_product_root(
                    target,
                    game.db,
                    game,
                    player_id,
                    flash=flash,
                )
                return
            body = (
                f"<b>📦 {clean(product['title'])}</b>\n\n"
                "Доступных предложений нет."
            )
            await present(
                target,
                notice(flash, body),
                ui_commerce._offers_keyboard(product_id, offers),
            )

        render_procurement_product._nightshift_affordable_empty = True
        ui_commerce.render_procurement_product = render_procurement_product


def _install_first_batch_quality_protection() -> None:
    current = procurement_market.ProcurementMarketGameService.buy_offer_for_employee
    if getattr(current, "_nightshift_tutorial_quality", False):
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

        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT offer_quality_mean, offer_quality_sigma
                   FROM supplier_offers
                   WHERE id=? AND player_id=? AND status='open'""",
                (offer_id, player_id),
            ).fetchone()
            if not offer:
                return current(self, player_id, offer_id, employee_id)
            previous_mean = offer["offer_quality_mean"]
            previous_sigma = offer["offer_quality_sigma"]
            conn.execute(
                """UPDATE supplier_offers
                   SET offer_quality_mean=84.0, offer_quality_sigma=0.0
                   WHERE id=?""",
                (offer_id,),
            )

        try:
            return current(self, player_id, offer_id, employee_id)
        finally:
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE supplier_offers
                       SET offer_quality_mean=?, offer_quality_sigma=?
                       WHERE id=?""",
                    (previous_mean, previous_sigma, offer_id),
                )

    buy_offer_for_employee._nightshift_tutorial_quality = True
    procurement_market.ProcurementMarketGameService.buy_offer_for_employee = (
        buy_offer_for_employee
    )


def apply_tutorial_runtime_fixes() -> None:
    """Keep tutorial guidance non-blocking and normalize player-facing copy."""
    _install_copy_rules()
    _install_procurement_empty_state()
    _install_first_batch_quality_protection()
