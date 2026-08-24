from __future__ import annotations

from .game import GameService
from .simulation import iso, utcnow


class DisputePaymentGameService(GameService):
    def dispute_payment_context(self, player_id: int, dispute_id: int, decision: str) -> dict | None:
        if decision not in {"refund", "partial"}:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.id dispute_id, d.status, o.id order_id, o.revenue,
                          e.id employee_id, e.alias employee_alias, e.deposit,
                          s.balance, s.reserve_target
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   JOIN shops s ON s.player_id=d.player_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        if not row or row["status"] != "open":
            return None
        amount = int(row["revenue"]) if decision == "refund" else int(row["revenue"] * 0.5)
        return {
            "dispute_id": dispute_id,
            "order_id": int(row["order_id"]),
            "amount": amount,
            "employee_id": int(row["employee_id"]),
            "employee_alias": row["employee_alias"],
            "employee_deposit": int(row["deposit"]),
            "shop_balance": int(row["balance"]),
            "shop_reserve": int(row["reserve_target"]),
        }

    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        if source not in {"shop", "employee", "none"}:
            raise ValueError("Unsupported compensation source")
        if decision == "reject":
            result = super().resolve_dispute(player_id, dispute_id, "reject")
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE disputes SET refund_amount=0, refund_source='none', refund_employee_id=NULL WHERE id=? AND player_id=?",
                    (dispute_id, player_id),
                )
            return result

        context = self.dispute_payment_context(player_id, dispute_id, decision)
        if not context:
            return "Этот диспут уже закрыт."
        refund = int(context["amount"])
        if source == "shop":
            if int(context["shop_balance"]) < refund:
                return f"На счёте магазина недостаточно денег.\n\nНужно: {refund:,} ₽\nДоступно: {context['shop_balance']:,} ₽"
            result = super().resolve_dispute(player_id, dispute_id, decision)
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE disputes SET refund_amount=?, refund_source='shop', refund_employee_id=NULL WHERE id=? AND player_id=?",
                    (refund, dispute_id, player_id),
                )
            return f"{result}\nИсточник: счёт магазина."

        if int(context["employee_deposit"]) < refund:
            return f"Недостаточно средств в депозите сотрудника.\n\nНужно: {refund:,} ₽\nДоступно: {context['employee_deposit']:,} ₽"

        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, e.id eid, e.alias employee_alias, e.deposit
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            if int(row["deposit"]) < refund:
                return "Депозит сотрудника уже недостаточен для этой компенсации."
            conn.execute(
                "UPDATE employees SET deposit=deposit-?, losses=losses+?, stress=MIN(100, stress+2.5) WHERE id=?",
                (refund, refund, row["eid"]),
            )
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (refund, player_id))
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'refund_employee_deposit', 'employee', ?, ?)""",
                (player_id, -refund, row["eid"], f"Компенсация по диспуту #{dispute_id} из депозита {row['employee_alias']}"),
            )
            good = self._decision_quality(row["true_cause"], decision)
            conn.execute(
                """UPDATE disputes
                   SET status='resolved', decision=?, refund_amount=?, refund_source='employee',
                       refund_employee_id=?, resolved_at=? WHERE id=?""",
                (decision, refund, row["eid"], iso(now), dispute_id),
            )
            conn.execute("UPDATE orders SET status='completed' WHERE id=?", (row["order_id"],))
            conn.execute(
                "UPDATE inbox SET status='closed' WHERE player_id=? AND kind='dispute' AND json_extract(payload_json, '$.dispute_id')=?",
                (player_id, dispute_id),
            )
        quality_text = "Решение выглядит удачным." if good > 0 else "Решение может иметь неприятные последствия." if good < 0 else "Ситуация осталась неоднозначной."
        return f"Диспут закрыт. Компенсация: {refund:,} ₽.\nИсточник: депозит {context['employee_alias']}.\n\n{quality_text}"
