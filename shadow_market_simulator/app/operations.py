from __future__ import annotations

from .nightshift import NightshiftSimulationEngine
from .services import FinalGameService
from .simulation import clamp, iso, utcnow


class OperationsSimulationEngine(NightshiftSimulationEngine):
    """Adds batch responsibility and customer reviews to the core simulation."""

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        if not created:
            return False

        with self.db.connect() as conn:
            warehouse = conn.execute(
                "SELECT id FROM employees WHERE player_id=? AND role='warehouse' AND active=1 LIMIT 1",
                (player_id,),
            ).fetchone()
            if not warehouse:
                deposit = 700_000
                cur = conn.execute(
                    """INSERT INTO employees(
                           player_id, alias, role, pay_per_job, deposit,
                           deposit_contribution_pct, has_car,
                           reliability, attention, honesty, loyalty, stress
                       ) VALUES (?, 'Маяк', 'warehouse', 5000, ?, 10, 1, 0.91, 0.88, 0.93, 0.78, 10)""",
                    (player_id, deposit),
                )
                warehouse_id = cur.lastrowid
            else:
                warehouse_id = int(warehouse["id"])

            # Starter employee deposits are liabilities held by the shop and therefore
            # also appear on its cash balance. This keeps free-cash arithmetic coherent.
            deposits = int(conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0])
            conn.execute("UPDATE shops SET balance=balance+? WHERE player_id=?", (deposits, player_id))
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, note)
                   VALUES (?, ?, 'deposit_in', 'Стартовые депозиты команды')""",
                (player_id, deposits),
            )
            conn.execute(
                """UPDATE batches SET responsible_employee_id=?
                   WHERE player_id=? AND responsible_employee_id IS NULL""",
                (warehouse_id, player_id),
            )
        return True

    def _create_order(self, conn, player_id: int, listing, employee, now) -> bool:
        before_id = int(conn.execute(
            "SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?",
            (player_id,),
        ).fetchone()[0])
        disputed = super()._create_order(conn, player_id, listing, employee, now)
        order = conn.execute(
            "SELECT id FROM orders WHERE player_id=? AND id>? ORDER BY id DESC LIMIT 1",
            (player_id, before_id),
        ).fetchone()
        if order and not disputed:
            self._create_review(conn, player_id, int(order["id"]), force=False)
        return disputed

    def create_review_for_order(self, player_id: int, order_id: int, *, force: bool = False) -> int | None:
        with self.db.connect() as conn:
            return self._create_review(conn, player_id, order_id, force=force)

    def _create_review(self, conn, player_id: int, order_id: int, *, force: bool) -> int | None:
        exists = conn.execute("SELECT id FROM reviews WHERE order_id=?", (order_id,)).fetchone()
        if exists:
            return int(exists["id"])
        row = conn.execute(
            """SELECT o.*, c.review_tendency, e.attention, e.stress,
                      p.title product_title,
                      d.true_cause, d.decision
               FROM orders o
               JOIN clients c ON c.id=o.client_id
               JOIN employees e ON e.id=o.employee_id
               JOIN products p ON p.id=o.product_id
               LEFT JOIN disputes d ON d.order_id=o.id
               WHERE o.id=? AND o.player_id=?""",
            (order_id, player_id),
        ).fetchone()
        if not row:
            return None

        probability = clamp(0.35 + float(row["review_tendency"]) * 0.55, 0.35, 0.90)
        if not force and self.rng.random() > probability:
            return None

        quality = float(row["quality"])
        if quality >= 90:
            stars = 5
            quality_sentiment = "good"
            quality_text = self.rng.choice([
                "Качество отличное, к товару вопросов нет.",
                "По качеству всё стабильно, покупкой доволен.",
            ])
        elif quality >= 80:
            stars = 4
            quality_sentiment = "good"
            quality_text = self.rng.choice([
                "Качество хорошее, всё устроило.",
                "По товару всё нормально, без замечаний.",
            ])
        elif quality >= 68:
            stars = 3
            quality_sentiment = "neutral"
            quality_text = self.rng.choice([
                "Качество среднее, ожидал немного лучше.",
                "По качеству есть вопросы, но в целом нормально.",
            ])
        else:
            stars = 2
            quality_sentiment = "bad"
            quality_text = self.rng.choice([
                "Качество заметно хуже прошлых покупок.",
                "Товар разочаровал по качеству.",
            ])

        delivery_score = float(row["attention"]) - max(0.0, float(row["stress"]) - 55.0) / 180.0
        cause = row["true_cause"]
        if cause in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
            delivery_score = min(delivery_score, 0.45)
        if cause == "QUALITY_COMPLAINT":
            quality_sentiment = "bad"
            stars = min(stars, 2)
            quality_text = "По качеству этой покупки остались серьёзные вопросы."

        if delivery_score >= 0.87:
            delivery_sentiment = "good"
            delivery_text = self.rng.choice([
                "По доставке всё без вопросов.",
                "Сотрудник отработал аккуратно.",
            ])
        elif delivery_score >= 0.68:
            delivery_sentiment = "neutral"
            delivery_text = "По доставке нормально, но можно аккуратнее."
        else:
            delivery_sentiment = "bad"
            stars = max(1, stars - 1)
            delivery_text = self.rng.choice([
                "По доставке был косяк, описание подвело.",
                "Сотрудник допустил ошибку, пришлось разбираться.",
            ])

        if row["decision"] in {"refund", "partial", "auto_partial"} and force:
            stars = min(5, stars + 1)
            service_text = "Поддержка магазина ситуацию в итоге решила."
        elif row["decision"] == "reject" and force:
            stars = max(1, stars - 1)
            service_text = "По решению магазина остался недоволен."
        else:
            service_text = ""

        text = " ".join(part for part in (quality_text, delivery_text, service_text) if part)
        cur = conn.execute(
            """INSERT INTO reviews(
                   player_id, order_id, client_id, product_id, employee_id,
                   rating, text, quality_sentiment, delivery_sentiment
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                order_id,
                row["client_id"],
                row["product_id"],
                row["employee_id"],
                stars,
                text,
                quality_sentiment,
                delivery_sentiment,
            ),
        )
        conn.execute(
            "UPDATE shops SET rating=MAX(1.0, MIN(5.0, rating*0.985 + ?*0.015)) WHERE player_id=?",
            (stars, player_id),
        )
        return int(cur.lastrowid)


