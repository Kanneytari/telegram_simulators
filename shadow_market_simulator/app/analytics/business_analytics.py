from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from .db import Database
from .simulation import parse_dt, utcnow


PERIOD_DAYS = {"7": 7, "30": 30}
PERIOD_LABELS = {"7": "7 дней", "30": "30 дней"}


def normalize_period(period: str | None) -> str:
    return period if period in PERIOD_DAYS else "7"


def period_label(period: str | None) -> str:
    return PERIOD_LABELS[normalize_period(period)]


def _money(value: int | float) -> str:
    return f"{int(round(value or 0)):,} ₽"


def _signed_money(value: int | float) -> str:
    number = int(round(value or 0))
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,} ₽"


def _window(period: str, now: datetime | None = None) -> dict:
    key = normalize_period(period)
    now = (now or utcnow()).astimezone(timezone.utc)
    span = timedelta(days=PERIOD_DAYS[key])
    return {
        "period": key,
        "days": PERIOD_DAYS[key],
        "current_start": now - span,
        "current_end": now,
        "previous_start": now - span * 2,
        "previous_end": now - span,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _range_sql(column: str) -> str:
    return f"datetime({column}) >= datetime(?) AND datetime({column}) < datetime(?)"


def _comparison_ready(shop, window: dict) -> bool:
    if not shop or not shop["created_at"]:
        return False
    return parse_dt(shop["created_at"]) <= window["previous_start"]


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def _trend(current: float, previous: float, *, neutral_pct: float = 5.0) -> tuple[str, str]:
    if current == previous == 0:
        return "→", ""
    if previous == 0:
        return ("↑", "с нуля") if current > 0 else ("↓", "")
    change = _pct_change(current, previous)
    if change is None:
        return "→", ""
    if abs(change) < neutral_pct:
        return "→", ""
    return ("↑", f"{abs(change):.0f}%") if change > 0 else ("↓", f"{abs(change):.0f}%")


def _money_with_trend(current: int, previous: int, ready: bool) -> str:
    base = f"<b>{_signed_money(current)}</b>"
    if not ready:
        return base + " · сравнение появится позже"
    if current == previous:
        return base + " →"
    if (current < 0 <= previous) or (previous < 0 <= current):
        arrow = "↑" if current > previous else "↓"
        return base + f" {arrow} было {_signed_money(previous)}"
    arrow, detail = _trend(float(current), float(previous))
    return base + f" {arrow}" + (f" {detail}" if detail else "")


def _count_with_trend(current: int, previous: int, ready: bool) -> str:
    if not ready:
        return f"<b>{current}</b> · сравнение появится позже"
    arrow, detail = _trend(float(current), float(previous))
    return f"<b>{current}</b> {arrow}" + (f" {detail}" if detail else "")


def _rating_with_trend(current: float, current_count: int, previous: float, previous_count: int, ready: bool) -> str:
    if current_count <= 0:
        return "пока нет оценок"
    base = f"<b>{current:.1f}/5</b>"
    if not ready or previous_count <= 0:
        return base
    delta = current - previous
    if abs(delta) < 0.15:
        return base + " →"
    return base + (" ↑" if delta > 0 else " ↓")


def _share_with_trend(current: float, current_n: int, previous: float, previous_n: int, ready: bool) -> str:
    if current_n <= 0:
        return "пока нет заказов"
    base = f"<b>{current * 100:.0f}%</b>"
    if not ready or previous_n <= 0:
        return base
    delta = current - previous
    if abs(delta) < 0.03:
        return base + " →"
    return base + (" ↑" if delta > 0 else " ↓")


def _order_metrics(conn, player_id: int, start: datetime, end: datetime) -> dict:
    params = (player_id, _iso(start), _iso(end))
    orders = conn.execute(
        f"""SELECT COUNT(*) orders,
                   COALESCE(SUM(quantity),0) units,
                   COALESCE(SUM(revenue),0) revenue,
                   COALESCE(SUM(cost),0) cogs,
                   COALESCE(SUM(employee_cost),0) retail_wages,
                   COALESCE(SUM(customer_was_repeat),0) repeats
            FROM orders
            WHERE player_id=? AND {_range_sql('created_at')}""",
        params,
    ).fetchone()
    ratings = conn.execute(
        f"""SELECT COUNT(*) n,
                   COALESCE(AVG(product_rating),0) product_rating,
                   COALESCE(AVG(courier_rating),0) courier_rating
            FROM order_ratings
            WHERE player_id=? AND {_range_sql('created_at')}""",
        params,
    ).fetchone()
    wholesale = int(conn.execute(
        f"""SELECT COALESCE(SUM(amount),0)
            FROM wholesale_delivery_payments
            WHERE player_id=? AND {_range_sql('created_at')}""",
        params,
    ).fetchone()[0])
    shop_refunds = int(conn.execute(
        f"""SELECT COALESCE(SUM(refund_amount),0)
            FROM disputes
            WHERE player_id=? AND refund_source='shop'
              AND resolved_at IS NOT NULL AND {_range_sql('resolved_at')}""",
        params,
    ).fetchone()[0])
    employee_losses = int(conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE amount END),0)
            FROM ledger
            WHERE player_id=? AND kind='employee_loss' AND {_range_sql('created_at')}""",
        params,
    ).fetchone()[0])
    investments = int(conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE amount END),0)
            FROM ledger
            WHERE player_id=? AND kind='staff_investment' AND {_range_sql('created_at')}""",
        params,
    ).fetchone()[0])

    revenue = int(orders["revenue"] or 0)
    cogs = int(orders["cogs"] or 0)
    retail_wages = int(orders["retail_wages"] or 0)
    earned = revenue - cogs - retail_wages - wholesale - shop_refunds - employee_losses
    count = int(orders["orders"] or 0)
    repeats = int(orders["repeats"] or 0)
    return {
        "orders": count,
        "units": int(orders["units"] or 0),
        "revenue": revenue,
        "cogs": cogs,
        "retail_wages": retail_wages,
        "wholesale_wages": wholesale,
        "team_cost": retail_wages + wholesale,
        "shop_refunds": shop_refunds,
        "employee_losses": employee_losses,
        "losses": shop_refunds + employee_losses,
        "investments": investments,
        "earned": earned,
        "repeats": repeats,
        "repeat_share": repeats / count if count else 0.0,
        "rating_count": int(ratings["n"] or 0),
        "product_rating": float(ratings["product_rating"] or 0.0),
        "courier_rating": float(ratings["courier_rating"] or 0.0),
    }


