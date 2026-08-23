from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from .db import Database


PERIOD_LABELS = {
    "7": "7 дней",
    "30": "30 дней",
    "all": "всё время",
}


LEDGER_LABELS = {
    "capital": "Стартовый капитал / пополнения",
    "sale": "Продажи",
    "procurement": "Закупки",
    "salary": "Выплаты сотрудникам",
    "refund": "Компенсации клиентам",
    "refund_employee_deposit": "Компенсации из депозитов",
    "deposit_in": "Полученные депозиты сотрудников",
    "deposit_return": "Возврат депозитов сотрудникам",
    "deposit_forfeit": "Удержанные депозиты",
    "recruitment": "Найм и поиск сотрудников",
}


def normalize_period(period: str | None) -> str:
    return period if period in PERIOD_LABELS else "30"


def period_label(period: str | None) -> str:
    return PERIOD_LABELS[normalize_period(period)]


def _period_clause(column: str, period: str | None) -> str:
    period = normalize_period(period)
    if period == "7":
        return f"datetime({column}) >= datetime('now','-7 day')"
    if period == "30":
        return f"datetime({column}) >= datetime('now','-30 day')"
    return "1=1"


def _money(value) -> str:
    return f"{int(value or 0):,} ₽"


def overview_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("created_at", period)
    review_filter = _period_clause("created_at", period)
    dispute_filter = _period_clause("created_at", period)
    payroll_filter = _period_clause("created_at", period)
    wholesale_filter = _period_clause("created_at", period)
    ledger_filter = _period_clause("created_at", period)

    with db.connect() as conn:
        shop = conn.execute(
            "SELECT balance, rating FROM shops WHERE player_id=?",
            (player_id,),
        ).fetchone()
        orders = conn.execute(
            f"""SELECT COUNT(*) orders,
                       COALESCE(SUM(quantity),0) units,
                       COALESCE(SUM(revenue),0) revenue,
                       COALESCE(SUM(cost),0) cogs,
                       COALESCE(SUM(employee_cost),0) retail_wages
                FROM orders
                WHERE player_id=? AND {order_filter}""",
            (player_id,),
        ).fetchone()
        wholesale = conn.execute(
            f"""SELECT COUNT(*) deliveries, COALESCE(SUM(amount),0) wages
                FROM wholesale_delivery_payments
                WHERE player_id=? AND {wholesale_filter}""",
            (player_id,),
        ).fetchone()
        reviews = conn.execute(
            f"""SELECT COUNT(*) count, COALESCE(AVG(rating),0) avg
                FROM reviews
                WHERE player_id=? AND {review_filter}""",
            (player_id,),
        ).fetchone()
        disputes = conn.execute(
            f"""SELECT COUNT(*) count,
                       COALESCE(SUM(refund_amount),0) refunds
                FROM disputes
                WHERE player_id=? AND {dispute_filter}""",
            (player_id,),
        ).fetchone()
        payroll = conn.execute(
            f"""SELECT COALESCE(SUM(gross_wages),0) gross,
                       COALESCE(SUM(cash_paid),0) cash,
                       COALESCE(SUM(deposit_added),0) deposit
                FROM payroll_runs
                WHERE player_id=? AND {payroll_filter}""",
            (player_id,),
        ).fetchone()
        cashflow = conn.execute(
            f"""SELECT COALESCE(SUM(CASE WHEN kind!='capital' THEN amount ELSE 0 END),0) business,
                       COALESCE(SUM(CASE WHEN amount>0 AND kind!='capital' THEN amount ELSE 0 END),0) inflow,
                       COALESCE(SUM(CASE WHEN amount<0 AND kind!='capital' THEN -amount ELSE 0 END),0) outflow
                FROM ledger
                WHERE player_id=? AND {ledger_filter}""",
            (player_id,),
        ).fetchone()
        accrued = int(conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])

    revenue = int(orders["revenue"])
    cogs = int(orders["cogs"])
    earned_wages = int(orders["retail_wages"]) + int(wholesale["wages"])
    contribution = revenue - cogs - earned_wages
    avg_check = revenue / int(orders["orders"]) if orders["orders"] else 0.0
    dispute_rate = int(disputes["count"]) / int(orders["orders"]) * 100.0 if orders["orders"] else 0.0

    return (
        f"<b>📈 Детальная статистика · {period_label(period)}</b>\n"
        "Период считается по реальному календарю.\n\n"
        "<b>Продажи</b>\n"
        f"Заказов: <b>{orders['orders']}</b> · единиц: {orders['units']}\n"
        f"Выручка: <b>{_money(revenue)}</b>\n"
        f"Средний чек: {_money(avg_check)}\n"
        f"Себестоимость проданного товара: {_money(cogs)}\n"
        f"Начислено сотрудникам за операции: {_money(earned_wages)}\n"
        f"Вклад до прочих расходов: <b>{_money(contribution)}</b>\n\n"
        "<b>Качество</b>\n"
        f"Отзывы: {reviews['count']} · ⭐ {float(reviews['avg']):.2f}\n"
        f"Диспуты: {disputes['count']} ({dispute_rate:.1f}% заказов)\n"
        f"Компенсации по диспутам: {_money(disputes['refunds'])}\n"
        f"Текущий рейтинг магазина: ⭐ {float(shop['rating']):.2f}\n\n"
        "<b>Деньги и персонал</b>\n"
        f"Выплачено сотрудникам деньгами: {_money(payroll['cash'])}\n"
        f"Переведено в депозиты из зарплаты: {_money(payroll['deposit'])}\n"
        f"Сейчас начислено к выплате: <b>{_money(accrued)}</b>\n"
        f"Денежные поступления по операциям: {_money(cashflow['inflow'])}\n"
        f"Денежные расходы по операциям: {_money(cashflow['outflow'])}\n"
        f"Чистый денежный поток без стартового капитала: <b>{_money(cashflow['business'])}</b>\n"
        f"Текущий баланс: <b>{_money(shop['balance'])}</b>"
    )


