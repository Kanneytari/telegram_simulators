from __future__ import annotations

from ..staff.idle import IdleAwareMixin
from ..staff_relationships import StaffRelationshipGameService


class GlobalPackagingGameService(IdleAwareMixin, StaffRelationshipGameService):
    def global_packaging_rule(self, player_id: int) -> dict[str, int]:
        self.simulation._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return {
            "pct_1": int(row["pct_1"]),
            "pct_2": int(row["pct_2"]),
            "pct_5": int(row["pct_5"]),
        }

    def adjust_global_packaging_rule(
        self, player_id: int, pack_size: int, delta: int
    ) -> str:
        if pack_size not in {1, 2, 5} or delta not in {-10, 10}:
            raise ValueError("Unsupported packaging adjustment")

        self.simulation._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
                (player_id,),
            ).fetchone()
            values = {
                1: int(row["pct_1"]),
                2: int(row["pct_2"]),
                5: int(row["pct_5"]),
            }

            if delta > 0:
                needed = min(delta, 100 - values[pack_size])
                for other in sorted(
                    (value for value in values if value != pack_size),
                    key=lambda value: values[value],
                    reverse=True,
                ):
                    take = min(needed, values[other])
                    values[other] -= take
                    values[pack_size] += take
                    needed -= take
                    if needed <= 0:
                        break
            else:
                amount = min(-delta, values[pack_size])
                values[pack_size] -= amount
                other = max(
                    (value for value in values if value != pack_size),
                    key=lambda value: values[value],
                )
                values[other] += amount

            conn.execute(
                """UPDATE shop_packaging_rules
                   SET pct_1=?, pct_2=?, pct_5=?, updated_at=CURRENT_TIMESTAMP
                   WHERE player_id=?""",
                (values[1], values[2], values[5], player_id),
            )

        return f"×1 {values[1]}% · ×2 {values[2]}% · ×5 {values[5]}%"

    def change_employee_role(self, player_id: int, employee_id: int) -> str:
        result = super().change_employee_role(player_id, employee_id)
        self.simulation._ensure_packaging_rules(player_id)
        return result