def _product_metrics(conn, player_id: int, start: datetime, end: datetime, days: int) -> list[dict]:
    params = (player_id, _iso(start), _iso(end))
    rows = conn.execute(
        f"""SELECT p.id, p.title,
                   COUNT(o.id) orders,
                   COALESCE(SUM(o.quantity),0) units,
                   COALESCE(SUM(o.revenue),0) revenue,
                   COALESCE(SUM(o.cost),0) cogs,
                   COALESCE(SUM(o.employee_cost),0) retail_wages,
                   COUNT(r.order_id) rating_count,
                   COALESCE(AVG(r.product_rating),0) rating
            FROM products p
            LEFT JOIN orders o
              ON o.product_id=p.id AND o.player_id=? AND {_range_sql('o.created_at')}
            LEFT JOIN order_ratings r ON r.order_id=o.id
            WHERE p.active=1
            GROUP BY p.id, p.title
            ORDER BY p.id""",
        params,
    ).fetchall()
    wholesale = {
        int(row["product_id"]): int(row["amount"] or 0)
        for row in conn.execute(
            f"""SELECT ra.product_id, COALESCE(SUM(w.amount),0) amount
                FROM wholesale_delivery_payments w
                JOIN retail_allocations ra ON ra.id=w.allocation_id
                WHERE w.player_id=? AND {_range_sql('w.created_at')}
                GROUP BY ra.product_id""",
            params,
        ).fetchall()
    }
    refunds = {
        int(row["product_id"]): int(row["amount"] or 0)
        for row in conn.execute(
            f"""SELECT o.product_id, COALESCE(SUM(d.refund_amount),0) amount
                FROM disputes d
                JOIN orders o ON o.id=d.order_id
                WHERE d.player_id=? AND d.refund_source='shop'
                  AND d.resolved_at IS NOT NULL AND {_range_sql('d.resolved_at')}
                GROUP BY o.product_id""",
            params,
        ).fetchall()
    }
    stocks = {
        int(row["product_id"]): int(row["units"] or 0)
        for row in conn.execute(
            """SELECT rp.product_id, COALESCE(SUM(rp.position_count * rp.pack_size),0) units
               FROM retail_positions rp
               JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.position_count>0
                 AND e.active=1 AND e.role='courier'
               GROUP BY rp.product_id""",
            (player_id,),
        ).fetchall()
    }

    result: list[dict] = []
    for row in rows:
        product_id = int(row["id"])
        units = int(row["units"] or 0)
        stock = stocks.get(product_id, 0)
        daily_sales = units / max(1, days)
        stock_days = stock / daily_sales if daily_sales > 0 else None
        earned = (
            int(row["revenue"] or 0)
            - int(row["cogs"] or 0)
            - int(row["retail_wages"] or 0)
            - wholesale.get(product_id, 0)
            - refunds.get(product_id, 0)
        )
        result.append({
            "id": product_id,
            "title": str(row["title"]),
            "orders": int(row["orders"] or 0),
            "units": units,
            "revenue": int(row["revenue"] or 0),
            "earned": earned,
            "rating_count": int(row["rating_count"] or 0),
            "rating": float(row["rating"] or 0.0),
            "stock": stock,
            "stock_days": stock_days,
        })
    return result


