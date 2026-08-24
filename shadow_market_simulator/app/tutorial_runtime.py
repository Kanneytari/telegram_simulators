from __future__ import annotations

from . import (
    analytics_handlers,
    procurement_market,
    simulation,
    tutorial,
    ui_commerce,
    ui_navigation,
    ui_staff,
    ui_staff_handlers,
)
from .ui_common import clean, money, notice, present, tutorial_hint


RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


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
        return "Нажми [📦 Товар]"
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
            "Перед завершением обучения посмотри остальные разделы.\n\n"
            "[👥 Команда]\n"
            "Здесь можно проверить сотрудников, их нагрузку, депозит и результаты работы.\n\n"
            "[🔎 Нанять]\n"
            "Здесь можно искать новых сотрудников и задавать требования к кандидатам.\n\n"
            "[⚙️ Оплата]\n"
            "Здесь можно менять условия выплат для складменов и закладчиков.\n\n"
            "[⚙️ Фасовки]\n"
            "Здесь настраивается, какая часть нового товара будет продаваться по 1, 2 и 5 единиц.\n\n"
            "[📊 Аналитика]\n"
            "Здесь можно посмотреть продажи, расходы и прибыль.\n\n"
            "[📨 Входящие]\n"
            "Здесь появляются сообщения и ситуации, которые требуют решения.\n\n"
            "Когда закончишь, нажми [✅ Завершить обучение]."
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
            if any(int(product.get("total", 0)) > 0 for product in products):
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


def _handoff_state(db, player_id: int) -> bool:
    state = tutorial.sync_tutorial_state(db, player_id)
    return bool(
        state
        and state["active"]
        and state["stage"] == tutorial.STAGE_HANDOFF
    )


class _HintTarget:
    def __init__(self, target, hint: str):
        self._target = target
        self._hint = hint
        self.photo = getattr(target, "photo", None)

    def _text(self, text: str) -> str:
        return f"{text}\n\n{self._hint}"

    async def edit_text(self, text, **kwargs):
        return await self._target.edit_text(self._text(text), **kwargs)

    async def answer(self, text, **kwargs):
        return await self._target.answer(self._text(text), **kwargs)

    async def delete(self):
        return await self._target.delete()


def _return_target(target):
    return _HintTarget(target, tutorial_hint(RETURN_TO_MENU))


def _install_handoff_guidance() -> None:
    current_product_root = ui_commerce.render_product_root
    if not getattr(current_product_root, "_nightshift_handoff_steps", False):

        async def render_product_root(
            target,
            db,
            game,
            player_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            if not _handoff_state(db, player_id):
                await current_product_root(target, db, game, player_id, flash=flash)
                return
            products = game.procurement_products(player_id)
            body = (
                f"<b>📦 Товар</b>\n\n"
                f"Свободно: <b>{money(game._free_cash_conn(db.connect().__enter__(), player_id))}</b>"
            )
            # Avoid keeping a manually entered connection open: recalculate normally.
            with db.connect() as conn:
                free_cash = game._free_cash_conn(conn, player_id)
            body = (
                f"<b>📦 Товар</b>\n\n"
                f"Свободно: <b>{money(free_cash)}</b>\n\n"
                + tutorial_hint("Нажми [📦 Склад]")
            )
            await present(
                target,
                notice(flash, body),
                ui_commerce._procurement_products_keyboard(db, player_id, products),
            )

        render_product_root._nightshift_handoff_steps = True
        ui_commerce.render_product_root = render_product_root

    current_product = ui_commerce.render_procurement_product
    if not getattr(current_product, "_nightshift_handoff_steps", False):

        async def render_procurement_product(
            target,
            game,
            player_id: int,
            product_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            if not _handoff_state(game.db, player_id):
                await current_product(
                    target,
                    game,
                    player_id,
                    product_id,
                    flash=flash,
                )
                return
            await current_product(
                _return_target(target),
                game,
                player_id,
                product_id,
                flash=flash,
            )

        render_procurement_product._nightshift_handoff_steps = True
        ui_commerce.render_procurement_product = render_procurement_product

    current_storefront = ui_commerce.render_storefront_root
    if not getattr(current_storefront, "_nightshift_handoff_steps", False):

        async def render_storefront_root(
            target,
            db,
            game,
            simulation_engine,
            player_id: int,
        ) -> None:
            wrapped = _return_target(target) if _handoff_state(db, player_id) else target
            await current_storefront(
                wrapped,
                db,
                game,
                simulation_engine,
                player_id,
            )

        render_storefront_root._nightshift_handoff_steps = True
        ui_commerce.render_storefront_root = render_storefront_root

    current_sales_product = ui_commerce.render_sales_product
    if not getattr(current_sales_product, "_nightshift_handoff_steps", False):

        async def render_sales_product(target, db, player_id: int, product_id: int) -> None:
            wrapped = _return_target(target) if _handoff_state(db, player_id) else target
            await current_sales_product(wrapped, db, player_id, product_id)

        render_sales_product._nightshift_handoff_steps = True
        ui_commerce.render_sales_product = render_sales_product

    current_listing = ui_commerce.render_listing
    if not getattr(current_listing, "_nightshift_handoff_steps", False):

        async def render_listing(
            target,
            db,
            game,
            player_id: int,
            listing_id: int,
        ) -> None:
            wrapped = _return_target(target) if _handoff_state(db, player_id) else target
            await current_listing(wrapped, db, game, player_id, listing_id)

        render_listing._nightshift_handoff_steps = True
        ui_commerce.render_listing = render_listing

    current_inbox = ui_navigation.render_inbox
    if not getattr(current_inbox, "_nightshift_handoff_steps", False):

        async def render_inbox(
            target,
            game,
            simulation_engine,
            player_id: int,
            *,
            flash: str | None = None,
            page: int = 0,
        ) -> None:
            wrapped = _return_target(target) if _handoff_state(game.db, player_id) else target
            await current_inbox(
                wrapped,
                game,
                simulation_engine,
                player_id,
                flash=flash,
                page=page,
            )

        render_inbox._nightshift_handoff_steps = True
        ui_navigation.render_inbox = render_inbox

    current_team = ui_staff.render_team
    if not getattr(current_team, "_nightshift_handoff_steps", False):

        async def render_team(
            target,
            game,
            simulation_engine,
            player_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            wrapped = _return_target(target) if _handoff_state(game.db, player_id) else target
            await current_team(
                wrapped,
                game,
                simulation_engine,
                player_id,
                flash=flash,
            )

        render_team._nightshift_handoff_steps = True
        ui_staff.render_team = render_team
        ui_staff_handlers.render_team = render_team

    for name in ("overview_text", "products_text", "finance_text"):
        current = getattr(analytics_handlers, name)
        if getattr(current, "_nightshift_handoff_steps", False):
            continue

        def render_analytics(db, player_id: int, period: str, _current=current):
            text = _current(db, player_id, period)
            if _handoff_state(db, player_id):
                text += "\n\n" + tutorial_hint(RETURN_TO_MENU)
            return text

        render_analytics._nightshift_handoff_steps = True
        setattr(analytics_handlers, name, render_analytics)


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
    _install_handoff_guidance()
    _install_first_batch_quality_protection()
