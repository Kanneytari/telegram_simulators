from __future__ import annotations

from ..tutorial import hooks as tutorial_hooks

import json
import random

from .db import Database
from .simulation import SimulationEngine, clamp, iso, utcnow


ROLE_NAMES = {
    "courier": "Закладчик",
    "warehouse": "Складмен",
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
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            deposits = int(conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0])
            stock_cost = int(conn.execute(
                "SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches WHERE player_id=? AND status='warehouse'",
                (player_id,),
            ).fetchone()[0])
            stock_units = int(conn.execute(
                "SELECT COALESCE(SUM(remaining),0) FROM batches WHERE player_id=? AND status='warehouse'",
                (player_id,),
            ).fetchone()[0])
            open_inbox = int(conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id=? AND status='open'", (player_id,)
            ).fetchone()[0])
            urgent = int(conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id=? AND status='open' AND priority IN ('important','urgent')",
                (player_id,),
            ).fetchone()[0])
            employees = int(conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1", (player_id,)
            ).fetchone()[0])
            trust = conn.execute(
                "SELECT trust_score FROM shop_trust_state WHERE player_id=?", (player_id,)
            ).fetchone()
        free_cash = int(shop["balance"]) - deposits - int(shop["reserve_target"])
        trust_score = float(trust["trust_score"]) if trust else 55.0
        return (
            f"<b>{shop['name']}</b>\n\n"
            f"Баланс: <b>{shop['balance']:,} ₽</b>\n"
            f"Свободные деньги: <b>{free_cash:,} ₽</b>\n"
            f"Товарный остаток: {stock_units} ед. / ~{stock_cost:,} ₽ по себестоимости\n"
            f"Доверие: <b>{trust_score:.0f}/100</b>\n"
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
                """SELECT d.*, o.*, c.id cid, e.id eid
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   JOIN clients c ON c.id=o.client_id JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            refund = int(row["revenue"]) if decision == "refund" else int(row["revenue"] * 0.5) if decision == "partial" else 0
            if refund:
                conn.execute(
                    "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                    (refund, refund, player_id),
                )
                conn.execute(
                    "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'refund', 'order', ?, ?)",
                    (player_id, -refund, row["order_id"], f"Решение по диспуту #{dispute_id}"),
                )
            good = self._decision_quality(row["true_cause"], decision)
            if good > 0 and decision != "reject":
                conn.execute("UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?", (row["cid"],))
            if row["true_cause"] in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
                if decision == "reject":
                    conn.execute("UPDATE employees SET loyalty=MIN(1.0, loyalty+0.01) WHERE id=?", (row["eid"],))
                else:
                    conn.execute("UPDATE employees SET stress=MIN(100, stress+2.5) WHERE id=?", (row["eid"],))
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

    def reject_candidate(self, player_id: int, candidate_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE candidates SET status='rejected' WHERE id=? AND player_id=?", (candidate_id, player_id))

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

    @tutorial_hooks.price_progress
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

    def handle_inbox_action(self, player_id: int, item_id: int, action: str) -> str:
        with self.db.connect() as conn:
            item = conn.execute(
                "SELECT * FROM inbox WHERE id=? AND player_id=? AND status='open'",
                (item_id, player_id),
            ).fetchone()
            if not item:
                return "Сообщение уже неактуально."
            if item["kind"] == "discount_request":
                payload = json.loads(item["payload_json"] or "{}")
                percent = int(payload.get("percent", 0))
                text = f"Скидка {percent}% согласована." if action == "approve" else "Скидка отклонена."
            else:
                text = "Сообщение закрыто."
            conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
        return text
