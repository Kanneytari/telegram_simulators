from __future__ import annotations

from .operations import OperationsGameService, OperationsSimulationEngine
from .services import FinalGameService


class FinalOperationsSimulationEngine(OperationsSimulationEngine):
    def _expire_items(self, conn, player_id: int, now) -> None:
        before = {
            int(row["id"]): int(row["order_id"])
            for row in conn.execute(
                "SELECT id, order_id FROM disputes WHERE player_id=? AND status='open'",
                (player_id,),
            ).fetchall()
        }
        super()._expire_items(conn, player_id, now)
        for dispute_id, order_id in before.items():
            row = conn.execute("SELECT status, decision FROM disputes WHERE id=?", (dispute_id,)).fetchone()
            if row and row["status"] == "resolved" and row["decision"] == "auto_partial":
                self._create_review(conn, player_id, order_id, force=True)


class FinalOperationsGameService(OperationsGameService):
    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        with self.db.connect() as conn:
            order = conn.execute(
                "SELECT order_id FROM disputes WHERE id=? AND player_id=? AND status='open'",
                (dispute_id, player_id),
            ).fetchone()
        # Call the compensation implementation directly so a failed payment attempt
        # does not create a customer review before the dispute is actually resolved.
        result = FinalGameService.resolve_dispute_with_source(self, player_id, dispute_id, decision, source)
        if order:
            with self.db.connect() as conn:
                resolved = conn.execute(
                    "SELECT status FROM disputes WHERE id=? AND player_id=?",
                    (dispute_id, player_id),
                ).fetchone()
            if resolved and resolved["status"] == "resolved":
                self.simulation.create_review_for_order(player_id, int(order["order_id"]), force=True)
        return result
