from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


PAGE_SIZE = 5


def load_product_review_page(game, player_id: int, product_id: int, page: int, page_size: int = PAGE_SIZE) -> dict:
    page = max(0, int(page))
    page_size = max(1, int(page_size))
    with game.db.connect() as conn:
        product = conn.execute(
            "SELECT title FROM products WHERE id=? AND active=1",
            (product_id,),
        ).fetchone()
        total = int(conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE player_id=? AND product_id=?",
            (player_id, product_id),
        ).fetchone()[0])
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages - 1)
        rows = conn.execute(
            """SELECT r.*, p.title product_title, o.quantity,
                      c.alias client_alias, e.alias employee_alias
               FROM reviews r
               JOIN products p ON p.id=r.product_id
               JOIN orders o ON o.id=r.order_id
               JOIN clients c ON c.id=r.client_id
               JOIN employees e ON e.id=r.employee_id
               WHERE r.player_id=? AND r.product_id=?
               ORDER BY r.created_at DESC, r.id DESC
               LIMIT ? OFFSET ?""",
            (player_id, product_id, page_size, page * page_size),
        ).fetchall()
    return {
        "title": product["title"] if product else "Товар",
        "rows": rows,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "page_size": page_size,
    }


def _review_lines(reviews) -> str:
    if not reviews:
        return "Отзывов пока нет."
    blocks = []
    for row in reviews:
        date = str(row["created_at"])[:10]
        stars = "★" * int(row["rating"]) + "☆" * (5 - int(row["rating"]))
        head = f"{row['product_title']} × {row['quantity']} · {date} · {row['employee_alias']}"
        blocks.append(f"<b>{head}</b>\n{stars}\n{row['text']}")
    return "\n\n".join(blocks)


def _keyboard(product_id: int, page_data: dict) -> InlineKeyboardMarkup:
    page = int(page_data["page"])
    total_pages = int(page_data["total_pages"])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="← Новее",
            callback_data=f"store:reviews:{product_id}:{page-1}",
        ))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(
            text="Раньше →",
            callback_data=f"store:reviews:{product_id}:{page+1}",
        ))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="← Товар", callback_data=f"store:product:{product_id}")])
    rows.append([InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_product_review_router(game) -> Router:
    router = Router(name="product-review-pagination")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data.startswith("store:reviews:"))
    async def product_reviews(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        if len(parts) < 3 or not parts[2].isdigit():
            return
        product_id = int(parts[2])
        page = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
        data = load_product_review_page(game, callback.from_user.id, product_id, page)
        if data["total"]:
            start = data["page"] * data["page_size"] + 1
            end = start + len(data["rows"]) - 1
            counter = f"Отзывы {start}-{end} из {data['total']} · страница {data['page']+1}/{data['total_pages']}"
        else:
            counter = "Отзывов пока нет"
        text = (
            f"<b>⭐ Отзывы · {data['title']}</b>\n\n"
            f"{counter}\n\n"
            f"{_review_lines(data['rows'])}"
        )
        await present(callback.message, text, _keyboard(product_id, data))

    return router
