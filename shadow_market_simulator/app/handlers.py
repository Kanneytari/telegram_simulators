from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .db import Database
from .game import GameService, ROLE_NAMES
from .keyboards import (
    MAIN_MENU,
    candidate_actions,
    candidate_list,
    dispute_actions,
    employee_list,
    inbox_actions,
    inbox_list,
    listing_actions,
    listing_list,
    offer_actions,
    offer_list,
    recruitment_menu,
)
from .simulation import SimulationEngine


def build_router(db: Database, game: GameService, simulation: SimulationEngine, admin_ids: frozenset[int]) -> Router:
    router = Router()

    async def show_dashboard(message: Message) -> None:
        text = game.dashboard(message.from_user.id)
        await message.answer(text, reply_markup=MAIN_MENU)

    async def render_inbox(target: Message, player_id: int, edit: bool = False) -> None:
        items = game.inbox(player_id)
        text = "<b>Входящие</b>\n\n" + (f"Открытых сообщений: {len(items)}" if items else "Сейчас ничего не требует внимания.")
        if edit:
            await target.edit_text(text, reply_markup=inbox_list(items))
        else:
            await target.answer(text, reply_markup=inbox_list(items))

    async def render_team(target: Message, player_id: int, edit: bool = False) -> None:
        employees = game.employees(player_id)
        text = "<b>Команда</b>\n\nНажми на сотрудника, чтобы посмотреть накопленную статистику. Скрытых рейтингов надёжности игра не показывает."
        if edit:
            await target.edit_text(text, reply_markup=employee_list(employees))
        else:
            await target.answer(text, reply_markup=employee_list(employees))

    async def render_offers(target: Message, player_id: int, edit: bool = False) -> None:
        offers = game.offers(player_id)
        text = "<b>Закупки</b>\n\nКрупные партии дешевле на единицу, но сильнее замораживают оборотный капитал. Качество заранее известно только косвенно."
        if edit:
            await target.edit_text(text, reply_markup=offer_list(offers))
        else:
            await target.answer(text, reply_markup=offer_list(offers))

    async def render_listings(target: Message, player_id: int, edit: bool = False) -> None:
        listings = game.listings(player_id)
        text = "<b>Витрина</b>\n\nЦена влияет на спрос. Крупные упаковки дают больше выручки с заказа, но продаются медленнее."
        if edit:
            await target.edit_text(text, reply_markup=listing_list(listings))
        else:
            await target.answer(text, reply_markup=listing_list(listings))

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            await message.answer(
                "<b>NIGHTSHIFT</b>\n\nТы управляешь магазином на вымышленной теневой площадке. Мир работает в реальном времени: продажи, сотрудники и диспуты продолжаются, пока тебя нет.\n\nТвоя задача — удерживать ликвидность, рейтинг и команду, разбирая проблемы по данным, а не по готовым подсказкам.",
                reply_markup=MAIN_MENU,
            )
        await show_dashboard(message)

    @router.message(Command("tick"))
    async def debug_tick(message: Message) -> None:
        """Admin-only test helper: advance roughly six simulated hours immediately."""
        if message.from_user.id not in admin_ids:
            return
        from datetime import timedelta
        from .simulation import iso, utcnow
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (iso(utcnow() - timedelta(hours=6 / max(simulation.speed, 0.1))), message.from_user.id),
            )
        result = simulation.advance(message.from_user.id)
        await message.answer(
            f"Тестовый тик: {result.orders_created} заказов, {result.disputes_created} диспутов, {result.messages_created} сообщений."
        )

    @router.message(Command("reset"))
    async def reset(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        with db.connect() as conn:
            conn.execute("DELETE FROM shops WHERE player_id=?", (message.from_user.id,))
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await message.answer("Прогресс сброшен.", reply_markup=MAIN_MENU)
        await show_dashboard(message)

    @router.message(F.text == "🏠 Сводка")
    async def menu_dashboard(message: Message) -> None:
        await show_dashboard(message)

    @router.message(F.text == "📨 Входящие")
    async def menu_inbox(message: Message) -> None:
        await render_inbox(message, message.from_user.id)

    @router.message(F.text == "👥 Команда")
    async def menu_team(message: Message) -> None:
        await render_team(message, message.from_user.id)

    @router.message(F.text == "📦 Закупки")
    async def menu_offers(message: Message) -> None:
        await render_offers(message, message.from_user.id)

    @router.message(F.text == "🏷 Витрина")
    async def menu_listings(message: Message) -> None:
        await render_listings(message, message.from_user.id)

    @router.message(F.text == "📊 Аналитика")
    async def menu_analytics(message: Message) -> None:
        await message.answer(game.analytics(message.from_user.id))

    @router.callback_query(F.data == "inbox:list")
    async def cb_inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_inbox(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("inbox:item:"))
    async def cb_inbox_item(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await callback.message.edit_text("Сообщение уже неактуально.")
            return
        await callback.message.edit_text(f"<b>{item['title']}</b>\n\n{item['body']}", reply_markup=inbox_actions(item))

    @router.callback_query(F.data.startswith("inbox:dispute:"))
    async def cb_inbox_dispute(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item:
            return
        dispute_id = int(json.loads(item["payload_json"])["dispute_id"])
        text = game.dispute_details(callback.from_user.id, dispute_id)
        await callback.message.edit_text(text or "Диспут не найден.", reply_markup=dispute_actions(dispute_id))

    @router.callback_query(F.data.startswith("dispute:ask:"))
    async def cb_dispute_ask(callback: CallbackQuery) -> None:
        await callback.answer("Запрос отправлен")
        dispute_id = int(callback.data.split(":")[2])
        game.ask_employee_about_dispute(callback.from_user.id, dispute_id)
        text = game.dispute_details(callback.from_user.id, dispute_id)
        await callback.message.edit_text(text or "Диспут не найден.", reply_markup=dispute_actions(dispute_id))

    @router.callback_query(F.data.startswith("dispute:resolve:"))
    async def cb_dispute_resolve(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_id, decision = callback.data.split(":")
        result = game.resolve_dispute(callback.from_user.id, int(dispute_id), decision)
        await callback.message.edit_text(result)

    @router.callback_query(F.data.startswith("inbox:action:"))
    async def cb_inbox_action(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_id, action = callback.data.split(":")
        if action == "close":
            game.close_inbox(callback.from_user.id, int(item_id))
            result = "Сообщение закрыто."
        else:
            result = game.handle_inbox_action(callback.from_user.id, int(item_id), action)
        await callback.message.edit_text(result)

    @router.callback_query(F.data == "team:list")
    async def cb_team(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_team(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("employee:"))
    async def cb_employee(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        await callback.message.edit_text(text or "Сотрудник не найден.", reply_markup=employee_list([]))

    @router.callback_query(F.data == "candidates:list")
    async def cb_candidates(callback: CallbackQuery) -> None:
        await callback.answer()
        candidates = game.candidates(callback.from_user.id)
        await callback.message.edit_text("<b>Кандидаты</b>\n\nАнкета может быть неполной или неточной. Реальное качество сотрудника проявится только в статистике.", reply_markup=candidate_list(candidates))

    @router.callback_query(F.data.startswith("candidate:") & ~F.data.startswith("candidate:hire:") & ~F.data.startswith("candidate:reject:"))
    async def cb_candidate(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[1])
        with db.connect() as conn:
            c = conn.execute("SELECT * FROM candidates WHERE id=? AND player_id=?", (candidate_id, callback.from_user.id)).fetchone()
        if not c:
            await callback.message.edit_text("Кандидат недоступен.")
            return
        text = (
            f"<b>{c['alias']}</b>\n\n"
            f"Роль: {ROLE_NAMES.get(c['role'], c['role'])}\n"
            f"Желаемая ставка: {c['desired_pay']:,} ₽\n"
            f"Обеспечение: {c['deposit']:,} ₽\n"
            f"Автомобиль: {'да' if c['has_car'] else 'нет'}\n\n"
            f"Анкета: {c['summary']}"
        )
        await callback.message.edit_text(text, reply_markup=candidate_actions(candidate_id))

    @router.callback_query(F.data.startswith("candidate:hire:"))
    async def cb_candidate_hire(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        await callback.message.edit_text(game.hire_candidate(callback.from_user.id, candidate_id))

    @router.callback_query(F.data.startswith("candidate:reject:"))
    async def cb_candidate_reject(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        game.reject_candidate(callback.from_user.id, candidate_id)
        await callback.message.edit_text("Кандидату отказано.")

    @router.callback_query(F.data == "recruit:menu")
    async def cb_recruit_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.edit_text("<b>Поиск сотрудников</b>\n\nБолее дорогой канал повышает среднее качество входящего потока, но ничего не гарантирует.", reply_markup=recruitment_menu())

    @router.callback_query(F.data.startswith("recruit:run:"))
    async def cb_recruit_run(callback: CallbackQuery) -> None:
        await callback.answer()
        channel = callback.data.split(":")[2]
        await callback.message.edit_text(game.recruit(callback.from_user.id, channel))

    @router.callback_query(F.data == "offers:list")
    async def cb_offers(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_offers(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("offer:") & ~F.data.startswith("offer:buy:"))
    async def cb_offer(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[1])
        offers = {o["id"]: o for o in game.offers(callback.from_user.id)}
        o = offers.get(offer_id)
        if not o:
            await callback.message.edit_text("Предложение уже недоступно.")
            return
        total = o["quantity"] * o["unit_cost"]
        text = (
            f"<b>{o['supplier_title']}</b>\n\n"
            f"Товар: {o['product_title']}\n"
            f"Партия: {o['quantity']} ед.\n"
            f"Цена за ед.: {o['unit_cost']:,} ₽\n"
            f"Итого: <b>{total:,} ₽</b>\n"
            f"Репутационный сигнал по качеству: {o['quality_hint']}"
        )
        await callback.message.edit_text(text, reply_markup=offer_actions(offer_id))

    @router.callback_query(F.data.startswith("offer:buy:"))
    async def cb_offer_buy(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[2])
        await callback.message.edit_text(game.buy_offer(callback.from_user.id, offer_id))

    @router.callback_query(F.data == "listings:list")
    async def cb_listings(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_listings(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data.startswith("listing:") & ~F.data.startswith("listing:price:"))
    async def cb_listing(callback: CallbackQuery) -> None:
        await callback.answer()
        listing_id = int(callback.data.split(":")[1])
        rows = {r["id"]: r for r in game.listings(callback.from_user.id)}
        row = rows.get(listing_id)
        if not row:
            await callback.message.edit_text("Позиция не найдена.")
            return
        unit = row["price"] / row["pack_size"]
        market_delta = (unit / row["base_market_price"] - 1) * 100
        await callback.message.edit_text(
            f"<b>{row['title']} × {row['pack_size']}</b>\n\nЦена: {row['price']:,} ₽\nЦена за единицу: {unit:,.0f} ₽\nОтносительно рынка: {market_delta:+.1f}%\nДоступный остаток: {row['stock']} ед.",
            reply_markup=listing_actions(listing_id),
        )

    @router.callback_query(F.data.startswith("listing:price:"))
    async def cb_listing_price(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, listing_id, percent = callback.data.split(":")
        result = game.change_listing_price(callback.from_user.id, int(listing_id), int(percent))
        await callback.message.edit_text(result, reply_markup=listing_actions(int(listing_id)))

    return router