def daily_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("created_at", period)
    payroll_filter = _period_clause("created_at", period)
    with db.connect() as conn:
        sales_rows = conn.execute(
            f"""SELECT date(created_at) day,
                       COUNT(*) orders,
                       COALESCE(SUM(quantity),0) units,
                       COALESCE(SUM(revenue),0) revenue
                FROM orders
                WHERE player_id=? AND {order_filter}
                GROUP BY date(created_at)
                ORDER BY day""",
            (player_id,),
        ).fetchall()
        payroll_rows = conn.execute(
            f"""SELECT date(created_at) day,
                       COALESCE(SUM(cash_paid),0) cash
                FROM payroll_runs
                WHERE player_id=? AND {payroll_filter}
                GROUP BY date(created_at)""",
            (player_id,),
        ).fetchall()

    sales = {str(row["day"]): row for row in sales_rows}
    payroll = {str(row["day"]): int(row["cash"]) for row in payroll_rows}
    days: list[str] = []
    today = datetime.now(timezone.utc).date()
    if period in {"7", "30"}:
        count = int(period)
        for offset in range(count - 1, -1, -1):
            days.append(str(today - timedelta(days=offset)))
    else:
        active = sorted(set(sales) | set(payroll))
        days = active[-30:]

    lines = []
    for day in days:
        row = sales.get(day)
        orders = int(row["orders"]) if row else 0
        revenue = int(row["revenue"]) if row else 0
        wages = payroll.get(day, 0)
        short = day[5:]
        lines.append(f"{short} · {orders} зак. · {_money(revenue)} · выпл. {_money(wages)}")

    if not lines:
        lines.append("За выбранный период операций нет.")
    suffix = "\n\nДля периода «всё время» показаны последние 30 дней с активностью." if period == "all" and len(days) >= 30 else ""
    return (
        f"<b>📅 Динамика по дням · {period_label(period)}</b>\n"
        "Дата · заказы · выручка · фактические выплаты\n\n"
        + "\n".join(lines)
        + suffix
    )


