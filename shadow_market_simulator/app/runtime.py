from __future__ import annotations

from .simulation import SimulationEngine, TickResult, iso, parse_dt, utcnow


class PlayerSimulationEngine(SimulationEngine):
    def player_multiplier(self, player_id: int) -> float:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return max(0.1, float(row[0])) if row else 1.0

    def effective_speed(self, player_id: int) -> float:
        return max(0.1, float(self.speed) * self.player_multiplier(player_id))

    def advance(self, player_id: int, now=None) -> TickResult:
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if not shop:
                return TickResult()
            last = parse_dt(shop["last_simulated_at"])
            real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            sim_hours = min(real_hours * self.effective_speed(player_id), 72.0)
            if sim_hours < 0.015:
                return TickResult()
            orders, disputes = self._simulate_sales(conn, player_id, shop, sim_hours, now)
            messages = self._simulate_management_events(conn, player_id, sim_hours, now)
            self._reactivate_employees(conn, player_id, now)
            self._expire_items(conn, player_id, now)
            self._maybe_refresh_offer(conn, player_id, now)
            conn.execute(
                "UPDATE shops SET last_simulated_at=?, last_seen_at=? WHERE player_id=?",
                (iso(now), iso(now), player_id),
            )
            return TickResult(orders, disputes, messages)
