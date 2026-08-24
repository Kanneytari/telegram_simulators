from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from .customer_trust import premium_allowance, trust_band
from .db import Database


PERIOD_LABELS = {"7": "7 дней", "30": "30 дней", "all": "всё время"}

LEDGER_LABELS = {
    "capital": "Стартовый капитал / пополнения",
    "sale": "Продажи",
    "procurement": "Закупки",
    "salary": "Выплаты сотрудникам",
    "refund": "Компенсации клиентам",
    "refund_employee_deposit": "Компенсации из депозитов",
    "deposit_in": "Полученные депозиты",
    "deposit_return": "Возврат депозитов",
    "deposit_forfeit": "Удержанные депозиты",
    "recruitment": "Найм",
}


def normalize_period(period: str | None) -> str:
    return period if period in PERIOD_LABELS else "30"


def period_label(period: str | None) -> str:
    return PERIOD_LABELS[normalize_period(period)]


def _clause(column: str, period: str | None) -> str:
    period = normalize_period(period)
    if period == "7":
        return f"datetime({column}) >= datetime('now','-7 day')"
    if period == "30":
        return f"datetime({column}) >= datetime('now','-30 day')"
    return "1=1"


def _money(value) -> str:
    return f"{int(value or 0):,} ₽"


def _trust_snapshot(conn, player_id: int) -> dict:
    state = conn.execute(
        "SELECT * FROM shop_trust_state WHERE player_id=?", (player_id,)
    ).fetchone()
    ratings = conn.execute(
        """SELECT COUNT(*) n, COALESCE(AVG(product_rating),0) product,
                  COALESCE(AVG(courier_rating),0) courier
           FROM order_ratings WHERE player_id=?""",
        (player_id,),
    ).fetchone()
    clients = conn.execute(
        """SELECT COUNT(*) total,
                  SUM(CASE WHEN purchases>=1 THEN 1 ELSE 0 END) buyers,
                  SUM(CASE WHEN purchases>=2 THEN 1 ELSE 0 END) repeat_clients,
                  SUM(CASE WHEN purchases>=4 AND trust>=0.72 THEN 1 ELSE 0 END) regulars,
                  COALESCE(AVG(CASE WHEN purchases>0 THEN lifetime_value END),0) avg_ltv
           FROM client_relationships WHERE player_id=?""",
        (player_id,),
    ).fetchone()
    buyers = int(clients["buyers"] or 0)
    regulars = int(clients["regulars"] or 0)
    trust = float(state["trust_score"] if state else 64.0)
    regular_share = regulars / buyers if buyers else 0.0
    return {
        "trust": trust,
        "availability": float(state["availability_ema"] if state else 0.60),
        "fairness": float(state["fairness_ema"] if state else 0.65),
        "rating_count": int(ratings["n"] or 0),
        "product_rating": float(ratings["product"] or 0.0),
        "courier_rating": float(ratings["courier"] or 0.0),
        "buyers": buyers,
        "repeat_clients": int(clients["repeat_clients"] or 0),
        "regulars": regulars,
        "avg_ltv": float(clients["avg_ltv"] or 0),
        "premium": premium_allowance(trust, regular_share),
    }


