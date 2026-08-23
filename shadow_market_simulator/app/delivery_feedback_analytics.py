from __future__ import annotations

import math
from html import escape

from .db import Database
from .detailed_analytics import normalize_period, period_label


DELIVERY_REVIEW_PAGE_SIZE = 5


def _period_clause(column: str, period: str) -> str:
    period = normalize_period(period)
    if period == "7":
        return f"datetime({column}) >= datetime('now','-7 day')"
    if period == "30":
        return f"datetime({column}) >= datetime('now','-30 day')"
    return "1=1"


def delivery_staff_rows(db: Database, player_id: int, period: str = "30"):
    period = normalize_period(period)
    review_filter = _period_clause("r.created_at", period)
    with db.connect() as conn:
        return conn.execute(
            f"""SELECT e.id, e.alias, e.active,
                       COUNT(r.id) review_count,
                       COALESCE(SUM(CASE WHEN r.delivery_sentiment='bad' THEN 1 ELSE 0 END),0) bad_delivery,
                       COALESCE(AVG(r.rating),0) review_avg,
                       COALESCE(AVG(CASE WHEN r.delivery_sentiment='bad' THEN r.rating END),0) bad_avg
                FROM employees e
                LEFT JOIN reviews r
                  ON r.employee_id=e.id
                 AND r.player_id=e.player_id
                 AND {review_filter}
                WHERE e.player_id=? AND e.role='courier'
                GROUP BY e.id, e.alias, e.active
                ORDER BY bad_delivery DESC, review_count DESC, e.active DESC, e.alias""",
            (player_id,),
        ).fetchall()


def delivery_staff_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    rows = delivery_staff_rows(db, player_id, period)
    lines = []
    total_reviews = 0
    total_bad = 0
    for row in rows:
        review_count = int(row["review_count"])
        bad = int(row["bad_delivery"])
        total_reviews += review_count
        total_bad += bad
        bad_rate = bad / review_count * 100.0 if review_count else 0.0
        inactive = " · ушёл" if not row["active"] else ""
        avg = f"⭐ {float(row['review_avg']):.2f}" if review_count else "нет отзывов"
        lines.append(
            f"<b>👤 {escape(str(row['alias']))}</b>{inactive}\n"
            f"Негатив по доставке: <b>{bad}</b> из {review_count} ({bad_rate:.1f}%)\n"
            f"Средняя оценка: {avg}"
        )

    total_rate = total_bad / total_reviews * 100.0 if total_reviews else 0.0
    return (
        f"<b>🚩 Негатив по доставке · {period_label(period)}</b>\n\n"
        f"Всего негативных отзывов: <b>{total_bad}</b> из {total_reviews} ({total_rate:.1f}%)\n\n"
        + ("\n\n".join(lines) if lines else "Розничных сотрудников нет.")
        + "\n\n<i>Открой сотрудника кнопкой ниже, чтобы посмотреть тексты негативных отзывов.</i>"
    )


def employee_delivery_reviews_text(
    db: Database,
    player_id: int,
    employee_id: int,
    period: str = "30",
    page: int = 0,
    page_size: int = DELIVERY_REVIEW_PAGE_SIZE,
) -> tuple[str, int, int]:
    period = normalize_period(period)
    page_size = max(1, int(page_size))
    review_filter = _period_clause("r.created_at", period)

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id, alias, active FROM employees WHERE id=? AND player_id=? AND role='courier'",
            (employee_id, player_id),
        ).fetchone()
        if not employee:
            return "Сотрудник не найден.", 1, 0

        total = int(conn.execute(
            f"""SELECT COUNT(*)
                FROM reviews r
                WHERE r.player_id=? AND r.employee_id=?
                  AND r.delivery_sentiment='bad' AND {review_filter}""",
            (player_id, employee_id),
        ).fetchone()[0])
        pages = max(1, int(math.ceil(total / page_size)))
        page = max(0, min(int(page), pages - 1))
        rows = conn.execute(
            f"""SELECT r.id, r.rating, r.text, r.created_at,
                       r.quality_sentiment, p.title product_title,
                       o.id order_id, o.quantity, o.revenue
                FROM reviews r
                JOIN products p ON p.id=r.product_id
                JOIN orders o ON o.id=r.order_id
                WHERE r.player_id=? AND r.employee_id=?
                  AND r.delivery_sentiment='bad' AND {review_filter}
                ORDER BY datetime(r.created_at) DESC, r.id DESC
                LIMIT ? OFFSET ?""",
            (player_id, employee_id, page_size, page * page_size),
        ).fetchall()

    inactive = " · ушёл" if not employee["active"] else ""
    header = (
        f"<b>🚩 {escape(str(employee['alias']))}{inactive}</b>\n"
        f"Негатив по доставке · {period_label(period)}\n"
        f"Всего: <b>{total}</b> · страница {page + 1}/{pages}"
    )
    if not rows:
        return header + "\n\nНегативных отзывов за выбранный период нет.", pages, page

    blocks = []
    for row in rows:
        date = str(row["created_at"])[:10]
        stars = "★" * int(row["rating"]) + "☆" * (5 - int(row["rating"]))
        blocks.append(
            f"<b>{escape(str(row['product_title']))}</b> · {date}\n"
            f"{stars} · заказ #{row['order_id']} · {row['quantity']} ед. · {int(row['revenue']):,} ₽\n"
            f"{escape(str(row['text']))}"
        )

    return header + "\n\n" + "\n\n".join(blocks), pages, page