def _product_map(rows: list[dict]) -> dict[int, dict]:
    return {int(row["id"]): row for row in rows}


def _shop_snapshot(conn, player_id: int) -> dict:
    shop = conn.execute(
        "SELECT * FROM shops WHERE player_id=?",
        (player_id,),
    ).fetchone()
    trust = conn.execute(
        "SELECT trust_score FROM shop_trust_state WHERE player_id=?",
        (player_id,),
    ).fetchone()
    employees = conn.execute(
        """SELECT id, alias, role, stress, active, available
           FROM employees WHERE player_id=? ORDER BY id""",
        (player_id,),
    ).fetchall()
    accrued = int(conn.execute(
        "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=?",
        (player_id,),
    ).fetchone()[0])
    breakdowns = int(conn.execute(
        """SELECT COUNT(*) FROM inbox
           WHERE player_id=? AND kind='courier_problem'""",
        (player_id,),
    ).fetchone()[0])
    return {
        "shop": shop,
        "balance": int(shop["balance"] if shop else 0),
        "trust": float(trust["trust_score"] if trust else 64.0),
        "employees": list(employees),
        "accrued": accrued,
        "breakdowns": breakdowns,
    }


def _business_status(current: dict, previous: dict, ready: bool, team: dict) -> str:
    active_couriers = [e for e in team["employees"] if e["active"] and e["role"] == "courier"]
    if not active_couriers:
        return "🔴 Магазин не может нормально продавать"
    if current["orders"] <= 0:
        return "⚪ Продаж за период пока нет"
    if current["earned"] < 0:
        return "🔴 Магазин сейчас теряет деньги"
    if not ready:
        return "🟢 Магазин работает в плюс" if current["earned"] > 0 else "🟡 Продажи есть, но заработка почти нет"
    if previous["earned"] <= 0 < current["earned"]:
        return "🟢 Магазин вышел в плюс"
    earned_change = _pct_change(current["earned"], previous["earned"])
    order_change = _pct_change(current["orders"], previous["orders"])
    if order_change is not None and order_change > 10 and earned_change is not None and earned_change < -10:
        return "🟡 Продаж больше, но магазин зарабатывает меньше"
    if earned_change is not None and earned_change >= 10:
        return "🟢 Магазин растёт"
    if earned_change is not None and earned_change <= -15:
        return "🔴 Магазин зарабатывает хуже"
    if order_change is not None and order_change <= -20:
        return "🟡 Продажи заметно снизились"
    return "⚪ Существенных изменений нет"


def _team_summary(team: dict, current: dict, previous: dict, ready: bool) -> str:
    active = [e for e in team["employees"] if e["active"]]
    couriers = [e for e in active if e["role"] == "courier"]
    if not active:
        return "🔴 Нет сотрудников."
    if not couriers:
        return "🔴 Нет розничных сотрудников — продажи остановлены."
    critical = [e for e in active if float(e["stress"]) >= 78]
    tense = [e for e in active if 52 <= float(e["stress"]) < 78]
    if critical:
        return f"🔴 {len(critical)} сотрудник(а) на пределе."
    if tense:
        return f"🟡 {len(tense)} сотрудник(а) перегружены."
    if ready and current["rating_count"] >= 3 and previous["rating_count"] >= 3:
        if current["courier_rating"] <= previous["courier_rating"] - 0.35:
            return "🟡 Покупатели стали хуже оценивать работу закладчиков."
    return "🟢 Команда работает нормально."


