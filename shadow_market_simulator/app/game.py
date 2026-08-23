from __future__ import annotations

import json
import random
from datetime import timedelta

from .db import Database
from .simulation import SimulationEngine, clamp, iso, utcnow


ROLE_NAMES = {
    "courier": "Розничный сотрудник",
    "warehouse": "Склад",
    "operator": "Оператор",
}


class GameService:
    def __init__(self, db: Database, simulation: SimulationEngine, rng: random.Random | None = None):
        self.db = db
        self.simulation = simulation
        self.rng = rng or random.Random()

    def dashboard(self, player_id: int) -> str:
        self.simulation.advance(player_id)
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id = ?", (player_id,)).fetchone()
            deposits = conn.execute(
                "SELECT COALESCE(SUM(deposit), 0) FROM employees WHERE player_id = ? AND active = 1", (player_id,)
            ).fetchone()[0]
            stock_cost = conn.execute(
                "SELECT COALESCE(SUM(remaining * unit_cost), 0) FROM batches WHERE player_id = ? AND status = 'warehouse'", (player_id,)
            ).fetchone()[0]
            open_inbox = conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id = ? AND status = 'open'", (player_id,)
            ).fetchone()[0]
            urgent = conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id = ? AND status = 'open' AND priority IN ('important', 'urgent')", (player_id,)
            ).fetchone()[0]
            employees = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id = ? AND active = 1", (player_id,)
            ).fetchone()[0]
            stock_units = conn.execute(
                "SELECT COALESCE(SUM(remaining), 0) FROM batches WHERE player_id = ? AND status = 'warehouse'", (player_id,)
            ).fetchone()[0]
            free_cash = int(shop["balance"]) - int(deposits) - int(shop["reserve_target"])
            return (
                f"<b>{shop['name']}</b>\n\n"
                f"Баланс: <b>{shop['balance']:,} ₽</b>\n"
                f"Свободные деньги: <b>{free_cash:,} ₽</b>\n"
                f"Товарный остаток: {stock_units} ед. / ~{stock_cost:,} ₽ по себестоимости\n"
                f"Рейтинг: <b>{shop['rating']:.2f}</b>\n"
                f"Сотрудников: {employees}\n"
                f"Открытых сообщений: {open_inbox}"
                + (f"\nТребуют внимания: <b>{urgent}</b>" if urgent else "")
            )

    def inbox(self, player_id: int, limit: int = 12):
        self.simulation.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT * FROM inbox WHERE player_id = ? AND status = 'open'
                   ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END, created_at
                   LIMIT ?""",
                (player_id, limit),
            ).fetchall()

    def inbox_item(self, player_id: int, item_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM inbox WHERE id = ? AND player_id = ?", (item_id, player_id)
            ).fetchone()

    def close_inbox(self, player_id: int, item_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE inbox SET status = 'closed' WHERE id = ? AND player_id = ?", (item_id, player_id)
            )

    def dispute_details(self, player_id: int, dispute_id: int) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.revenue, o.quantity, o.quality, o.batch_id,
                          c.alias client_alias, c.account_age_days, c.marketplace_orders, c.shop_orders,
                          c.total_spend, c.disputes_total, c.disputes_won,
                          e.alias employee_alias, e.jobs_done, e.disputes employee_disputes, e.losses,
                          e.deposit, e.joined_at,
                          p.title product_title
                   FROM disputes d
                   JOIN orders o ON o.id = d.order_id
                   JOIN clients c ON c.id = o.client_id
                   JOIN employees e ON e.id = o.employee_id
                   JOIN products p ON p.id = o.product_id
                   WHERE d.id = ? AND d.player_id = ?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row:
                return None
            evidence = json.loads(row["evidence_json"])
            employee_rate = (row["employee_disputes"] / row["jobs_done"] * 100.0) if row["jobs_done"] else 0.0
            client_avg = row["total_spend"] / row["shop_orders"] if row["shop_orders"] else 0
            batch = conn.execute(
                """SELECT b.*, s.title supplier_title,
                   (SELECT COUNT(*) FROM orders o2 WHERE o2.batch_id=b.id) orders_count,
                   (SELECT COUNT(*) FROM disputes d2 JOIN orders o2 ON o2.id=d2.order_id WHERE o2.batch_id=b.id) disputed_count
                   FROM batches b JOIN suppliers s ON s.id=b.supplier_id WHERE b.id=?""",
                (row["batch_id"],),
            ).fetchone()
            batch_rate = (batch["disputed_count"] / batch["orders_count"] * 100.0) if batch["orders_count"] else 0.0
            extra = f"\n\n<b>Ответ сотрудника</b>\n{row['courier_reply']}" if row["courier_reply"] else ""
            return (
                f"<b>Диспут #{row['id']}</b> · заказ {row['revenue']:,} ₽\n"
                f"{row['message']}\n\n"
                f"<b>Клиент {row['client_alias']}</b>\n"
                f"Аккаунту: {row['account_age_days']} дн.\n"
                f"Покупок на площадке: {row['marketplace_orders']}\n"
                f"У нас: {row['shop_orders']} · {row['total_spend']:,} ₽\n"
                f"Средний чек у нас: {client_avg:,.0f} ₽\n"
                f"Диспутов: {row['disputes_total']} · выиграно {row['disputes_won']}\n\n"
                f"<b>Сотрудник {row['employee_alias']}</b>\n"
                f"Заказов: {row['jobs_done']}\n"
                f"Диспуты: {row['employee_disputes']} ({employee_rate:.1f}%)\n"
                f"Обеспечение: {row['deposit']:,} ₽\n\n"
                f"<b>Заказ</b>\n"
                f"Товар: {row['product_title']} × {row['quantity']}\n"
                f"Описание: {'есть' if evidence.get('description_present') else 'нет'}\n"
                f"Доп. материал: {'есть' if evidence.get('extra_material_present') else 'нет'}\n"
                f"Партия #{row['batch_id']}: качество по внутренней оценке {row['quality']:.0f}/100\n"
                f"Диспуты по партии: {batch_rate:.1f}% ({batch['disputed_count']}/{batch['orders_count']})"
                f"{extra}"
            )

    def ask_employee_about_dispute(self, player_id: int, dispute_id: int) -> str:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, e.alias, e.honesty, e.attention
                   FROM disputes d JOIN orders o ON o.id=d.order_id JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Диспут уже закрыт."
            if row["courier_reply"]:
                return row["courier_reply"]
            cause = row["true_cause"]
            accurate = self.rng.random() < (float(row["honesty"]) * 0.65 + float(row["attention"]) * 0.25)
            if accurate:
                replies = {
                    "CLIENT_FRAUD": "Уверен, что всё оформил штатно. Перепроверил свою запись - явной ошибки не вижу.",
                    "EMPLOYEE_ERROR": "Перепроверил. Похоже, я действительно мог перепутать данные заказа.",
                    "DESCRIPTION_ERROR": "Описание получилось слабым. Тут мой косяк, надо было оформить понятнее.",
                    "QUALITY_COMPLAINT": "По исполнению заказа ошибок не вижу. Возможно, вопрос к самой партии.",
                    "CLIENT_ERROR": "С моей стороны запись выглядит нормально. Возможно, клиент неправильно понял описание.",
                }
                reply = replies[cause]
            else:
                reply = self.rng.choice([
                    "По памяти всё было нормально. Точно сказать уже не могу.",
                    "Перепроверил свои записи - ничего очевидного не нашёл.",
                    "Есть сомнение в описании, но уверенности нет.",
                ])
            conn.execute("UPDATE disputes SET courier_reply=? WHERE id=?", (reply, dispute_id))
            return reply

    def resolve_dispute(self, player_id: int, dispute_id: int, decision: str) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, c.id cid, c.review_tendency, c.loyalty, e.id eid
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   JOIN clients c ON c.id=o.client_id JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            if decision == "refund":
                refund = int(row["revenue"])
            elif decision == "partial":
                refund = int(row["revenue"] * 0.5)
            else:
                refund = 0
            if refund:
                conn.execute("UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?", (refund, refund, player_id))
                conn.execute(
                    "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'refund', 'order', ?, ?)",
                    (player_id, -refund, row["order_id"], f"Решение по диспуту #{dispute_id}"),
                )

            good = self._decision_quality(row["true_cause"], decision)
            rating_delta = 0.0
            if good > 0:
                rating_delta = self.rng.uniform(0.001, 0.008) * float(row["review_tendency"])
                conn.execute("UPDATE clients SET loyalty=MIN(1.0, loyalty+0.03) WHERE id=?", (row["cid"],))
                if row["true_cause"] == "CLIENT_FRAUD" and decision == "reject":
                    conn.execute("UPDATE clients SET disputes_won=disputes_won WHERE id=?", (row["cid"],))
                elif decision != "reject":
                    conn.execute("UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?", (row["cid"],))
            elif good < 0:
                rating_delta = -self.rng.uniform(0.015, 0.055) * float(row["review_tendency"])
                conn.execute("UPDATE clients SET loyalty=MAX(0.0, loyalty-0.12) WHERE id=?", (row["cid"],))

            if row["true_cause"] in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
                if decision == "reject":
                    conn.execute("UPDATE employees SET loyalty=MIN(1.0, loyalty+0.01) WHERE id=?", (row["eid"],))
                else:
                    conn.execute("UPDATE employees SET stress=MIN(100, stress+2.5) WHERE id=?", (row["eid"],))
            conn.execute("UPDATE shops SET rating=MAX(1.0, MIN(5.0, rating+?)) WHERE player_id=?", (rating_delta, player_id))
            conn.execute(
                "UPDATE disputes SET status='resolved', decision=?, resolved_at=? WHERE id=?",
                (decision, iso(now), dispute_id),
            )
            conn.execute("UPDATE orders SET status='completed' WHERE id=?", (row["order_id"],))
            conn.execute(
                "UPDATE inbox SET status='closed' WHERE player_id=? AND kind='dispute' AND json_extract(payload_json, '$.dispute_id')=?",
                (player_id, dispute_id),
            )
            quality_text = "Решение выглядит удачным." if good > 0 else "Решение может иметь неприятные последствия." if good < 0 else "Ситуация осталась неоднозначной."
            return f"Диспут закрыт. Компенсация: {refund:,} ₽. {quality_text}"

    def _decision_quality(self, cause: str, decision: str) -> int:
        best = {
            "CLIENT_FRAUD": {"reject": 1, "partial": 0, "refund": -1},
            "EMPLOYEE_ERROR": {"refund": 1, "partial": 0, "reject": -1},
            "DESCRIPTION_ERROR": {"refund": 1, "partial": 1, "reject": -1},
            "QUALITY_COMPLAINT": {"partial": 1, "refund": 0, "reject": -1},
            "CLIENT_ERROR": {"partial": 1, "reject": 0, "refund": 0},
        }
        return best.get(cause, {}).get(decision, 0)

    def employees(self, player_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 ORDER BY role, joined_at", (player_id,)
            ).fetchall()

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            e = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=?", (employee_id, player_id)).fetchone()
            if not e:
                return None
            rate = (e["disputes"] / e["jobs_done"] * 100.0) if e["jobs_done"] else 0.0
            status = "работает" if e["available"] else "временно недоступен"
            return (
                f"<b>{e['alias']}</b> · {ROLE_NAMES.get(e['role'], e['role'])}\n\n"
                f"Статус: {status}\n"
                f"Ставка: {e['pay_per_job']:,} ₽ за заказ\n"
                f"Обеспечение: {e['deposit']:,} ₽\n"
                f"Автомобиль: {'да' if e['has_car'] else 'нет'}\n"
                f"Заказов: {e['jobs_done']}\n"
                f"Диспутов: {e['disputes']} ({rate:.1f}%)\n"
                f"Прямые потери: {e['losses']:,} ₽\n"
                f"В команде с: {str(e['joined_at'])[:10]}"
            )

    def candidates(self, player_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM candidates WHERE player_id=? AND status='open' ORDER BY desired_pay", (player_id,)
            ).fetchall()

    def recruit(self, player_id: int, channel: str) -> str:
        params = {
            "board": (2500, 0.00, "Доска площадки"),
            "referral": (6000, 0.08, "Рефералы команды"),
            "niche": (11000, 0.14, "Нишевая реклама"),
        }
        if channel not in params:
            raise ValueError("Unknown recruitment channel")
        cost, quality_bonus, title = params[channel]
        now = utcnow()
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if shop["balance"] < cost:
                return "На счету недостаточно денег."
            conn.execute("UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?", (cost, cost, player_id))
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, ?, 'recruitment', ?)",
                (player_id, -cost, title),
            )
            alias = self.rng.choice(["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза"]) + str(self.rng.randint(10, 99))
            reliability = clamp(self.rng.uniform(0.55, 0.91) + quality_bonus, 0.4, 0.99)
            attention = clamp(self.rng.uniform(0.55, 0.92) + quality_bonus * 0.8, 0.4, 0.99)
            honesty = clamp(self.rng.uniform(0.50, 0.95) + quality_bonus * 0.35, 0.35, 0.99)
            loyalty = self.rng.uniform(0.45, 0.88)
            desired = int(140 + (reliability + attention) * 65 + self.rng.randint(-20, 25))
            deposit = self.rng.choice([15000, 25000, 40000, 60000, 90000])
            has_car = int(self.rng.random() < 0.42)
            summary = f"кандидат из канала «{title}»; {'есть автомобиль' if has_car else 'без автомобиля'}; обеспечение {deposit:,} ₽"
            conn.execute(
                """INSERT INTO candidates(player_id, alias, role, desired_pay, deposit, has_car,
                   reliability, attention, honesty, loyalty, summary, expires_at)
                   VALUES (?, ?, 'courier', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (player_id, alias, desired, deposit, has_car, reliability, attention, honesty, loyalty, summary, iso(now + timedelta(hours=8))),
            )
            return f"Кампания запущена за {cost:,} ₽. Новый кандидат уже появился в списке."

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            c = conn.execute("SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'", (candidate_id, player_id)).fetchone()
            if not c:
                return "Кандидат уже недоступен."
            cur = conn.execute(
                """INSERT INTO employees(player_id, alias, role, pay_per_job, deposit, has_car,
                   reliability, attention, honesty, loyalty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (player_id, c["alias"], c["role"], c["desired_pay"], c["deposit"], c["has_car"], c["reliability"], c["attention"], c["honesty"], c["loyalty"]),
            )
            conn.execute("UPDATE shops SET balance=balance+? WHERE player_id=?", (c["deposit"], player_id))
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'deposit_in', 'employee', ?, ?)",
                (player_id, c["deposit"], cur.lastrowid, f"Обеспечение сотрудника {c['alias']}"),
            )
            conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (candidate_id,))
            return f"{c['alias']} принят в команду. Ставка: {c['desired_pay']:,} ₽."

    def reject_candidate(self, player_id: int, candidate_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE candidates SET status='rejected' WHERE id=? AND player_id=?", (candidate_id, player_id))

    def offers(self, player_id: int):
        self.simulation.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT o.*, s.title supplier_title, p.title product_title
                   FROM supplier_offers o JOIN suppliers s ON s.id=o.supplier_id JOIN products p ON p.id=o.product_id
                   WHERE o.player_id=? AND o.status='open' ORDER BY o.unit_cost * o.quantity""",
                (player_id,),
            ).fetchall()

    def buy_offer(self, player_id: int, offer_id: int) -> str:
        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT o.*, s.quality_mean, s.quality_sigma, s.reliability, s.title supplier_title, p.title product_title
                   FROM supplier_offers o JOIN suppliers s ON s.id=o.supplier_id JOIN products p ON p.id=o.product_id
                   WHERE o.id=? AND o.player_id=? AND o.status='open'""",
                (offer_id, player_id),
            ).fetchone()
            if not offer:
                return "Предложение уже недоступно."
            total = int(offer["quantity"] * offer["unit_cost"])
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            deposits = conn.execute("SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1", (player_id,)).fetchone()[0]
            free_cash = int(shop["balance"]) - int(deposits) - int(shop["reserve_target"])
            if shop["balance"] < total:
                return f"Недостаточно денег: нужно {total:,} ₽."
            risk_note = " Покупка съедает резерв." if free_cash < total else ""
            delivered = self.rng.random() < float(offer["reliability"])
            quality = clamp(self.rng.gauss(float(offer["quality_mean"]), float(offer["quality_sigma"])), 35.0, 99.0)
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (total, player_id))
            if delivered:
                cur = conn.execute(
                    """INSERT INTO batches(player_id, supplier_id, product_id, quantity, remaining, unit_cost, quality)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, offer["supplier_id"], offer["product_id"], offer["quantity"], offer["quantity"], offer["unit_cost"], quality),
                )
                note = f"Партия #{cur.lastrowid}: {offer['product_title']} × {offer['quantity']}"
            else:
                # Supplier failure is deliberately abstract: this is an economic risk, not a procedure simulation.
                cur = None
                note = f"Срыв сделки с {offer['supplier_title']}"
                conn.execute("UPDATE shops SET supplier_reputation=MAX(0, supplier_reputation-1) WHERE player_id=?", (player_id,))
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'procurement', 'offer', ?, ?)",
                (player_id, -total, offer_id, note),
            )
            conn.execute("UPDATE supplier_offers SET status='bought' WHERE id=?", (offer_id,))
            if delivered:
                return f"Куплена партия {offer['product_title']} × {offer['quantity']} за {total:,} ₽. Качество станет понятно по статистике продаж.{risk_note}"
            return f"Сделка сорвалась. Потеря: {total:,} ₽. Это риск поставщика, а не отдельная игровая мини-механика.{risk_note}"

    def listings(self, player_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT l.*, p.title, p.base_market_price,
                   (SELECT COALESCE(SUM(remaining),0) FROM batches b WHERE b.player_id=l.player_id AND b.product_id=l.product_id AND b.status='warehouse') stock
                   FROM listings l JOIN products p ON p.id=l.product_id
                   WHERE l.player_id=? ORDER BY p.id, l.pack_size""",
                (player_id,),
            ).fetchall()

    def change_listing_price(self, player_id: int, listing_id: int, percent: int) -> str:
        if percent not in {-5, 5}:
            raise ValueError("Price step must be ±5")
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM listings WHERE id=? AND player_id=?", (listing_id, player_id)).fetchone()
            if not row:
                return "Позиция не найдена."
            new_price = max(100, int(round(row["price"] * (1 + percent / 100) / 10) * 10))
            conn.execute("UPDATE listings SET price=? WHERE id=?", (new_price, listing_id))
            return f"Цена изменена: {row['price']:,} → {new_price:,} ₽."

    def analytics(self, player_id: int) -> str:
        self.simulation.advance(player_id)
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            stats = conn.execute(
                """SELECT COUNT(*) orders, COALESCE(SUM(revenue),0) revenue,
                   COALESCE(SUM(revenue-cost-employee_cost),0) gross_profit,
                   SUM(CASE WHEN status='disputed' THEN 1 ELSE 0 END) active_disputed
                   FROM orders WHERE player_id=? AND created_at >= datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
            dispute_total = conn.execute(
                "SELECT COUNT(*) FROM disputes WHERE player_id=? AND created_at >= datetime('now','-7 day')", (player_id,)
            ).fetchone()[0]
            refund_total = -conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM ledger WHERE player_id=? AND kind='refund' AND created_at >= datetime('now','-7 day')",
                (player_id,),
            ).fetchone()[0]
            employees = conn.execute(
                """SELECT alias, jobs_done, disputes FROM employees WHERE player_id=? AND active=1
                   ORDER BY CASE WHEN jobs_done=0 THEN 999 ELSE CAST(disputes AS REAL)/jobs_done END DESC LIMIT 5""",
                (player_id,),
            ).fetchall()
            lines = []
            for e in employees:
                rate = e["disputes"] / e["jobs_done"] * 100 if e["jobs_done"] else 0.0
                lines.append(f"• {e['alias']}: {e['jobs_done']} заказов, {rate:.1f}% диспутов")
            margin = (stats["gross_profit"] / stats["revenue"] * 100) if stats["revenue"] else 0.0
            dispute_rate = (dispute_total / stats["orders"] * 100) if stats["orders"] else 0.0
            return (
                "<b>Аналитика · 7 дней</b>\n\n"
                f"Заказов: {stats['orders']}\n"
                f"Выручка: {stats['revenue']:,} ₽\n"
                f"Валовая маржа до компенсаций: {stats['gross_profit']:,} ₽ ({margin:.1f}%)\n"
                f"Компенсации: {refund_total:,} ₽\n"
                f"Диспуты: {dispute_total} ({dispute_rate:.1f}% заказов)\n"
                f"Рейтинг: {shop['rating']:.2f}\n\n"
                "<b>Команда</b>\n" + ("\n".join(lines) if lines else "Пока нет статистики")
            )

    def handle_inbox_action(self, player_id: int, item_id: int, action: str) -> str:
        now = utcnow()
        with self.db.connect() as conn:
            item = conn.execute("SELECT * FROM inbox WHERE id=? AND player_id=? AND status='open'", (item_id, player_id)).fetchone()
            if not item:
                return "Сообщение уже неактуально."
            payload = json.loads(item["payload_json"] or "{}")
            if item["kind"] == "discount_request":
                client_id = payload["client_id"]
                percent = int(payload["percent"])
                if action == "approve":
                    conn.execute("UPDATE clients SET loyalty=MIN(1.0, loyalty+0.06) WHERE id=?", (client_id,))
                    text = f"Купон на {percent}% выдан. Лояльность клиента выросла."
                else:
                    conn.execute("UPDATE clients SET loyalty=MAX(0.0, loyalty-0.025) WHERE id=?", (client_id,))
                    text = "Отказано. Прямых расходов нет, но клиент это запомнит."
            elif item["kind"] == "raise_request":
                employee_id = payload["employee_id"]
                e = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
                if action == "approve":
                    new_pay = int(round(e["pay_per_job"] * 1.10 / 5) * 5)
                    conn.execute("UPDATE employees SET pay_per_job=?, loyalty=MIN(1.0, loyalty+0.08) WHERE id=?", (new_pay, employee_id))
                    text = f"Ставка {e['alias']} повышена до {new_pay:,} ₽."
                else:
                    conn.execute("UPDATE employees SET loyalty=MAX(0.0, loyalty-0.08), stress=MIN(100, stress+4) WHERE id=?", (employee_id,))
                    text = "Повышение отклонено."
            elif item["kind"] == "leave_request":
                employee_id = payload["employee_id"]
                if action == "approve":
                    until = now + timedelta(hours=6)
                    conn.execute("UPDATE employees SET available=0, unavailable_until=?, loyalty=MIN(1.0, loyalty+0.05), stress=MAX(0,stress-12) WHERE id=?", (iso(until), employee_id))
                    text = "Пауза согласована. Сотрудник временно выпадает из производственной мощности."
                else:
                    conn.execute("UPDATE employees SET loyalty=MAX(0.0, loyalty-0.10), stress=MIN(100,stress+7) WHERE id=?", (employee_id,))
                    text = "Пауза не согласована. Сотрудник продолжит работу, но решение повлияет на его состояние."
            elif item["kind"] == "advance_request":
                employee_id = payload["employee_id"]
                amount = int(payload["amount"])
                e = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
                shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
                if action == "approve" and e["deposit"] >= amount and shop["balance"] >= amount:
                    conn.execute("UPDATE employees SET deposit=deposit-?, loyalty=MIN(1.0,loyalty+0.04) WHERE id=?", (amount, employee_id))
                    conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (amount, player_id))
                    conn.execute("INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'deposit_out', 'employee', ?, 'Частичный возврат обеспечения')", (player_id, -amount, employee_id))
                    text = f"Возвращено {amount:,} ₽ из обеспечения. Теперь риск магазина по этому сотруднику выше."
                else:
                    conn.execute("UPDATE employees SET loyalty=MAX(0.0, loyalty-0.03) WHERE id=?", (employee_id,))
                    text = "Запрос отклонён."
            else:
                text = "Сообщение закрыто."
            conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
            return text