class OperationsGameService(FinalGameService):
    """UI-facing operations: accountable inventory, termination and review analytics."""

    def warehouse_staff_for_offer(self, player_id: int, offer_id: int):
        with self.db.connect() as conn:
            offer = conn.execute(
                "SELECT quantity, unit_cost FROM supplier_offers WHERE id=? AND player_id=? AND status='open'",
                (offer_id, player_id),
            ).fetchone()
            if not offer:
                return []
            total = int(offer["quantity"] * offer["unit_cost"])
            rows = conn.execute(
                """SELECT e.*,
                          COALESCE((SELECT SUM(b.remaining*b.unit_cost) FROM batches b
                                    WHERE b.player_id=e.player_id
                                      AND b.responsible_employee_id=e.id
                                      AND b.status='warehouse'),0) exposure
                   FROM employees e
                   WHERE e.player_id=? AND e.active=1 AND e.role='warehouse'
                   ORDER BY e.deposit DESC""",
                (player_id,),
            ).fetchall()
        result = []
        for row in rows:
            exposure = int(row["exposure"] or 0)
            free_coverage = max(0, int(row["deposit"]) - exposure)
            result.append({
                "id": int(row["id"]),
                "alias": row["alias"],
                "deposit": int(row["deposit"]),
                "exposure": exposure,
                "free_coverage": free_coverage,
                "eligible": free_coverage >= total,
                "required": total,
            })
        return result

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT o.*, s.quality_mean, s.quality_sigma, s.reliability,
                          s.title supplier_title, p.title product_title
                   FROM supplier_offers o
                   JOIN suppliers s ON s.id=o.supplier_id
                   JOIN products p ON p.id=o.product_id
                   WHERE o.id=? AND o.player_id=? AND o.status='open'""",
                (offer_id, player_id),
            ).fetchone()
            employee = conn.execute(
                """SELECT * FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (employee_id, player_id),
            ).fetchone()
            if not offer:
                return "Предложение уже недоступно."
            if not employee:
                return "Оптовый сотрудник больше недоступен."

            total = int(offer["quantity"] * offer["unit_cost"])
            exposure = int(conn.execute(
                """SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches
                   WHERE player_id=? AND responsible_employee_id=? AND status='warehouse'""",
                (player_id, employee_id),
            ).fetchone()[0])
            free_coverage = max(0, int(employee["deposit"]) - exposure)
            if free_coverage < total:
                return (
                    "Недостаточно свободного покрытия по депозиту.\n\n"
                    f"Нужно: {total:,} ₽\n"
                    f"Свободно у {employee['alias']}: {free_coverage:,} ₽"
                )

            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if int(shop["balance"]) < total:
                return f"Недостаточно денег: нужно {total:,} ₽."

            delivered = self.rng.random() < float(offer["reliability"])
            quality = clamp(
                self.rng.gauss(float(offer["quality_mean"]), float(offer["quality_sigma"])),
                35.0,
                99.0,
            )
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (total, player_id))
            conn.execute(
                """UPDATE employees SET jobs_done=jobs_done+1,
                       wages_accrued=wages_accrued+?, stress=MIN(100, stress+1.2),
                       last_contact_at=? WHERE id=?""",
                (int(employee["pay_per_job"]), iso(utcnow()), employee_id),
            )
            if delivered:
                cur = conn.execute(
                    """INSERT INTO batches(
                           player_id, supplier_id, product_id, responsible_employee_id,
                           quantity, remaining, unit_cost, quality
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        offer["supplier_id"],
                        offer["product_id"],
                        employee_id,
                        offer["quantity"],
                        offer["quantity"],
                        offer["unit_cost"],
                        quality,
                    ),
                )
                note = f"Партия #{cur.lastrowid}: {offer['product_title']} · ответственный {employee['alias']}"
            else:
                note = f"Срыв сделки с {offer['supplier_title']} · ответственный {employee['alias']}"
                conn.execute(
                    "UPDATE shops SET supplier_reputation=MAX(0, supplier_reputation-1) WHERE player_id=?",
                    (player_id,),
                )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'procurement', 'offer', ?, ?)""",
                (player_id, -total, offer_id, note),
            )
            conn.execute("UPDATE supplier_offers SET status='bought' WHERE id=?", (offer_id,))

        if delivered:
            return (
                f"Партия куплена за <b>{total:,} ₽</b>.\n\n"
                f"Ответственный: <b>{employee['alias']}</b>\n"
                f"Начислено за операцию: {employee['pay_per_job']:,} ₽"
            )
        return f"Сделка сорвалась. Потеря: {total:,} ₽."

    def employee_inventory(self, player_id: int, employee_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT b.*, p.title product_title
                   FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.player_id=? AND b.responsible_employee_id=?
                     AND b.status='warehouse' AND b.remaining>0
                   ORDER BY b.acquired_at DESC""",
                (player_id, employee_id),
            ).fetchall()

    def batch_transfer_options(self, player_id: int, batch_id: int):
        with self.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse'",
                (batch_id, player_id),
            ).fetchone()
            if not batch:
                return None, []
            value = int(batch["remaining"] * batch["unit_cost"])
            employees = conn.execute(
                """SELECT e.*,
                          COALESCE((SELECT SUM(b.remaining*b.unit_cost) FROM batches b
                                    WHERE b.player_id=e.player_id
                                      AND b.responsible_employee_id=e.id
                                      AND b.status='warehouse'),0) exposure
                   FROM employees e
                   WHERE e.player_id=? AND e.active=1 AND e.role='warehouse' AND e.id<>?
                   ORDER BY e.deposit DESC""",
                (player_id, batch["responsible_employee_id"] or -1),
            ).fetchall()
        options = []
        for employee in employees:
            free = max(0, int(employee["deposit"]) - int(employee["exposure"] or 0))
            options.append({"id": int(employee["id"]), "alias": employee["alias"], "free": free, "eligible": free >= value})
        return batch, options

    def reassign_batch(self, player_id: int, batch_id: int, employee_id: int) -> str:
        batch, options = self.batch_transfer_options(player_id, batch_id)
        if not batch:
            return "Партия не найдена."
        target = next((row for row in options if row["id"] == employee_id), None)
        if not target or not target["eligible"]:
            return "У выбранного сотрудника недостаточно свободного покрытия."
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE batches SET responsible_employee_id=? WHERE id=? AND player_id=?",
                (employee_id, batch_id, player_id),
            )
        return f"Партия #{batch_id} передана сотруднику {target['alias']}."

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            e = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=?", (employee_id, player_id)).fetchone()
            if not e:
                return None
            reviews = conn.execute(
                "SELECT COUNT(*) count, COALESCE(AVG(rating),0) avg FROM reviews WHERE player_id=? AND employee_id=?",
                (player_id, employee_id),
            ).fetchone()
            exposure = int(conn.execute(
                """SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches
                   WHERE player_id=? AND responsible_employee_id=? AND status='warehouse'""",
                (player_id, employee_id),
            ).fetchone()[0])
        rate = e["disputes"] / e["jobs_done"] * 100.0 if e["jobs_done"] else 0.0
        status = "работает" if e["active"] and e["available"] else "временно недоступен" if e["active"] else "уволен"
        role = "Оптовый сотрудник" if e["role"] == "warehouse" else "Розничный сотрудник" if e["role"] == "courier" else e["role"]
        text = (
            f"<b>👤 {e['alias']}</b> · {role}\n\n"
            f"<b>Условия</b>\n"
            f"Статус: {status}\n"
            f"Ставка: <b>{e['pay_per_job']:,} ₽</b> / операцию\n"
            f"Депозит: <b>{e['deposit']:,} ₽</b>\n"
            f"Начислено к выплате: {e['wages_accrued']:,} ₽\n\n"
            f"<b>Статистика</b>\n"
            f"Операций: {e['jobs_done']}\n"
            f"Диспутов: {e['disputes']} ({rate:.1f}%)\n"
            f"Прямые потери: {e['losses']:,} ₽\n"
            f"Отзывы: {reviews['count']}"
        )
        if reviews["count"]:
            text += f" · ⭐ {float(reviews['avg']):.2f}"
        if e["role"] == "warehouse":
            free = max(0, int(e["deposit"]) - exposure)
            text += (
                "\n\n<b>Ответственность</b>\n"
                f"Товар на ответственности: {exposure:,} ₽\n"
                f"Свободное покрытие: <b>{free:,} ₽</b>"
            )
        return text

    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return {"status": "missing", "message": "Сотрудник уже не работает в магазине."}
            exposure = int(conn.execute(
                """SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches
                   WHERE player_id=? AND responsible_employee_id=? AND status='warehouse'""",
                (player_id, employee_id),
            ).fetchone()[0])
            if exposure > 0:
                return {
                    "status": "inventory",
                    "message": f"Нельзя уволить сотрудника: на нём числится товар на {exposure:,} ₽. Сначала передай партии другому оптовому сотруднику.",
                }
            payout = int(employee["deposit"]) + int(employee["wages_accrued"])
            balance = int(conn.execute("SELECT balance FROM shops WHERE player_id=?", (player_id,)).fetchone()[0])
            if balance < payout:
                return {"status": "money", "message": f"Для расчёта нужно {payout:,} ₽, на счёте {balance:,} ₽."}
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (payout, player_id))
            conn.execute(
                """UPDATE employees SET active=0, available=0, deposit=0,
                       total_wages_paid=total_wages_paid+wages_accrued, wages_accrued=0
                   WHERE id=?""",
                (employee_id,),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'employee_settlement', 'employee', ?, ?)""",
                (player_id, -payout, employee_id, f"Расчёт при увольнении {employee['alias']}"),
            )
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND status='open'
                     AND json_extract(payload_json, '$.employee_id')=?""",
                (player_id, employee_id),
            )
        return {"status": "ok", "message": f"{employee['alias']} уволен. Итоговый расчёт: {payout:,} ₽."}

    def product_reviews(self, player_id: int, product_id: int, limit: int = 15):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT r.*, p.title product_title, o.quantity, c.alias client_alias, e.alias employee_alias
                   FROM reviews r
                   JOIN products p ON p.id=r.product_id
                   JOIN orders o ON o.id=r.order_id
                   JOIN clients c ON c.id=r.client_id
                   JOIN employees e ON e.id=r.employee_id
                   WHERE r.player_id=? AND r.product_id=?
                   ORDER BY r.created_at DESC LIMIT ?""",
                (player_id, product_id, limit),
            ).fetchall()

    def employee_reviews(self, player_id: int, employee_id: int, limit: int = 15):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT r.*, p.title product_title, o.quantity, c.alias client_alias
                   FROM reviews r
                   JOIN products p ON p.id=r.product_id
                   JOIN orders o ON o.id=r.order_id
                   JOIN clients c ON c.id=r.client_id
                   WHERE r.player_id=? AND r.employee_id=?
                   ORDER BY r.created_at DESC LIMIT ?""",
                (player_id, employee_id, limit),
            ).fetchall()

    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        with self.db.connect() as conn:
            order = conn.execute(
                "SELECT order_id FROM disputes WHERE id=? AND player_id=? AND status='open'",
                (dispute_id, player_id),
            ).fetchone()
        result = super().resolve_dispute_with_source(player_id, dispute_id, decision, source)
        if order:
            self.simulation.create_review_for_order(player_id, int(order["order_id"]), force=True)
        return result