def _product_concerns(current_products: list[dict], previous_products: list[dict], ready: bool) -> list[tuple[int, str]]:
    previous = _product_map(previous_products)
    concerns: list[tuple[int, str]] = []
    for row in current_products:
        title = escape(row["title"])
        prev = previous.get(row["id"], {"units": 0})
        if row["rating_count"] >= 3 and row["rating"] < 3.7:
            concerns.append((95, f"🔴 Покупатели плохо оценивают {title}: {row['rating']:.1f}/5."))
            continue
        if row["units"] > 0 and row["stock"] <= 0:
            concerns.append((90, f"🔴 {title} закончился на витрине — часть продаж может теряться."))
            continue
        if ready and prev["units"] >= 3 and row["units"] <= prev["units"] * 0.55:
            concerns.append((80, f"🟡 {title} продаётся заметно хуже прошлого периода."))
            continue
        if row["units"] > 0 and row["stock_days"] is not None and row["stock_days"] > 14:
            concerns.append((65, f"🟡 Запаса {title} слишком много относительно текущих продаж."))
            continue
        if row["units"] > 0 and row["stock_days"] is not None and row["stock_days"] < 2:
            concerns.append((60, f"🟡 {title} скоро закончится на витрине."))
    return concerns


def _overview_insights(current: dict, previous: dict, ready: bool, products: list[dict], prev_products: list[dict], team: dict) -> list[str]:
    candidates: list[tuple[int, str]] = []
    if current["employee_losses"] > 0:
        candidates.append((110, f"🔴 Из-за проблем с сотрудниками потеряно {_money(current['employee_losses'])}."))
    if current["shop_refunds"] > 0 and (
        current["shop_refunds"] >= 5_000
        or (current["revenue"] > 0 and current["shop_refunds"] / current["revenue"] >= 0.03)
    ):
        if ready and previous["shop_refunds"] > 0 and current["shop_refunds"] >= previous["shop_refunds"] * 1.7:
            candidates.append((105, f"🔴 Возвраты выросли почти вдвое или сильнее: {_money(current['shop_refunds'])}."))
        else:
            candidates.append((100, f"🔴 На возвратах потеряно {_money(current['shop_refunds'])}."))

    candidates.extend(_product_concerns(products, prev_products, ready))

    active = [e for e in team["employees"] if e["active"]]
    stressed = sorted(active, key=lambda e: float(e["stress"]), reverse=True)
    if stressed and float(stressed[0]["stress"]) >= 78:
        candidates.append((85, f"🔴 {escape(str(stressed[0]['alias']))} работает на пределе — риск ошибок и срыва выше."))
    elif stressed and float(stressed[0]["stress"]) >= 52:
        candidates.append((70, f"🟡 У {escape(str(stressed[0]['alias']))} высокий стресс; стоит проверить нагрузку."))

    if ready and current["rating_count"] >= 3 and previous["rating_count"] >= 3:
        if current["courier_rating"] <= previous["courier_rating"] - 0.35:
            candidates.append((75, f"🟡 Оценка работы закладчиков снизилась до {current['courier_rating']:.1f}/5."))
        if current["product_rating"] <= previous["product_rating"] - 0.35:
            candidates.append((76, f"🟡 Покупатели стали хуже оценивать товар: {current['product_rating']:.1f}/5."))
    if ready and current["orders"] > 0 and previous["orders"] > 0:
        if current["repeat_share"] <= previous["repeat_share"] - 0.10:
            candidates.append((68, "🟡 Покупатели заметно реже возвращаются за повторной покупкой."))

    prev_map = _product_map(prev_products)
    positives: list[tuple[int, str]] = []
    for row in products:
        prev = prev_map.get(row["id"])
        if not ready or not prev or prev["units"] < 3 or row["units"] < 5 or row["earned"] <= 0:
            continue
        growth = _pct_change(row["units"], prev["units"])
        if growth is not None and growth >= 20:
            positives.append((45, f"🟢 {escape(row['title'])} продаётся заметно лучше прошлого периода."))
    if ready and current["earned"] > previous["earned"] and current["earned"] > 0:
        positives.append((42, "🟢 Магазин зарабатывает больше, чем в прошлом периоде."))
    if ready and current["repeat_share"] >= previous["repeat_share"] + 0.08 and current["orders"] >= 5:
        positives.append((40, "🟢 Покупатели стали заметно чаще возвращаться."))

    candidates.sort(key=lambda item: item[0], reverse=True)
    chosen = [text for _, text in candidates[:3]]
    if len(chosen) < 3:
        for _, text in sorted(positives, key=lambda item: item[0], reverse=True):
            if text not in chosen:
                chosen.append(text)
            if len(chosen) >= 3:
                break
    if not chosen:
        if current["orders"] <= 0:
            chosen.append("⚪ Продаж пока недостаточно, чтобы делать выводы.")
        else:
            chosen.append("🟢 Явных проблем за этот период не видно.")
    return chosen[:3]


