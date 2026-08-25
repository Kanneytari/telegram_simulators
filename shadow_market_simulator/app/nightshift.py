from __future__ import annotations

from datetime import timedelta

from .simulation import iso, parse_dt, utcnow


class NightshiftSimulationMixin:
    """Personal game-time and timer scaling for a cooperative simulation MRO."""

    def effective_speed(self, player_id: int) -> float:
        # /speed is absolute relative to standard time: x60 == one game hour per real minute.
        return self.player_multiplier(player_id)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE settings SET last_payroll_at=COALESCE(last_payroll_at, ?) WHERE player_id=?",
                (iso(utcnow()), player_id),
            )
        return created

    def advance(self, player_id: int, now=None):
        now = now or utcnow()
        with self.db.connect() as conn:
            before = {
                "inbox": conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM inbox WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0],
                "disputes": conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM disputes WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0],
                "offers": conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM supplier_offers WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0],
            }
        result = super().advance(player_id, now)
        self._scale_new_timers(player_id, before, now)
        return result

    def _scale_new_timers(self, player_id: int, before: dict[str, int], now) -> None:
        speed = self.effective_speed(player_id)
        if abs(speed - 1.0) < 0.0001:
            return
        with self.db.connect() as conn:
            self._scale_rows_after_id(
                conn, "inbox", "expires_at", player_id, before["inbox"], now, speed
            )
            self._scale_rows_after_id(
                conn,
                "disputes",
                "deadline_at",
                player_id,
                before["disputes"],
                now,
                speed,
            )
            self._scale_rows_after_id(
                conn,
                "supplier_offers",
                "expires_at",
                player_id,
                before["offers"],
                now,
                speed,
            )

    @staticmethod
    def _scale_rows_after_id(
        conn,
        table: str,
        column: str,
        player_id: int,
        after_id: int,
        now,
        speed: float,
    ) -> None:
        rows = conn.execute(
            f"SELECT id, {column} FROM {table} WHERE player_id=? AND id>? AND {column} IS NOT NULL",
            (player_id, after_id),
        ).fetchall()
        for row in rows:
            target = parse_dt(row[column])
            remaining = max(0.0, (target - now).total_seconds())
            conn.execute(
                f"UPDATE {table} SET {column}=? WHERE id=?",
                (iso(now + timedelta(seconds=remaining / speed)), row["id"]),
            )

    def rescale_existing_timers(
        self,
        player_id: int,
        old_speed: float,
        new_speed: float,
        now=None,
    ) -> None:
        """Preserve remaining game-time duration when /speed changes."""
        now = now or utcnow()
        old_speed = max(0.1, float(old_speed))
        new_speed = max(0.1, float(new_speed))
        with self.db.connect() as conn:
            targets = (
                ("inbox", "expires_at", "status='open'"),
                ("disputes", "deadline_at", "status='open'"),
                ("supplier_offers", "expires_at", "status='open'"),
                ("candidates", "expires_at", "status='open'"),
                ("employees", "unavailable_until", "active=1 AND available=0"),
            )
            for table, column, condition in targets:
                rows = conn.execute(
                    f"SELECT id, {column} FROM {table} WHERE player_id=? AND {condition} AND {column} IS NOT NULL",
                    (player_id,),
                ).fetchall()
                for row in rows:
                    target = parse_dt(row[column])
                    remaining_real = max(0.0, (target - now).total_seconds())
                    remaining_game = remaining_real * old_speed
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=?",
                        (
                            iso(
                                now
                                + timedelta(
                                    seconds=remaining_game / new_speed
                                )
                            ),
                            row["id"],
                        ),
                    )

    def fast_forward_timers(self, player_id: int, game_hours: float) -> None:
        """Move existing gameplay deadlines forward for the admin /tick helper."""
        speed = self.effective_speed(player_id)
        shift = timedelta(hours=max(0.0, game_hours) / speed)
        with self.db.connect() as conn:
            targets = (
                ("inbox", "expires_at", "status='open'"),
                ("disputes", "deadline_at", "status='open'"),
                ("supplier_offers", "expires_at", "status='open'"),
                ("candidates", "expires_at", "status='open'"),
                ("employees", "unavailable_until", "active=1 AND available=0"),
            )
            for table, column, condition in targets:
                rows = conn.execute(
                    f"SELECT id, {column} FROM {table} WHERE player_id=? AND {condition} AND {column} IS NOT NULL",
                    (player_id,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=?",
                        (iso(parse_dt(row[column]) - shift), row["id"]),
                    )

    def _expire_items(self, conn, player_id: int, now) -> None:
        super()._expire_items(conn, player_id, now)
        auto_resolved = conn.execute(
            """SELECT d.id, o.revenue
               FROM disputes d JOIN orders o ON o.id=d.order_id
               WHERE d.player_id=? AND d.decision='auto_partial'
                 AND d.refund_source IS NULL""",
            (player_id,),
        ).fetchall()
        for row in auto_resolved:
            conn.execute(
                """UPDATE disputes
                   SET refund_amount=?, refund_source='shop', refund_employee_id=NULL
                   WHERE id=?""",
                (int(row["revenue"] * 0.5), row["id"]),
            )


__all__ = ["NightshiftSimulationMixin"]
