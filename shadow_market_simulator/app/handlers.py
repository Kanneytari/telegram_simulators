from __future__ import annotations

import json
from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from .db import Database
from .game import GameService, ROLE_NAMES
from .keyboards import (
    analytics_actions,
    candidate_actions,
    candidate_list,
    dispute_actions,
    employee_actions,
    employee_list,
    inbox_actions,
    inbox_list,
    listing_actions,
    listing_list,
    main_menu,
    offer_actions,
    offer_confirm,
    offer_list,
    recruitment_confirm,
    recruitment_menu,
    reset_confirmation,
    result_actions,
)
from .simulation import SimulationEngine, iso, utcnow


RECRUITMENT = {
    "board": (2500, "Доска площадки"),
    "referral": (6000, "Рефералы команды"),
    "niche": (11000, "Нишевая реклама"),
}

LEGACY_MENU = {
    "🏠 Сводка": "home",
    "📨 Входящие": "inbox",
    "👥 Команда": "team",
    "📦 Закупки": "offers",
    "🏷 Витрина": "listings",
    "📊 Аналитика": "analytics",
}


def build_router(
    db: Database,
    game: GameService,
    simulation: SimulationEngine,
    admin_ids: frozenset[int],
) -> Router:
    router = Router()

    def dashboard_snapshot(player_id: int) -> tuple[str, int, int]:
        simulation.advance(player_id)
        with db.connect() as conn:
            shop = conn.execute(
                "SELECT * FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
            deposits = conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]
            stock = conn.execute(
                """SELECT COALESCE(SUM(remaining),0) AS units,
                          COALESCE(SUM(remaining * unit_cost),0) AS cost
                   FROM batches
                   WHERE player_id=? AND status='warehouse'""",
                (player_id,),
            ).fetchone()
            inbox = conn.execute(
                """SELECT COUNT(*) AS opened,
                          SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) AS urgent
                   FROM inbox
                   WHERE player_id=? AND status='open'""",
                (player_id,),
            ).fetchone()
            employees = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]

        opened = int(inbox["opened"] or 0)
        urgent = int(inbox["urgent"] or 0)
        free_cash = int(shop["balance"]) - int(deposits) - int(shop["reserve_target"])
        free_icon = "🔴" if free_cash < 0 else "💵"
        attention = f" · 🔴 {urgent}" if urgent else ""
        text = (
            f"<b>🌒 {shop['name']}</b>\n\n"
            f"💳 Баланс: <b>{shop['balance']:,} ₽</b>\n"
            f"{free_icon} Свободно: <b>{free_cash:,} ₽</b>\n"
            f"⭐ Рейтинг: <b>{shop['rating']:.2f}</b>\n\n"
            f"📦 Запас: {stock['units']} ед. · ~{stock['cost']:,} ₽\n"
            f"👥 Команда: {employees}\n"
            f"📨 Входящие: {opened}{attention}"
        )
        return text, opened, urgent

    async def present(
        target: Message,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
        *,
        edit: bool = False,
    ) -> None:
        if not edit:
            await target.answer(text, reply_markup=markup)
            return
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def show_dashboard(target: Message, player_id: int, *, edit: bool = False) -> None:
        text, opened, urgent = dashboard_snapshot(player_id)
        await present(target, text, main_menu(opened, urgent), edit=edit)

    async def render_inbox(target: Message, player_id: int, *, edit: bool = False) -> None:
        items = game.inbox(player_id)
        urgent = sum(item["priority"] in {"important", "urgent"} for item in items)
        if items:
            text = f"<b>📨 Входящие</b>\n\nОткрыто: <b>{len(items)}</b>"
            if urgent:
                text += f" · требуют внимания: <b>{urgent}</b>"
            text += "\nВыбери сообщение."
        else:
            text = "<b>📨 Входящие</b>\n\nНичего не требует решения."
        await present(target, text, inbox_list(items), edit=edit)

    async def render_team(target: Message, player_id: int, *, edit: bool = False) -> None:
        employees = game.employees(player_id)
        text = (
            f"<b>👥 Команда</b>\n\nВ штате: <b>{len(employees)}</b>\n"
            "Оценивай людей по фактической статистике, а не по скрытым рейтингам."
        )
        await present(target, text, employee_list(employees), edit=edit)

    async def render_candidates(target: Message, player_id: int, *, edit: bool = False) -> None:
        candidates = game.candidates(player_id)
        if candidates:
            text = (
                f"<b>👤 Кандидаты</b>\n\nАктивных анкет: <b>{len(candidates)}</b>\n"
                "Анкета не гарантирует реальное качество работы."
            )
        else:
            text = "<b>👤 Кандидаты</b>\n\nАктивных анкет нет. Запусти поиск."
        await present(target, text, candidate_list(candidates), edit=edit)

    async def render_offers(target: Message, player_id: int, *, edit: bool = False) -> None:
        offers = game.offers(player_id)
        text = (
            f"<b>📦 Закупки</b>\n\nПредложений: <b>{len(offers)}</b>\n"
            "Большая партия дешевле за единицу, но сильнее связывает деньги."
        )
        await present(target, text, offer_list(offers), edit=edit)

    async def render_listings(target: Message, player_id: int, *, edit: bool = False) -> None:
        listings = game.listings(player_id)
        text = (
            "<b>🏷 Витрина</b>\n\n"
            "Цена влияет на спрос и оборачиваемость. Выбери позицию для настройки."
        )
        await present(target, text, listing_list(listings), edit=edit)

    async def render_listing_detail(
        target: Message,
        player_id: int,
        listing_id: int,
        *,
        edit: bool = True,
    ) -> bool:
        rows = {row["id"]: row for row in game.listings(player_id)}
        row = rows.get(listing_id)
        if not row:
            await present(
                target,
                "Позиция больше недоступна.",
                result_actions("menu:listings", "← Витрина"),
                edit=edit,
            )
            return False
        unit = row["price"] / row["pack_size"]
        market_delta = (unit / row["base_market_price"] - 1) * 100
        text = (
            f"<b>🏷 {row['title']} × {row['pack_size']}</b>\n\n"
            f"Цена: <b>{row['price']:,} ₽</b>\n"
            f"За единицу: {unit:,.0f} ₽\n"
            f"К рынку: {market_delta:+.1f}%\n"
            f"Остаток: {row['stock']} ед."
        )
        await present(target, text, listing_actions(listing_id), edit=edit)
        return True

    def offer_by_id(player_id: int, offer_id: int):
        return {offer["id"]: offer for offer in game.offers(player_id)}.get(offer_id)

    def offer_text(offer, *, confirmation: bool = False) -> str:
        total = offer["quantity"] * offer["unit_cost"]
        text = (
            f"<b>📦 {offer['supplier_title']}</b>\n\n"
            f"{offer['product_title']} × {offer['quantity']} ед.\n"
            f"За единицу: {offer['unit_cost']:,} ₽\n"
            f"Итого: <b>{total:,} ₽</b>\n"
            f"Качество: {offer['quality_hint']}"
        )
        if confirmation:
            text += "\n\n<b>Подтвердить покупку?</b>\nСредства спишутся сразу."
        return text

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            intro = (
                "<b>NIGHTSHIFT</b>\n\n"
                "Асинхронный симулятор управления магазином. Продажи, обращения и сотрудники "
                "продолжают жить, пока ты офлайн.\n\n"
                "Все управление находится в inline-меню под сообщениями."
            )
        else:
            intro = "<b>NIGHTSHIFT</b>\n\nВсе управление находится в inline-меню под сообщениями."
        await message.answer(intro, reply_markup=ReplyKeyboardRemove())
        await show_dashboard(message, message.from_user.id)

    @router.message(Command("menu"))
    async def command_menu(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await show_dashboard(message, message.from_user.id)

    @router.message(Command("tick"))
    async def debug_tick(message: Message) -> None:
        """Admin-only helper: advance roughly six simulated hours immediately."""
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (
                    iso(utcnow() - timedelta(hours=6 / max(simulation.speed, 0.1))),
                    message.from_user.id,
                ),
            )
        result = simulation.advance(message.from_user.id)
        _, opened, urgent = dashboard_snapshot(message.from_user.id)
        await message.answer(
            "<b>⏩ Тестовый тик</b>\n\n"
            f"Заказов: {result.orders_created}\n"
            f"Диспутов: {result.disputes_created}\n"
            f"Сообщений: {result.messages_created}",
            reply_markup=main_menu(opened, urgent),
        )

    @router.message(Command("reset"))
    async def reset(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await message.answer(
            "<b>🗑 Сбросить прогресс?</b>\n\n"
            "Будут удалены магазин, деньги, заказы, команда, клиенты, партии, диспуты и статистика.\n"
            "После подтверждения начнётся новая игра. Действие необратимо.",
            reply_markup=reset_confirmation(),
        )

    @router.callback_query(F.data == "reset:confirm")
    async def cb_reset_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        with db.connect() as conn:
            conn.execute("DELETE FROM shops WHERE player_id=?", (callback.from_user.id,))
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        text = "<b>Готово.</b>\n\nПрогресс полностью сброшен. Началась новая игра."
        _, opened, urgent = dashboard_snapshot(callback.from_user.id)
        await present(callback.message, text, main_menu(opened, urgent), edit=True)

    @router.callback_query(F.data == "reset:cancel")
    async def cb_reset_cancel(callback: CallbackQuery) -> None:
        await callback.answer("Сброс отменён")
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    @router.message(F.text.in_(set(LEGACY_MENU)))
    async def legacy_reply_menu(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        section = LEGACY_MENU[message.text]
        await message.answer(
            "Нижнее меню больше не используется — управление перенесено в inline-кнопки.",
            reply_markup=ReplyKeyboardRemove(),
        )
        if section == "home":
            await show_dashboard(message, message.from_user.id)
        elif section == "inbox":
            await render_inbox(message, message.from_user.id)
        elif section == "team":
            await render_team(message, message.from_user.id)
        elif section == "offers":
            await render_offers(message, message.from_user.id)
        elif section == "listings":
            await render_listings(message, message.from_user.id)
        else:
            await message.answer(game.analytics(message.from_user.id), reply_markup=analytics_actions())

    @router.callback_query(F.data == "menu:home")
    async def cb_home(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.in_({"menu:inbox", "inbox:list"}))
    async def cb_inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_inbox(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:team")
    async def cb_team(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_team(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:offers")
    async def cb_offers(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_offers(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:listings")
    async def cb_listings(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_listings(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:analytics")
    async def cb_analytics(callback: CallbackQuery) -> None:
        await callback.answer()
        await present(
            callback.message,
            game.analytics(callback.from_user.id),
            analytics_actions(),
            edit=True,
        )

    @router.callback_query(F.data.startswith("inbox:item:"))
    async def cb_inbox_item(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await present(
                callback.message,
                "Это сообщение уже неактуально.",
                result_actions("menu:inbox", "← Входящие"),
                edit=True,
            )
            return
        marker = {"urgent": "🔴", "important": "🟠", "normal": "⚪"}.get(item["priority"], "⚪")
        await present(
            callback.message,
            f"<b>{marker} {item['title']}</b>\n\n{item['body']}",
            inbox_actions(item),
            edit=True,
        )

    @router.callback_query(F.data.startswith("inbox:dispute:"))
    async def cb_inbox_dispute(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await present(
                callback.message,
                "Диспут уже закрыт.",
                result_actions("menu:inbox", "← Входящие"),
                edit=True,
            )
            return
        dispute_id = int(json.loads(item["payload_json"])["dispute_id"])
        text = game.dispute_details(callback.from_user.id, dispute_id)
        await present(
            callback.message,
            text or "Диспут не найден.",
            dispute_actions(dispute_id) if text else result_actions("menu:inbox", "← Входящие"),
            edit=True,
        )

    @router.callback_query(F.data.startswith("dispute:ask:"))
    async def cb_dispute_ask(callback: CallbackQuery) -> None:
        dispute_id = int(callback.data.split(":")[2])
        reply = game.ask_employee_about_dispute(callback.from_user.id, dispute_id)
        await callback.answer("Пояснение получено" if reply else "Нет ответа")
        text = game.dispute_details(callback.from_user.id, dispute_id)
        await present(
            callback.message,
            text or "Диспут не найден.",
            dispute_actions(dispute_id) if text else result_actions("menu:inbox", "← Входящие"),
            edit=True,
        )

    @router.callback_query(F.data.startswith("dispute:resolve:"))
    async def cb_dispute_resolve(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_id, decision = callback.data.split(":")
        result = game.resolve_dispute(callback.from_user.id, int(dispute_id), decision)
        await present(
            callback.message,
            f"<b>⚖️ Диспут закрыт</b>\n\n{result}",
            result_actions("menu:inbox", "← Входящие"),
            edit=True,
        )

    @router.callback_query(F.data.startswith("inbox:action:"))
    async def cb_inbox_action(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_id, action = callback.data.split(":")
        if action == "close":
            game.close_inbox(callback.from_user.id, int(item_id))
            result = "Сообщение закрыто."
        else:
            result = game.handle_inbox_action(callback.from_user.id, int(item_id), action)
        await present(
            callback.message,
            f"<b>Готово</b>\n\n{result}",
            result_actions("menu:inbox", "← Входящие"),
            edit=True,
        )

    @router.callback_query(F.data == "team:list")
    async def cb_team_legacy(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_team(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("employee:") & ~F.data.startswith("employee:action:"))
    async def cb_employee(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        await present(
            callback.message,
            text or "Сотрудник не найден.",
            employee_actions() if text else result_actions("menu:team", "← Команда"),
            edit=True,
        )

    @router.callback_query(F.data == "candidates:list")
    async def cb_candidates(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_candidates(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(
        F.data.startswith("candidate:")
        & ~F.data.startswith("candidate:hire:")
        & ~F.data.startswith("candidate:reject:")
    )
    async def cb_candidate(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[1])
        with db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, callback.from_user.id),
            ).fetchone()
        if not candidate:
            await present(
                callback.message,
                "Кандидат больше недоступен.",
                result_actions("candidates:list", "← Кандидаты"),
                edit=True,
            )
            return
        text = (
            f"<b>👤 {candidate['alias']}</b>\n\n"
            f"Роль: {ROLE_NAMES.get(candidate['role'], candidate['role'])}\n"
            f"Ставка: <b>{candidate['desired_pay']:,} ₽</b> / заказ\n"
            f"Обеспечение: {candidate['deposit']:,} ₽\n"
            f"Автомобиль: {'есть' if candidate['has_car'] else 'нет'}\n\n"
            f"{candidate['summary']}"
        )
        await present(callback.message, text, candidate_actions(candidate_id), edit=True)

    @router.callback_query(F.data.startswith("candidate:hire:"))
    async def cb_candidate_hire(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        result = game.hire_candidate(callback.from_user.id, candidate_id)
        await present(
            callback.message,
            f"<b>👥 Команда</b>\n\n{result}",
            result_actions("menu:team", "← Команда"),
            edit=True,
        )

    @router.callback_query(F.data.startswith("candidate:reject:"))
    async def cb_candidate_reject(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        game.reject_candidate(callback.from_user.id, candidate_id)
        await present(
            callback.message,
            "<b>Кандидату отказано.</b>",
            result_actions("candidates:list", "← Кандидаты"),
            edit=True,
        )

    @router.callback_query(F.data == "recruit:menu")
    async def cb_recruit_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        await present(
            callback.message,
            "<b>🔎 Поиск сотрудников</b>\n\nДорогой канал повышает среднее качество потока, но ничего не гарантирует.",
            recruitment_menu(),
            edit=True,
        )

    @router.callback_query(F.data.startswith("recruit:confirm:"))
    async def cb_recruit_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        channel = callback.data.split(":")[2]
        cost, title = RECRUITMENT[channel]
        await present(
            callback.message,
            f"<b>🔎 {title}</b>\n\nСтоимость: <b>{cost:,} ₽</b>\nОплата списывается сразу. Запустить поиск?",
            recruitment_confirm(channel, cost),
            edit=True,
        )

    @router.callback_query(F.data.startswith("recruit:run:"))
    async def cb_recruit_run(callback: CallbackQuery) -> None:
        await callback.answer()
        channel = callback.data.split(":")[2]
        result = game.recruit(callback.from_user.id, channel)
        await present(
            callback.message,
            f"<b>🔎 Поиск завершён</b>\n\n{result}",
            result_actions("candidates:list", "← Кандидаты"),
            edit=True,
        )

    @router.callback_query(F.data == "offers:list")
    async def cb_offers_legacy(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_offers(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(
        F.data.startswith("offer:")
        & ~F.data.startswith("offer:buy:")
        & ~F.data.startswith("offer:confirm:")
    )
    async def cb_offer(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[1])
        offer = offer_by_id(callback.from_user.id, offer_id)
        if not offer:
            await present(
                callback.message,
                "Предложение больше недоступно.",
                result_actions("menu:offers", "← Закупки"),
                edit=True,
            )
            return
        await present(callback.message, offer_text(offer), offer_actions(offer_id), edit=True)

    @router.callback_query(F.data.startswith("offer:confirm:"))
    async def cb_offer_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[2])
        offer = offer_by_id(callback.from_user.id, offer_id)
        if not offer:
            await present(
                callback.message,
                "Предложение больше недоступно.",
                result_actions("menu:offers", "← Закупки"),
                edit=True,
            )
            return
        await present(callback.message, offer_text(offer, confirmation=True), offer_confirm(offer_id), edit=True)

    @router.callback_query(F.data.startswith("offer:buy:"))
    async def cb_offer_buy(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[2])
        result = game.buy_offer(callback.from_user.id, offer_id)
        await present(
            callback.message,
            f"<b>📦 Закупка</b>\n\n{result}",
            result_actions("menu:offers", "← Закупки"),
            edit=True,
        )

    @router.callback_query(F.data == "listings:list")
    async def cb_listings_legacy(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_listings(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("listing:") & ~F.data.startswith("listing:price:"))
    async def cb_listing(callback: CallbackQuery) -> None:
        await callback.answer()
        listing_id = int(callback.data.split(":")[1])
        await render_listing_detail(callback.message, callback.from_user.id, listing_id)

    @router.callback_query(F.data.startswith("listing:price:"))
    async def cb_listing_price(callback: CallbackQuery) -> None:
        _, _, listing_id, percent = callback.data.split(":")
        result = game.change_listing_price(callback.from_user.id, int(listing_id), int(percent))
        await callback.answer(result)
        await render_listing_detail(callback.message, callback.from_user.id, int(listing_id))

    return router