def overview_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        shop = conn.execute("SELECT balance FROM shops WHERE player_id=?", (player_id,)).fetchone()
        orders = conn.execute(
            f"""SELECT COUNT(*) orders, COALESCE(SUM(quantity),0) units,
                       COALESCE(SUM(revenue),0) revenue, COALESCE(SUM(cost),0) cogs,
                       COALESCE(SUM(employee_cost),0) retail_wages,
                       COALESCE(SUM(customer_was_repeat),0) repeat_orders
                FROM orders WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        wholesale = int(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM wholesale_delivery_payments WHERE player_id=? AND {_clause('created_at', period)}",
            (player_id,),
        ).fetchone()[0])
        ratings = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(AVG(product_rating),0) product,
                       COALESCE(AVG(courier_rating),0) courier
                FROM order_ratings WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        disputes = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(refund_amount),0) refunds
                FROM disputes WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        trust = _trust_snapshot(conn, player_id)
        accrued = int(conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])

    revenue = int(orders["revenue"])
    contribution = revenue - int(orders["cogs"]) - int(orders["retail_wages"]) - wholesale
    repeat_share = int(orders["repeat_orders"] or 0) / int(orders["orders"] or 1) * 100 if orders["orders"] else 0.0
    rating_text = (
        f"Качество товара: {float(ratings['product']):.2f}/5\nРабота курьеров: {float(ratings['courier']):.2f}/5"
        if ratings["n"] else "Покупательских оценок за период пока нет."
    )
    return (
        f"<b>📈 Сводка · {period_label(period)}</b>\n\n"
        f"Заказов: <b>{orders['orders']}</b> · {orders['units']} ед.\n"
        f"Выручка: <b>{_money(revenue)}</b>\n"
        f"Вклад после себестоимости и комиссий: <b>{_money(contribution)}</b>\n"
        f"Повторных заказов: {orders['repeat_orders']} ({repeat_share:.1f}%)\n\n"
        f"<b>Покупательские оценки</b>\n{rating_text}\n\n"
        f"<b>Долгосрочный прогресс</b>\n"
        f"Доверие: <b>{trust['trust']:.0f}/100</b> · {trust_band(trust['trust'])}\n"
        f"Повторных покупателей: {trust['repeat_clients']}\n"
        f"Постоянных клиентов: <b>{trust['regulars']}</b>\n"
        f"Стабильность наличия: {trust['availability'] * 100:.0f}%\n"
        f"Допустимая премия к рынку: ~+{trust['premium'] * 100:.0f}%\n\n"
        f"Диспутов: {disputes['n']} · компенсации {_money(disputes['refunds'])}\n"
        f"Начислено сотрудникам сейчас: {_money(accrued)}\n"
        f"Текущий баланс: <b>{_money(shop['balance'])}</b>"
    )


def daily_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT date(created_at) day, COUNT(*) orders,
                       COALESCE(SUM(revenue),0) revenue,
                       COALESCE(SUM(customer_was_repeat),0) repeats
                FROM orders WHERE player_id=? AND {_clause('created_at', period)}
                GROUP BY date(created_at) ORDER BY day""",
            (player_id,),
        ).fetchall()
    by_day = {str(row["day"]): row for row in rows}
    today = datetime.now(timezone.utc).date()
    if period in {"7", "30"}:
        days = [str(today - timedelta(days=i)) for i in range(int(period) - 1, -1, -1)]
    else:
        days = list(by_day)[-30:]
    lines = []
    for day in days:
        row = by_day.get(day)
        if row:
            lines.append(
                f"{day[5:]} · {row['orders']} зак. · {_money(row['revenue'])} · повторн. {row['repeats']}"
            )
        else:
            lines.append(f"{day[5:]} · 0 зак. · 0 ₽")
    return (
        f"<b>📅 По дням · {period_label(period)}</b>\n"
        "Дата · заказы · выручка · повторные\n\n"
        + ("\n".join(lines) if lines else "Нет активности.")
    )