def products_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("o.created_at", period)
    review_filter = _period_clause("r.created_at", period)
    dispute_filter = _period_clause("d.created_at", period)

    with db.connect() as conn:
        products = conn.execute(
            f"""SELECT p.id, p.title,
                       COALESCE(s.orders,0) orders,
                       COALESCE(s.units,0) units,
                       COALESCE(s.revenue,0) revenue,
                       COALESCE(s.cogs,0) cogs,
                       COALESCE(s.retail_wages,0) retail_wages,
                       COALESCE(rv.review_count,0) review_count,
                       COALESCE(rv.review_avg,0) review_avg,
                       COALESCE(dp.disputes,0) disputes,
                       COALESCE(stock.units,0) stock_units
                FROM products p
                LEFT JOIN (
                    SELECT o.product_id, COUNT(*) orders, SUM(o.quantity) units,
                           SUM(o.revenue) revenue, SUM(o.cost) cogs,
                           SUM(o.employee_cost) retail_wages
                    FROM orders o
                    WHERE o.player_id=? AND {order_filter}
                    GROUP BY o.product_id
                ) s ON s.product_id=p.id
                LEFT JOIN (
                    SELECT r.product_id, COUNT(*) review_count, AVG(r.rating) review_avg
                    FROM reviews r
                    WHERE r.player_id=? AND {review_filter}
                    GROUP BY r.product_id
                ) rv ON rv.product_id=p.id
                LEFT JOIN (
                    SELECT o.product_id, COUNT(*) disputes
                    FROM disputes d JOIN orders o ON o.id=d.order_id
                    WHERE d.player_id=? AND {dispute_filter}
                    GROUP BY o.product_id
                ) dp ON dp.product_id=p.id
                LEFT JOIN (
                    SELECT product_id, SUM(units) units FROM (
                        SELECT product_id, SUM(remaining) units
                        FROM batches
                        WHERE player_id=? AND status IN ('receiving','warehouse') AND remaining>0
                        GROUP BY product_id
                        UNION ALL
                        SELECT product_id, SUM(quantity) units
                        FROM retail_allocations
                        WHERE player_id=? AND status IN ('waiting','preparing')
                        GROUP BY product_id
                        UNION ALL
                        SELECT product_id, SUM(position_count*pack_size) units
                        FROM retail_positions
                        WHERE player_id=? AND position_count>0
                        GROUP BY product_id
                    ) current_stock
                    GROUP BY product_id
                ) stock ON stock.product_id=p.id
                WHERE p.active=1
                ORDER BY revenue DESC, p.id""",
            (player_id, player_id, player_id, player_id, player_id, player_id),
        ).fetchall()

    lines = []
    for row in products:
        orders = int(row["orders"])
        revenue = int(row["revenue"])
        contribution = revenue - int(row["cogs"]) - int(row["retail_wages"])
        avg_check = revenue / orders if orders else 0
        dispute_rate = int(row["disputes"]) / orders * 100.0 if orders else 0.0
        rating = f"⭐ {float(row['review_avg']):.2f}" if int(row["review_count"]) else "нет отзывов"
        lines.append(
            f"<b>{escape(str(row['title']))}</b>\n"
            f"{orders} зак. · {row['units']} ед. · выручка {_money(revenue)}\n"
            f"Средний чек {_money(avg_check)} · вклад {_money(contribution)}\n"
            f"{rating} · диспуты {dispute_rate:.1f}% · сейчас в запасе {row['stock_units']} ед."
        )

    return (
        f"<b>📦 Товары · {period_label(period)}</b>\n\n"
        + ("\n\n".join(lines) if lines else "Нет данных по товарам.")
        + "\n\n<i>Вклад = выручка - себестоимость - розничные ставки. Оптовые выплаты и прочие расходы показаны отдельно в финансах.</i>"
    )


def finance_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("created_at", period)
    payroll_filter = _period_clause("created_at", period)
    wholesale_filter = _period_clause("created_at", period)
    ledger_filter = _period_clause("created_at", period)

    with db.connect() as conn:
        sales = conn.execute(
            f"""SELECT COALESCE(SUM(revenue),0) revenue,
                       COALESCE(SUM(cost),0) cogs,
                       COALESCE(SUM(employee_cost),0) retail_wages
                FROM orders WHERE player_id=? AND {order_filter}""",
            (player_id,),
        ).fetchone()
        wholesale_wages = int(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM wholesale_delivery_payments WHERE player_id=? AND {wholesale_filter}",
            (player_id,),
        ).fetchone()[0])
        payroll = conn.execute(
            f"""SELECT COALESCE(SUM(gross_wages),0) gross,
                       COALESCE(SUM(cash_paid),0) cash,
                       COALESCE(SUM(deposit_added),0) deposit
                FROM payroll_runs WHERE player_id=? AND {payroll_filter}""",
            (player_id,),
        ).fetchone()
        ledger = conn.execute(
            f"""SELECT kind, COALESCE(SUM(amount),0) amount
                FROM ledger
                WHERE player_id=? AND {ledger_filter}
                GROUP BY kind
                ORDER BY ABS(SUM(amount)) DESC, kind""",
            (player_id,),
        ).fetchall()

    earned = int(sales["retail_wages"]) + wholesale_wages
    contribution = int(sales["revenue"]) - int(sales["cogs"]) - earned
    business_cash = sum(int(row["amount"]) for row in ledger if row["kind"] != "capital")
    lines = []
    for row in ledger[:12]:
        amount = int(row["amount"])
        label = LEDGER_LABELS.get(str(row["kind"]), str(row["kind"]).replace("_", " ").capitalize())
        sign = "+" if amount > 0 else ""
        lines.append(f"{escape(label)}: <b>{sign}{amount:,} ₽</b>")

    return (
        f"<b>💰 Финансы · {period_label(period)}</b>\n\n"
        "<b>Экономика продаж</b>\n"
        f"Выручка: {_money(sales['revenue'])}\n"
        f"Себестоимость проданного товара: {_money(sales['cogs'])}\n"
        f"Начислено рознице за заказы: {_money(sales['retail_wages'])}\n"
        f"Начислено опту за передачи: {_money(wholesale_wages)}\n"
        f"Вклад до прочих расходов: <b>{_money(contribution)}</b>\n\n"
        "<b>Фактические выплаты</b>\n"
        f"Начислено в закрытых payroll: {_money(payroll['gross'])}\n"
        f"Выплачено деньгами: {_money(payroll['cash'])}\n"
        f"Переведено в депозиты: {_money(payroll['deposit'])}\n\n"
        "<b>Движение денег</b>\n"
        + ("\n".join(lines) if lines else "Движений за период нет.")
        + f"\n\nЧистый поток без стартового капитала: <b>{_money(business_cash)}</b>"
    )


