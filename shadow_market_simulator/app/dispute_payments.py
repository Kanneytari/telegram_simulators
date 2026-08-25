from __future__ import annotations

from .simulation import iso, utcnow


class DisputePaymentMixin:
    """Add explicit refund-source handling to a cooperative game service."""

    def dispute_payment_context(
        self, player_id: int, dispute_id: int, decision: str
    ) -> dict | None:
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
        amount = (
            int(row["revenue"])
            if decision == "refund"
            else int(row["revenue"] * 0.5)
        )
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

    def _resolve_from_shop_or_reject(
        self, player_id: int, dispute_id: int, decision: str
    ) -> str:
        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, c.id cid, e.id eid, s.balance shop_balance
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN clients c ON c.id=o.client_id
                   JOIN employees e ON e.id=o.employee_id
                   JOIN shops s ON s.player_id=d.player_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."

            refund = (
                int(row["revenue"])
                if decision == "refund"
                else int(row["revenue"] * 0.5)
                if decision == "partial"
                else 0
            )
            if refund and int(row["shop_balance"]) < refund:
                return (
                    "На счёте магазина недостаточно денег.\n\n"
                    f"Нужно: {refund:,} ₽\n"
                    f"Доступно: {int(row['shop_balance']):,} ₽"
                )

            if refund:
                conn.execute(
                    "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                    (refund, refund, player_id),
                )
                conn.execute(
                    """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                       VALUES (?, ?, 'refund', 'order', ?, ?)""",
                    (
                        player_id,
                        -refund,
                        row["order_id"],
                        f"Решение по диспуту #{dispute_id}",
                    ),
                )

            good = self._decision_quality(row["true_cause"], decision)
            if good > 0 and decision != "reject":
                conn.execute(
                    "UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?",
                    (row["cid"],),
                )
            if row["true_cause"] in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
                if decision == "reject":
                    conn.execute(
                        "UPDATE employees SET loyalty=MIN(1.0, loyalty+0.01) WHERE id=?",
                        (row["eid"],),
                    )
                else:
                    conn.execute(
                        "UPDATE employees SET stress=MIN(100, stress+2.5) WHERE id=?",
                        (row["eid"],),
                    )

            refund_source = "shop" if refund else "none"
            conn.execute(
                """UPDATE disputes
                   SET status='resolved', decision=?, refund_amount=?, refund_source=?,
                       refund_employee_id=NULL, resolved_at=?
                   WHERE id=?""",
                (decision, refund, refund_source, iso(now), dispute_id),
            )
            conn.execute(
                "UPDATE orders SET status='completed' WHERE id=?",
                (row["order_id"],),
            )
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND kind='dispute'
                     AND json_extract(payload_json, '$.dispute_id')=?""",
                (player_id, dispute_id),
            )

        quality_text = (
            "Решение выглядит удачным."
            if good > 0
            else "Решение может иметь неприятные последствия."
            if good < 0
            else "Ситуация осталась неоднозначной."
        )
        return f"Диспут закрыт. Компенсация: {refund:,} ₽. {quality_text}"

    def resolve_dispute_with_source(
        self,
        player_id: int,
        dispute_id: int,
        decision: str,
        source: str,
    ) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        if source not in {"shop", "employee", "none"}:
            raise ValueError("Unsupported compensation source")
        if decision == "reject":
            if source != "none":
                return "Для отклонённого диспута источник компенсации не нужен."
            return self._resolve_from_shop_or_reject(player_id, dispute_id, decision)
        if source == "none":
            return "Выберите источник компенсации."

        context = self.dispute_payment_context(player_id, dispute_id, decision)
        if not context:
            return "Этот диспут уже закрыт."
        refund = int(context["amount"])
        if source == "shop":
            result = self._resolve_from_shop_or_reject(
                player_id, dispute_id, decision
            )
            if result.startswith("На счёте магазина недостаточно денег."):
                return result
            if result == "Этот диспут уже закрыт.":
                return result
            return f"{result}\nИсточник: счёт магазина."

        if int(context["employee_deposit"]) < refund:
            return (
                "Недостаточно средств в депозите сотрудника.\n\n"
                f"Нужно: {refund:,} ₽\n"
                f"Доступно: {context['employee_deposit']:,} ₽"
            )

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
                """UPDATE employees
                   SET deposit=deposit-?, losses=losses+?, stress=MIN(100, stress+2.5)
                   WHERE id=?""",
                (refund, refund, row["eid"]),
            )
            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (refund, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'refund_employee_deposit', 'employee', ?, ?)""",
                (
                    player_id,
                    -refund,
                    row["eid"],
                    f"Компенсация по диспуту #{dispute_id} из депозита {row['employee_alias']}",
                ),
            )
            good = self._decision_quality(row["true_cause"], decision)
            if good > 0:
                conn.execute(
                    "UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?",
                    (row["client_id"],),
                )
            conn.execute(
                """UPDATE disputes
                   SET status='resolved', decision=?, refund_amount=?, refund_source='employee',
                       refund_employee_id=?, resolved_at=? WHERE id=?""",
                (decision, refund, row["eid"], iso(now), dispute_id),
            )
            conn.execute(
                "UPDATE orders SET status='completed' WHERE id=?",
                (row["order_id"],),
            )
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND kind='dispute'
                     AND json_extract(payload_json, '$.dispute_id')=?""",
                (player_id, dispute_id),
            )
        quality_text = (
            "Решение выглядит удачным."
            if good > 0
            else "Решение может иметь неприятные последствия."
            if good < 0
            else "Ситуация осталась неоднозначной."
        )
        return (
            f"Диспут закрыт. Компенсация: {refund:,} ₽.\n"
            f"Источник: депозит {context['employee_alias']}.\n\n"
            f"{quality_text}"
        )


# Transitional import compatibility. This is an alias, not an inheritance layer.
DisputePaymentGameService = DisputePaymentMixin

__all__ = ["DisputePaymentMixin", "DisputePaymentGameService"]