def products_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT p.id, p.title, COUNT(o.id) orders,
                       COALESCE(SUM(o.quantity),0) units,
                       COALESCE(SUM(o.revenue),0) revenue,
                       COALESCE(SUM(o.revenue-o.cost-o.employee_cost),0) contribution,
                       COALESCE(AVG(r.product_rating),0) quality,
                       COUNT(r.order_id) rating_count
                FROM products p
                LEFT JOIN orders o ON o.product_id=p.id AND o.player_id=? AND {_clause('o.created_at', period)}
                LEFT JOIN order_ratings r ON r.order_id=o.id
                WHERE p.active=1
                GROUP BY p.id, p.title ORDER BY revenue DESC, p.id""",
            (player_id,),
        ).fetchall()
        stocks = {
            int(row["product_id"]): int(row["units"] or 0)
            for row in conn.execute(
                """SELECT product_id, SUM(position_count*pack_size) units
                   FROM retail_positions WHERE player_id=? AND position_count>0 GROUP BY product_id""",
                (player_id,),
            ).fetchall()
        }
    blocks = []
    for row in rows:
        quality = f"🧪 {float(row['quality']):.2f}/5" if int(row["rating_count"]) else "🧪 —"
        blocks.append(
            f"<b>{escape(str(row['title']))}</b>\n"
            f"{row['orders']} зак. · {row['units']} ед. · {_money(row['revenue'])}\n"
            f"Вклад: {_money(row['contribution'])} · {quality}\n"
            f"На витрине сейчас: {stocks.get(int(row['id']), 0)} ед."
        )
    return f"<b>📦 По товарам · {period_label(period)}</b>\n\n" + "\n\n".join(blocks)


def finance_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        sales = conn.execute(
            f"""SELECT COALESCE(SUM(revenue),0) revenue, COALESCE(SUM(cost),0) cogs,
                       COALESCE(SUM(employee_cost),0) retail_wages
                FROM orders WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        wholesale = int(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM wholesale_delivery_payments WHERE player_id=? AND {_clause('created_at', period)}",
            (player_id,),
        ).fetchone()[0])
        payroll = conn.execute(
            f"""SELECT COALESCE(SUM(gross_wages),0) gross, COALESCE(SUM(cash_paid),0) cash,
                       COALESCE(SUM(deposit_added),0) deposit
                FROM payroll_runs WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        ledger = conn.execute(
            f"""SELECT kind, COALESCE(SUM(amount),0) amount FROM ledger
                WHERE player_id=? AND {_clause('created_at', period)}
                GROUP BY kind ORDER BY ABS(SUM(amount)) DESC""",
            (player_id,),
        ).fetchall()
    contribution = int(sales["revenue"]) - int(sales["cogs"]) - int(sales["retail_wages"]) - wholesale
    lines = [f"{LEDGER_LABELS.get(str(row['kind']), str(row['kind']))}: {_money(row['amount'])}" for row in ledger[:12]]
    return (
        f"<b>💰 Финансы · {period_label(period)}</b>\n\n"
        f"Выручка: {_money(sales['revenue'])}\n"
        f"Себестоимость: {_money(sales['cogs'])}\n"
        f"Комиссии розницы: {_money(sales['retail_wages'])}\n"
        f"Комиссии опта: {_money(wholesale)}\n"
        f"Вклад до прочих расходов: <b>{_money(contribution)}</b>\n\n"
        f"Фактически выплачено деньгами: {_money(payroll['cash'])}\n"
        f"Переведено в депозиты: {_money(payroll['deposit'])}\n\n"
        "<b>Движения денег</b>\n" + ("\n".join(lines) if lines else "Нет операций.")
    )


def staff_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT e.id, e.alias, e.role, e.active,
                       COUNT(o.id) orders, COALESCE(SUM(o.revenue),0) revenue,
                       COALESCE(SUM(o.employee_cost),0) retail_earned,
                       COALESCE(AVG(r.courier_rating),0) courier_rating,
                       COUNT(r.order_id) rating_count,
                       COALESCE(w.wholesale_earned,0) wholesale_earned
                FROM employees e
                LEFT JOIN orders o ON o.employee_id=e.id AND o.player_id=e.player_id AND {_clause('o.created_at', period)}
                LEFT JOIN order_ratings r ON r.order_id=o.id
                LEFT JOIN (
                    SELECT employee_id, SUM(amount) wholesale_earned
                    FROM wholesale_delivery_payments
                    WHERE player_id=? AND {_clause('created_at', period)} GROUP BY employee_id
                ) w ON w.employee_id=e.id
                WHERE e.player_id=?
                GROUP BY e.id, e.alias, e.role, e.active, w.wholesale_earned
                ORDER BY e.active DESC, e.role, e.alias""",
            (player_id, player_id),
        ).fetchall()
    blocks = []
    for row in rows:
        status = "" if row["active"] else " · ушёл"
        if row["role"] == "courier":
            rating = f" · 👤 {float(row['courier_rating']):.2f}/5" if int(row["rating_count"]) else ""
            blocks.append(
                f"<b>{escape(str(row['alias']))}</b>{status}\n"
                f"Розница · {row['orders']} заказов · {_money(row['revenue'])}\n"
                f"Заработано: {_money(row['retail_earned'])}{rating}"
            )
        else:
            blocks.append(
                f"<b>{escape(str(row['alias']))}</b>{status}\n"
                f"Опт · заработано за передачи: {_money(row['wholesale_earned'])}"
            )
    return f"<b>👥 Сотрудники · {period_label(period)}</b>\n\n" + ("\n\n".join(blocks) if blocks else "Нет сотрудников.")