def staff_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("o.created_at", period)
    review_filter = _period_clause("r.created_at", period)
    dispute_filter = _period_clause("d.created_at", period)
    wholesale_filter = _period_clause("w.created_at", period)
    salary_filter = _period_clause("l.created_at", period)

    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT e.id, e.alias, e.role, e.active, e.wages_accrued,
                       COALESCE(ro.orders,0) orders,
                       COALESCE(ro.revenue,0) revenue,
                       COALESCE(ro.earned,0) retail_earned,
                       COALESCE(rv.review_count,0) review_count,
                       COALESCE(rv.review_avg,0) review_avg,
                       COALESCE(dp.disputes,0) disputes,
                       COALESCE(wh.deliveries,0) deliveries,
                       COALESCE(wh.earned,0) wholesale_earned,
                       COALESCE(pay.cash_paid,0) cash_paid
                FROM employees e
                LEFT JOIN (
                    SELECT o.employee_id, COUNT(*) orders, SUM(o.revenue) revenue, SUM(o.employee_cost) earned
                    FROM orders o WHERE o.player_id=? AND {order_filter}
                    GROUP BY o.employee_id
                ) ro ON ro.employee_id=e.id
                LEFT JOIN (
                    SELECT r.employee_id, COUNT(*) review_count, AVG(r.rating) review_avg
                    FROM reviews r WHERE r.player_id=? AND {review_filter}
                    GROUP BY r.employee_id
                ) rv ON rv.employee_id=e.id
                LEFT JOIN (
                    SELECT o.employee_id, COUNT(*) disputes
                    FROM disputes d JOIN orders o ON o.id=d.order_id
                    WHERE d.player_id=? AND {dispute_filter}
                    GROUP BY o.employee_id
                ) dp ON dp.employee_id=e.id
                LEFT JOIN (
                    SELECT w.employee_id, COUNT(*) deliveries, SUM(w.amount) earned
                    FROM wholesale_delivery_payments w
                    WHERE w.player_id=? AND {wholesale_filter}
                    GROUP BY w.employee_id
                ) wh ON wh.employee_id=e.id
                LEFT JOIN (
                    SELECT l.reference_id employee_id, SUM(-l.amount) cash_paid
                    FROM ledger l
                    WHERE l.player_id=? AND l.kind='salary' AND {salary_filter}
                    GROUP BY l.reference_id
                ) pay ON pay.employee_id=e.id
                WHERE e.player_id=?
                ORDER BY e.active DESC, e.role, e.alias""",
            (player_id, player_id, player_id, player_id, player_id, player_id),
        ).fetchall()

    lines = []
    for row in rows:
        active = "" if row["active"] else " · ушёл"
        if row["role"] == "warehouse":
            lines.append(
                f"<b>🚚 {escape(str(row['alias']))}</b>{active}\n"
                f"Передач рознице: {row['deliveries']} · начислено {_money(row['wholesale_earned'])}\n"
                f"Выплачено деньгами: {_money(row['cash_paid'])} · сейчас к выплате {_money(row['wages_accrued'])}"
            )
        else:
            orders = int(row["orders"])
            dispute_rate = int(row["disputes"]) / orders * 100.0 if orders else 0.0
            rating = f"⭐ {float(row['review_avg']):.2f}" if int(row["review_count"]) else "нет отзывов"
            lines.append(
                f"<b>👤 {escape(str(row['alias']))}</b>{active}\n"
                f"Заказов: {orders} · выручка {_money(row['revenue'])} · начислено {_money(row['retail_earned'])}\n"
                f"{rating} · диспуты {dispute_rate:.1f}%\n"
                f"Выплачено деньгами: {_money(row['cash_paid'])} · сейчас к выплате {_money(row['wages_accrued'])}"
            )

    return (
        f"<b>👥 Сотрудники · {period_label(period)}</b>\n\n"
        + ("\n\n".join(lines) if lines else "Сотрудников нет.")
    )


def quality_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    order_filter = _period_clause("created_at", period)
    review_filter = _period_clause("created_at", period)
    dispute_filter = _period_clause("created_at", period)

    with db.connect() as conn:
        orders = int(conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE player_id=? AND {order_filter}",
            (player_id,),
        ).fetchone()[0])
        reviews = conn.execute(
            f"""SELECT COUNT(*) count, COALESCE(AVG(rating),0) avg,
                       COALESCE(SUM(CASE WHEN rating=5 THEN 1 ELSE 0 END),0) r5,
                       COALESCE(SUM(CASE WHEN rating=4 THEN 1 ELSE 0 END),0) r4,
                       COALESCE(SUM(CASE WHEN rating=3 THEN 1 ELSE 0 END),0) r3,
                       COALESCE(SUM(CASE WHEN rating=2 THEN 1 ELSE 0 END),0) r2,
                       COALESCE(SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END),0) r1,
                       COALESCE(SUM(CASE WHEN quality_sentiment='bad' THEN 1 ELSE 0 END),0) quality_bad,
                       COALESCE(SUM(CASE WHEN delivery_sentiment='bad' THEN 1 ELSE 0 END),0) delivery_bad
                FROM reviews WHERE player_id=? AND {review_filter}""",
            (player_id,),
        ).fetchone()
        disputes = conn.execute(
            f"""SELECT COUNT(*) count,
                       COALESCE(SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),0) open_count,
                       COALESCE(SUM(CASE WHEN decision='refund' THEN 1 ELSE 0 END),0) refund_count,
                       COALESCE(SUM(CASE WHEN decision='partial' THEN 1 ELSE 0 END),0) partial_count,
                       COALESCE(SUM(CASE WHEN decision='reject' THEN 1 ELSE 0 END),0) reject_count,
                       COALESCE(SUM(refund_amount),0) refunds,
                       COALESCE(SUM(CASE WHEN refund_source='shop' THEN refund_amount ELSE 0 END),0) shop_refunds,
                       COALESCE(SUM(CASE WHEN refund_source='employee' THEN refund_amount ELSE 0 END),0) employee_refunds
                FROM disputes WHERE player_id=? AND {dispute_filter}""",
            (player_id,),
        ).fetchone()
        shop = conn.execute("SELECT rating FROM shops WHERE player_id=?", (player_id,)).fetchone()

    dispute_rate = int(disputes["count"]) / orders * 100.0 if orders else 0.0
    return (
        f"<b>⭐ Качество и диспуты · {period_label(period)}</b>\n\n"
        "<b>Отзывы</b>\n"
        f"Всего: {reviews['count']} · средняя ⭐ {float(reviews['avg']):.2f}\n"
        f"5★ {reviews['r5']} · 4★ {reviews['r4']} · 3★ {reviews['r3']} · 2★ {reviews['r2']} · 1★ {reviews['r1']}\n"
        f"Негатив по качеству: {reviews['quality_bad']}\n"
        f"Негатив по исполнению: {reviews['delivery_bad']}\n\n"
        "<b>Диспуты</b>\n"
        f"Всего: {disputes['count']} ({dispute_rate:.1f}% заказов) · открыто сейчас: {disputes['open_count']}\n"
        f"Полный возврат: {disputes['refund_count']} · частичный: {disputes['partial_count']} · отказ: {disputes['reject_count']}\n"
        f"Компенсации: {_money(disputes['refunds'])}\n"
        f"За счёт магазина: {_money(disputes['shop_refunds'])}\n"
        f"Из депозитов сотрудников: {_money(disputes['employee_refunds'])}\n\n"
        f"Текущий рейтинг магазина: <b>⭐ {float(shop['rating']):.2f}</b>"
    )


def section_text(db: Database, player_id: int, section: str, period: str = "30") -> str:
    section = section if section in {"overview", "daily", "products", "finance", "staff", "quality"} else "overview"
    functions = {
        "overview": overview_text,
        "daily": daily_text,
        "products": products_text,
        "finance": finance_text,
        "staff": staff_text,
        "quality": quality_text,
    }
    return functions[section](db, player_id, normalize_period(period))