def overview_text(db: Database, player_id: int, period: str = "7", now: datetime | None = None) -> str:
    window = _window(period, now)
    with db.connect() as conn:
        team = _shop_snapshot(conn, player_id)
        current = _order_metrics(conn, player_id, window["current_start"], window["current_end"])
        previous = _order_metrics(conn, player_id, window["previous_start"], window["previous_end"])
        current_products = _product_metrics(conn, player_id, window["current_start"], window["current_end"], window["days"])
        previous_products = _product_metrics(conn, player_id, window["previous_start"], window["previous_end"], window["days"])
    ready = _comparison_ready(team["shop"], window)
    status = _business_status(current, previous, ready, team)
    team_text = _team_summary(team, current, previous, ready)
    insights = _overview_insights(current, previous, ready, current_products, previous_products, team)
    insight_text = "\n".join(insights)

    return (
        f"<b>📊 Магазин · {period_label(period)}</b>\n\n"
        f"<b>{status}</b>\n"
        f"Заработано: {_money_with_trend(current['earned'], previous['earned'], ready)}\n"
        f"Заказов: {_count_with_trend(current['orders'], previous['orders'], ready)}\n"
        f"Баланс сейчас: <b>{_money(team['balance'])}</b>\n\n"
        f"<b>Покупатели</b>\n"
        f"Товар: {_rating_with_trend(current['product_rating'], current['rating_count'], previous['product_rating'], previous['rating_count'], ready)}\n"
        f"Закладчики: {_rating_with_trend(current['courier_rating'], current['rating_count'], previous['courier_rating'], previous['rating_count'], ready)}\n"
        f"Возвращаются: {_share_with_trend(current['repeat_share'], current['orders'], previous['repeat_share'], previous['orders'], ready)}\n"
        f"Доверие: <b>{team['trust']:.0f}/100</b>\n\n"
        f"<b>Команда</b>\n{team_text}\n\n"
        f"<b>На что обратить внимание</b>\n{insight_text}"
    )


def _stock_text(row: dict) -> str:
    if row["stock"] <= 0:
        return "товара на витрине нет"
    if row["units"] <= 0 or row["stock_days"] is None:
        return f"на витрине {row['stock']} ед., продаж пока нет"
    days = float(row["stock_days"])
    if days > 30:
        return "запаса больше чем на 30 дней"
    if days < 1:
        return "запаса меньше чем на день"
    return f"запаса примерно на {max(1, round(days))} дн."


def _product_block(row: dict, previous: dict | None, ready: bool, icon: str) -> str:
    if ready and previous is not None:
        arrow, detail = _trend(float(row["units"]), float(previous["units"]), neutral_pct=8.0)
        sales_trend = f" {arrow}" + (f" {detail}" if detail else "")
    else:
        sales_trend = ""
    rating = f"Оценка {row['rating']:.1f}/5" if row["rating_count"] else "Оценок пока нет"
    return (
        f"{icon} <b>{escape(row['title'])}</b>\n"
        f"{row['units']} шт.{sales_trend} · заработано <b>{_money(row['earned'])}</b>\n"
        f"{rating} · {_stock_text(row)}"
    )