def quality_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        products = conn.execute(
            f"""SELECT p.title, COUNT(r.order_id) n, COALESCE(AVG(r.product_rating),0) rating
                FROM products p LEFT JOIN order_ratings r
                  ON r.product_id=p.id AND r.player_id=? AND {_clause('r.created_at', period)}
                WHERE p.active=1 GROUP BY p.id, p.title ORDER BY rating DESC, n DESC""",
            (player_id,),
        ).fetchall()
        suppliers = conn.execute(
            f"""SELECT s.title supplier, p.title product,
                       COUNT(DISTINCT o.batch_id) batches, COUNT(o.id) orders,
                       COALESCE(AVG(r.product_rating),0) rating
                FROM orders o
                JOIN batches b ON b.id=o.batch_id
                JOIN suppliers s ON s.id=b.supplier_id
                JOIN products p ON p.id=o.product_id
                LEFT JOIN order_ratings r ON r.order_id=o.id
                WHERE o.player_id=? AND {_clause('o.created_at', period)}
                GROUP BY s.id, s.title, p.id, p.title
                ORDER BY rating DESC, orders DESC LIMIT 16""",
            (player_id,),
        ).fetchall()
    p_lines = [
        f"{escape(str(row['title']))}: " + (f"<b>{float(row['rating']):.2f}/5</b> · {row['n']} оценок" if row["n"] else "нет данных")
        for row in products
    ]
    s_lines = [
        f"{escape(str(row['supplier']))} · {escape(str(row['product']))}: <b>{float(row['rating']):.2f}/5</b> · {row['orders']} покуп. · {row['batches']} парт."
        for row in suppliers if row["orders"]
    ]
    return (
        f"<b>🧪 Качество · {period_label(period)}</b>\n\n"
        "<b>По товарам</b>\n" + "\n".join(p_lines) +
        "\n\n<b>История поставщиков</b>\n" + ("\n".join(s_lines) if s_lines else "Истории продаж по поставщикам пока нет.") +
        "\n\n<i>Здесь учитывается только оценка качества товара. Работа курьеров в эти цифры не входит.</i>"
    )


def customers_text(db: Database, player_id: int, period: str = "30") -> str:
    period = normalize_period(period)
    with db.connect() as conn:
        snapshot = _trust_snapshot(conn, player_id)
        orders = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(customer_was_repeat),0) repeats,
                       COALESCE(SUM(revenue),0) revenue
                FROM orders WHERE player_id=? AND {_clause('created_at', period)}""",
            (player_id,),
        ).fetchone()
        top = conn.execute(
            """SELECT c.alias, cr.purchases, cr.lifetime_value, cr.trust
               FROM client_relationships cr JOIN clients c ON c.id=cr.client_id
               WHERE cr.player_id=? AND cr.purchases>0
               ORDER BY cr.purchases DESC, cr.trust DESC, cr.lifetime_value DESC LIMIT 8""",
            (player_id,),
        ).fetchall()
    repeat_share = int(orders["repeats"] or 0) / int(orders["n"] or 1) * 100 if orders["n"] else 0.0
    top_lines = [
        f"{escape(str(row['alias']))}: {row['purchases']} покупок · {_money(row['lifetime_value'])} · доверие {float(row['trust']) * 100:.0f}/100"
        for row in top
    ]
    return (
        f"<b>🤝 Клиенты · {period_label(period)}</b>\n\n"
        f"Доверие магазина: <b>{snapshot['trust']:.0f}/100</b> · {trust_band(snapshot['trust'])}\n"
        f"Повторных покупателей: {snapshot['repeat_clients']}\n"
        f"Постоянных клиентов: <b>{snapshot['regulars']}</b>\n"
        f"Повторных заказов за период: {orders['repeats']} ({repeat_share:.1f}%)\n"
        f"Средний LTV покупателя: {_money(snapshot['avg_ltv'])}\n"
        f"Стабильность наличия: {snapshot['availability'] * 100:.0f}%\n"
        f"Качество решений по клиентам: {snapshot['fairness'] * 100:.0f}%\n"
        f"Допустимая премия к рынку: <b>~+{snapshot['premium'] * 100:.0f}%</b>\n\n"
        "<b>Самые ценные отношения</b>\n" + ("\n".join(top_lines) if top_lines else "Постоянная база ещё не сформирована.")
    )


def section_text(db: Database, player_id: int, section: str, period: str = "30") -> str:
    renderers = {
        "overview": overview_text,
        "daily": daily_text,
        "products": products_text,
        "finance": finance_text,
        "staff": staff_text,
        "quality": quality_text,
        "customers": customers_text,
    }
    return renderers.get(section, overview_text)(db, player_id, normalize_period(period))
