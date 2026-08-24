from __future__ import annotations

from .catalog_extension import ExpandedCatalogSimulationEngine
from .staff_idle import IdleAwareGameService


GLOBAL_PACKAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_packaging_rules (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    pct_1 INTEGER NOT NULL DEFAULT 60,
    pct_2 INTEGER NOT NULL DEFAULT 30,
    pct_5 INTEGER NOT NULL DEFAULT 10,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class GlobalPackagingSimulationEngine(ExpandedCatalogSimulationEngine):
    """Keep one packaging mix for the whole shop and mirror it to legacy rules."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(GLOBAL_PACKAGING_SCHEMA)
            player_ids = [int(row[0]) for row in conn.execute("SELECT player_id FROM shops").fetchall()]
            for player_id in player_ids:
                self._ensure_global_rule_conn(conn, player_id)
                self._sync_legacy_rules_conn(conn, player_id)

    def _ensure_global_rule_conn(self, conn, player_id: int) -> None:
        existing = conn.execute(
            "SELECT 1 FROM shop_packaging_rules WHERE player_id=?",
            (player_id,),
        ).fetchone()
        if existing:
            return

        # Preserve the dominant previous setup when converting an existing save.
        previous = conn.execute(
            """SELECT pct_1, pct_2, pct_5, COUNT(*) AS uses
               FROM packaging_rules
               WHERE player_id=?
               GROUP BY pct_1, pct_2, pct_5
               ORDER BY uses DESC, pct_1 DESC, pct_2 DESC, pct_5 DESC
               LIMIT 1""",
            (player_id,),
        ).fetchone()
        values = (
            (int(previous["pct_1"]), int(previous["pct_2"]), int(previous["pct_5"]))
            if previous else (60, 30, 10)
        )
        conn.execute(
            """INSERT INTO shop_packaging_rules(player_id, pct_1, pct_2, pct_5)
               VALUES (?, ?, ?, ?)""",
            (player_id, *values),
        )

    def _sync_legacy_rules_conn(self, conn, player_id: int) -> None:
        rule = conn.execute(
            "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
            (player_id,),
        ).fetchone()
        if not rule:
            return
        conn.execute(
            """UPDATE packaging_rules
               SET pct_1=?, pct_2=?, pct_5=?
               WHERE player_id=?""",
            (int(rule["pct_1"]), int(rule["pct_2"]), int(rule["pct_5"]), player_id),
        )

    def _ensure_packaging_rules(self, player_id: int) -> None:
        super()._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            conn.executescript(GLOBAL_PACKAGING_SCHEMA)
            self._ensure_global_rule_conn(conn, player_id)
            self._sync_legacy_rules_conn(conn, player_id)

    def seed_catalog(self) -> None:
        super().seed_catalog()
        with self.db.connect() as conn:
            player_ids = [int(row[0]) for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        for player_id in player_ids:
            self._ensure_packaging_rules(player_id)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        self._ensure_packaging_rules(player_id)
        return created


class GlobalPackagingGameService(IdleAwareGameService):
    """Expose the single shop-wide packaging rule to UI and legacy callbacks."""

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

    def adjust_global_packaging_rule(self, player_id: int, pack_size: int, delta: int) -> str:
        if pack_size not in {1, 2, 5} or delta not in {-10, 10}:
            raise ValueError("Unsupported packaging adjustment")

        self.simulation._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
                (player_id,),
            ).fetchone()
            values = {1: int(row["pct_1"]), 2: int(row["pct_2"]), 5: int(row["pct_5"])}

            if delta > 0:
                actual = min(delta, 100 - values[pack_size])
                needed = actual
                for other in sorted(
                    (p for p in values if p != pack_size),
                    key=lambda p: values[p],
                    reverse=True,
                ):
                    take = min(needed, values[other])
                    values[other] -= take
                    values[pack_size] += take
                    needed -= take
                    if needed <= 0:
                        break
            else:
                actual = min(-delta, values[pack_size])
                values[pack_size] -= actual
                other = max((p for p in values if p != pack_size), key=lambda p: values[p])
                values[other] += actual

            conn.execute(
                """UPDATE shop_packaging_rules
                   SET pct_1=?, pct_2=?, pct_5=?, updated_at=CURRENT_TIMESTAMP
                   WHERE player_id=?""",
                (values[1], values[2], values[5], player_id),
            )
            conn.execute(
                """UPDATE packaging_rules
                   SET pct_1=?, pct_2=?, pct_5=?
                   WHERE player_id=?""",
                (values[1], values[2], values[5], player_id),
            )

        return f"×1 {values[1]}% · ×2 {values[2]}% · ×5 {values[5]}%"

    def adjust_packaging_rule(
        self,
        player_id: int,
        employee_id: int,
        product_id: int,
        pack_size: int,
        delta: int,
    ) -> str:
        # Backward compatibility for stale Telegram buttons: they now change the
        # same global rule instead of creating a per-employee/per-product exception.
        return self.adjust_global_packaging_rule(player_id, pack_size, delta)

    def change_employee_role(self, player_id: int, employee_id: int) -> str:
        result = super().change_employee_role(player_id, employee_id)
        self.simulation._ensure_packaging_rules(player_id)
        return result