def products_text(db: Database, player_id: int, period: str = "7", now: datetime | None = None) -> str:
    window = _window(period, now)
    with db.connect() as conn:
        shop = conn.execute("SELECT created_at FROM shops WHERE player_id=?", (player_id,)).fetchone()
        current = _product_metrics(conn, player_id, window["current_start"], window["current_end"], window["days"])
        previous = _product_metrics(conn, player_id, window["previous_start"], window["previous_end"], window["days"])
    ready = _comparison_ready(shop, window)
    prev_map = _product_map(previous)
    total_units = sum(row["units"] for row in current)
    total_earned = sum(row["earned"] for row in current)
    prev_units = sum(row["units"] for row in previous)
    prev_earned = sum(row["earned"] for row in previous)

    header_units = _count_with_trend(total_units, prev_units, ready)
    header_earned = _money_with_trend(total_earned, prev_earned, ready)

    if total_units <= 0:
        body = (
            "Пока нет продаж, поэтому рано делить товары на успешные и проблемные.\n"
            "После первых заказов здесь появятся лидеры, слабые позиции и оценка запаса."
        )
        return (
            f"<b>📦 Товары · {period_label(period)}</b>\n\n"
            f"Продано: {header_units} ед.\n"
            f"Заработано на товарах: {header_earned}\n\n"
            f"{body}"
        )

    concerns = _product_concerns(current, previous, ready)
    concern_ids: set[int] = set()
    for _, text in concerns:
        for row in current:
            if escape(row["title"]) in text:
                concern_ids.add(row["id"])

    good = [row for row in current if row["units"] > 0 and row["earned"] > 0 and row["id"] not in concern_ids]
    good.sort(key=lambda row: (row["earned"], row["units"]), reverse=True)
    if len(good) < 2:
        fallback = [row for row in current if row["units"] > 0 and row["earned"] > 0 and row not in good]
        fallback.sort(key=lambda row: (row["earned"], row["units"]), reverse=True)
        good.extend(fallback[: 2 - len(good)])
    good = good[:2]

    problem_rows: list[dict] = []
    for score, text in sorted(concerns, key=lambda item: item[0], reverse=True):
        for row in current:
            if escape(row["title"]) in text and row not in problem_rows:
                problem_rows.append(row)
                break
        if len(problem_rows) >= 3:
            break

    sections: list[str] = []
    if good:
        sections.append("<b>Хорошо идут</b>\n\n" + "\n\n".join(
            _product_block(row, prev_map.get(row["id"]), ready, "🟢") for row in good
        ))
    if problem_rows:
        sections.append("<b>Требуют внимания</b>\n\n" + "\n\n".join(
            _product_block(row, prev_map.get(row["id"]), ready, "🔴" if row["rating_count"] >= 3 and row["rating"] < 3.7 else "🟡")
            for row in problem_rows
        ))
    if not problem_rows:
        sections.append("<b>Требуют внимания</b>\n\n🟢 Явных проблем с товарами сейчас не видно.")

    return (
        f"<b>📦 Товары · {period_label(period)}</b>\n\n"
        f"Продано: {header_units} ед.\n"
        f"Заработано на товарах: {header_earned}\n\n"
        + "\n\n".join(sections)
    )


def finance_text(db: Database, player_id: int, period: str = "7", now: datetime | None = None) -> str:
    window = _window(period, now)
    with db.connect() as conn:
        team = _shop_snapshot(conn, player_id)
        current = _order_metrics(conn, player_id, window["current_start"], window["current_end"])
        previous = _order_metrics(conn, player_id, window["previous_start"], window["previous_end"])
    ready = _comparison_ready(team["shop"], window)

    losses: list[str] = []
    if current["shop_refunds"] > 0:
        losses.append(f"🔴 Возвраты покупателям: <b>{_money(current['shop_refunds'])}</b>")
    if current["employee_losses"] > 0:
        losses.append(f"🔴 Потери из-за сотрудников: <b>{_money(current['employee_losses'])}</b>")
    if not losses:
        losses.append("🟢 Серьёзных денежных потерь за период нет.")

    return (
        f"<b>💰 Деньги · {period_label(period)}</b>\n\n"
        f"Продажи: <b>{_money(current['revenue'])}</b>\n\n"
        f"Товар обошёлся: −{_money(current['cogs'])}\n"
        f"Работа команды: −{_money(current['team_cost'])}\n"
        f"Возвраты и потери: −{_money(current['losses'])}\n\n"
        f"<b>Заработано:</b> {_money_with_trend(current['earned'], previous['earned'], ready)}\n\n"
        f"<b>Отдельно от торговли</b>\n"
        f"Вложено в развитие: <b>{_money(current['investments'])}</b>\n"
        f"Баланс сейчас: <b>{_money(team['balance'])}</b>\n"
        f"Нужно выплатить сотрудникам: <b>{_money(team['accrued'])}</b>\n\n"
        f"<b>Где теряем деньги</b>\n" + "\n".join(losses)
    )
