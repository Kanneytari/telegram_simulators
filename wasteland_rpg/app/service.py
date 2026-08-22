from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from .content import ENEMIES, SECTORS
from .game import GameError
from .gameplay import GameService as GameplayService
from .progression import level_from_xp, progress_from_xp, xp_required_for_next
from .sector_progression import SECTOR_NEXT, SECTOR_PREVIOUS


ANALYTICS_GAME_VERSION = "2026-08-23.1"


class GameService(GameplayService):
    """Runtime game service with progression, sector mastery and analytics."""

    # --- analytics -------------------------------------------------------

    def _analytics_event_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        event_name: str,
        *,
        context: str | None = None,
        run_id: str | None = None,
        entity_id: str | None = None,
        value: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        payload: dict = {}
        player = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if player:
            payload.update(
                {
                    "state": str(player["state"]),
                    "level": int(self.level(player)),
                    "xp": int(player["xp"]),
                    "hp": int(player["hp"]),
                    "credits": int(player["credits"]),
                    "ammo": int(player["ammo"]),
                    "medkits": int(player["medkits"]),
                    "threat": int(player["threat"]),
                    "steps": int(player["steps"]),
                    "weapon_id": str(player["weapon_id"]),
                    "armor_id": str(player["armor_id"]),
                }
            )
            location = conn.execute(
                "SELECT location_id FROM player_world WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if location:
                payload["location_id"] = str(location["location_id"])
        if metadata:
            payload.update(metadata)

        conn.execute(
            "INSERT INTO analytics_events "
            "(telegram_id, event_name, context, run_id, entity_id, value, metadata, game_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                telegram_id,
                event_name,
                context,
                run_id,
                entity_id,
                value,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ANALYTICS_GAME_VERSION,
            ),
        )

    def track_event(
        self,
        telegram_id: int,
        event_name: str,
        *,
        context: str | None = None,
        run_id: str | None = None,
        entity_id: str | None = None,
        value: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self.db.connect() as conn:
            self._analytics_event_conn(
                conn,
                telegram_id,
                event_name,
                context=context,
                run_id=run_id,
                entity_id=entity_id,
                value=value,
                metadata=metadata,
            )

    def analytics_events(self, telegram_id: int | None = None) -> list[dict]:
        with self.db.connect() as conn:
            if telegram_id is None:
                rows = conn.execute("SELECT * FROM analytics_events ORDER BY id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analytics_events WHERE telegram_id = ? ORDER BY id",
                    (telegram_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _new_run_id(context: str) -> str:
        return f"{context}:{uuid4().hex}"

    def _active_run_id_conn(
        self, conn: sqlite3.Connection, telegram_id: int, context: str
    ) -> str | None:
        start_event = "expedition_started" if context == "expedition" else "travel_started"
        row = conn.execute(
            "SELECT run_id FROM analytics_events "
            "WHERE telegram_id = ? AND event_name = ? AND run_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (telegram_id, start_event),
        ).fetchone()
        return str(row["run_id"]) if row and row["run_id"] else None

    def _active_run_id(self, telegram_id: int, context: str) -> str | None:
        with self.db.connect() as conn:
            return self._active_run_id_conn(conn, telegram_id, context)

    def _log_combat_started(self, telegram_id: int, parent_context: str, run_id: str | None) -> None:
        player = self.get_player(telegram_id)
        if player["state"] != "combat" or not player["enemy_id"]:
            return
        combat = self.combat_state(telegram_id)
        self.track_event(
            telegram_id,
            "combat_started",
            context="combat",
            run_id=run_id,
            entity_id=str(player["enemy_id"]),
            metadata={
                "parent_context": parent_context,
                "enemy_hp": int(player["enemy_hp"] or 0),
                "distance": int(combat["distance"]),
            },
        )

    def _log_player_death(
        self,
        telegram_id: int,
        *,
        parent_context: str,
        run_id: str | None,
        cause: str,
        metadata: dict | None = None,
    ) -> None:
        payload = {"cause": cause}
        if metadata:
            payload.update(metadata)
        self.track_event(
            telegram_id,
            "player_died",
            context=parent_context,
            run_id=run_id,
            entity_id=cause,
            metadata=payload,
        )

    def ensure_player(self, telegram_id: int, username: str | None = None) -> None:
        with self.db.connect() as conn:
            existed = bool(
                conn.execute(
                    "SELECT 1 FROM players WHERE telegram_id = ?", (telegram_id,)
                ).fetchone()
            )
            had_history = bool(
                conn.execute(
                    "SELECT 1 FROM analytics_events WHERE telegram_id = ? LIMIT 1",
                    (telegram_id,),
                ).fetchone()
            )
        super().ensure_player(telegram_id, username)
        if not existed:
            self.track_event(
                telegram_id,
                "character_recreated" if had_history else "player_created",
                context="system",
            )

    # --- progression -----------------------------------------------------

    def level(self, player) -> int:
        return level_from_xp(int(player["xp"]))

    def xp_progress(self, player) -> tuple[int, int]:
        return progress_from_xp(int(player["xp"]))

    def xp_needed_for_next_level(self, player) -> int:
        return xp_required_for_next(self.level(player))

    def upgrade_attribute(self, telegram_id: int, attribute: str) -> str:
        message = super().upgrade_attribute(telegram_id, attribute)
        player = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "attribute_upgraded",
            context="character",
            entity_id=attribute,
            value=int(player[attribute]),
        )
        return message

    # --- sector progression ---------------------------------------------

    def sector_max_threat(self, telegram_id: int, sector_id: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT max_threat FROM sector_progress WHERE telegram_id = ? AND sector_id = ?",
                (telegram_id, sector_id),
            ).fetchone()
        return int(row["max_threat"]) if row else 0

    def sector_mastered(self, telegram_id: int, sector_id: str) -> bool:
        return self.sector_max_threat(telegram_id, sector_id) >= 100

    def sector_unlocked(self, player, sector_id: str) -> bool:
        if sector_id not in SECTORS:
            return False
        sector = SECTORS[sector_id]
        telegram_id = int(player["telegram_id"])
        if self.location_id(telegram_id) != sector["hub"]:
            return False
        previous = SECTOR_PREVIOUS.get(sector_id)
        return previous is None or self.sector_mastered(telegram_id, previous)

    def sector_unlock_requirement(self, sector_id: str) -> str | None:
        previous = SECTOR_PREVIOUS.get(sector_id)
        if previous is None:
            return None
        return SECTORS[previous]["name"]

    # --- expeditions -----------------------------------------------------

    def start_expedition(self, telegram_id: int, sector_id: str) -> str:
        message = super().start_expedition(telegram_id, sector_id)
        run_id = self._new_run_id("expedition")
        self.track_event(
            telegram_id,
            "expedition_started",
            context="expedition",
            run_id=run_id,
            entity_id=sector_id,
        )
        return message

    def explore(self, telegram_id: int) -> dict:
        before = self.get_player(telegram_id)
        sector_id = before.get("sector_id")
        run_id = self._active_run_id(telegram_id, "expedition")
        before_state = str(before["state"])
        result = super().explore(telegram_id)
        if not sector_id:
            return result

        player = self.get_player(telegram_id)
        threat = int(player["threat"])
        newly_mastered = self._record_sector_progress(telegram_id, str(sector_id), threat)

        self.track_event(
            telegram_id,
            "expedition_explored",
            context="expedition",
            run_id=run_id,
            entity_id=str(sector_id),
            value=threat,
            metadata={
                "event_kind": str(result.get("kind", "unknown")),
                "threat_before": int(before["threat"]),
                "threat_after": threat,
                "step": int(player["steps"]),
            },
        )

        if before_state != "combat" and player["state"] == "combat":
            self._log_combat_started(telegram_id, "expedition", run_id)

        if newly_mastered:
            next_sector_id = SECTOR_NEXT.get(str(sector_id))
            self.track_event(
                telegram_id,
                "sector_completed",
                context="expedition",
                run_id=run_id,
                entity_id=str(sector_id),
                value=100,
                metadata={"unlocked_sector_id": next_sector_id},
            )
            if next_sector_id:
                next_sector = SECTORS[next_sector_id]
                result["progress_notice"] = (
                    f"Сектор пройден\nОткрыта новая локация: {next_sector['name']}"
                )
            else:
                result["progress_notice"] = "Сектор пройден"
        return result

    def resolve_choice(self, telegram_id: int, action: str) -> dict:
        before = self.get_player(telegram_id)
        scene = self.pending_scene(telegram_id)
        run_id = self._active_run_id(telegram_id, "expedition")
        result = super().resolve_choice(telegram_id, action)
        after = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "scene_choice",
            context="expedition",
            run_id=run_id,
            entity_id=scene,
            metadata={
                "action": action,
                "combat_started": bool(result.get("combat")),
                "success": result.get("success"),
                "dead": bool(result.get("dead")),
                "hp_before": int(before["hp"]),
            },
        )
        if before["state"] != "combat" and after["state"] == "combat":
            self._log_combat_started(telegram_id, "expedition", run_id)
        if result.get("dead"):
            self._log_player_death(
                telegram_id,
                parent_context="expedition",
                run_id=run_id,
                cause=f"scene:{scene or 'unknown'}",
                metadata={"hp_before": int(before["hp"]), "threat": int(before["threat"])},
            )
        return result

    def resolve_event(self, telegram_id: int, action: str) -> dict:
        before = self.get_player(telegram_id)
        event_id = str(before.get("pending_event") or "unknown")
        run_id = self._active_run_id(telegram_id, "expedition")
        result = super().resolve_event(telegram_id, action)
        self.track_event(
            telegram_id,
            "special_event_resolved",
            context="expedition",
            run_id=run_id,
            entity_id=event_id,
            metadata={
                "action": action,
                "success": result.get("success"),
                "dead": bool(result.get("dead")),
                "hp_before": int(before["hp"]),
            },
        )
        if result.get("dead"):
            self._log_player_death(
                telegram_id,
                parent_context="expedition",
                run_id=run_id,
                cause=f"event:{event_id}",
                metadata={"hp_before": int(before["hp"]), "threat": int(before["threat"])},
            )
        return result

    def return_base(self, telegram_id: int) -> dict:
        before = self.get_player(telegram_id)
        run_id = self._active_run_id(telegram_id, "expedition")
        sector_id = str(before.get("sector_id") or "unknown")
        result = super().return_base(telegram_id)
        self.track_event(
            telegram_id,
            "expedition_returned",
            context="expedition",
            run_id=run_id,
            entity_id=sector_id,
            value=int(result.get("value", 0)),
            metadata={
                "final_threat": int(before["threat"]),
                "steps": int(before["steps"]),
            },
        )
        return result

    def _record_sector_progress(self, telegram_id: int, sector_id: str, threat: int) -> bool:
        threat = max(0, min(100, int(threat)))
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT max_threat FROM sector_progress WHERE telegram_id = ? AND sector_id = ?",
                (telegram_id, sector_id),
            ).fetchone()
            old_max = int(row["max_threat"]) if row else 0
            conn.execute(
                "INSERT INTO sector_progress (telegram_id, sector_id, max_threat) VALUES (?, ?, ?) "
                "ON CONFLICT (telegram_id, sector_id) DO UPDATE SET "
                "max_threat = MAX(max_threat, excluded.max_threat)",
                (telegram_id, sector_id, threat),
            )
        return old_max < 100 <= threat

    # --- travel ----------------------------------------------------------

    def start_travel(self, telegram_id: int, route_id: str) -> str:
        origin = self.location_id(telegram_id)
        message = super().start_travel(telegram_id, route_id)
        travel = self.travel_state(telegram_id)
        run_id = self._new_run_id("travel")
        self.track_event(
            telegram_id,
            "travel_started",
            context="travel",
            run_id=run_id,
            entity_id=route_id,
            metadata={
                "origin_id": origin,
                "target_id": str(travel["target_id"]) if travel else None,
            },
        )
        return message

    def advance_travel(self, telegram_id: int) -> dict:
        before_player = self.get_player(telegram_id)
        before_travel = self.travel_state(telegram_id)
        run_id = self._active_run_id(telegram_id, "travel")
        result = super().advance_travel(telegram_id)
        after_player = self.get_player(telegram_id)
        after_travel = self.travel_state(telegram_id)
        route_id = str(before_travel["route_id"]) if before_travel else "unknown"
        step = (
            int(after_travel["step"])
            if after_travel
            else int(before_travel["step"]) if before_travel else 0
        )
        self.track_event(
            telegram_id,
            "travel_advanced",
            context="travel",
            run_id=run_id,
            entity_id=route_id,
            value=step,
            metadata={"event_kind": str(result.get("kind", "unknown"))},
        )
        if before_player["state"] != "combat" and after_player["state"] == "combat":
            self._log_combat_started(telegram_id, "travel", run_id)
        if result.get("arrived"):
            self.track_event(
                telegram_id,
                "travel_finished",
                context="travel",
                run_id=run_id,
                entity_id=route_id,
                metadata={
                    "target_id": self.location_id(telegram_id),
                    "steps": step,
                },
            )
        return result

    # --- economy ---------------------------------------------------------

    def buy_trade_good(self, telegram_id: int, item_id: str) -> str:
        before = self.get_player(telegram_id)
        location_id = self.location_id(telegram_id)
        message = super().buy_trade_good(telegram_id, item_id)
        after = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "market_bought",
            context="market",
            entity_id=item_id,
            value=int(before["credits"]) - int(after["credits"]),
            metadata={"location_id": location_id, "qty": 1},
        )
        return message

    def sell_cargo(self, telegram_id: int) -> str:
        before = self.get_player(telegram_id)
        location_id = self.location_id(telegram_id)
        cargo = self.cargo(telegram_id)
        message = super().sell_cargo(telegram_id)
        after = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "market_sold_cargo",
            context="market",
            value=int(after["credits"]) - int(before["credits"]),
            metadata={
                "location_id": location_id,
                "items": {str(row["item_id"]): int(row["qty"]) for row in cargo},
            },
        )
        return message

    def load_stash_to_cargo(self, telegram_id: int) -> str:
        before_qty = sum(int(row["qty"]) for row in self.cargo(telegram_id))
        message = super().load_stash_to_cargo(telegram_id)
        after_qty = sum(int(row["qty"]) for row in self.cargo(telegram_id))
        self.track_event(
            telegram_id,
            "stash_loaded_to_cargo",
            context="market",
            value=max(0, after_qty - before_qty),
        )
        return message

    def unload_cargo(self, telegram_id: int) -> str:
        before_qty = sum(int(row["qty"]) for row in self.cargo(telegram_id))
        message = super().unload_cargo(telegram_id)
        self.track_event(
            telegram_id,
            "cargo_unloaded_to_stash",
            context="market",
            value=before_qty,
        )
        return message

    def sell_all(self, telegram_id: int) -> str:
        before = self.get_player(telegram_id)
        location_id = self.location_id(telegram_id)
        stash = self.inventory(telegram_id, secured=1)
        message = super().sell_all(telegram_id)
        after = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "stash_sold",
            context="shop",
            value=int(after["credits"]) - int(before["credits"]),
            metadata={
                "location_id": location_id,
                "items": {str(row["item_id"]): int(row["qty"]) for row in stash},
            },
        )
        return message

    def buy(self, telegram_id: int, product: str) -> str:
        before = self.get_player(telegram_id)
        message = super().buy(telegram_id, product)
        after = self.get_player(telegram_id)
        self.track_event(
            telegram_id,
            "shop_bought",
            context="shop",
            entity_id=product,
            value=int(before["credits"]) - int(after["credits"]),
        )
        return message

    # --- inventory safety helpers ---------------------------------------

    def _change_item(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        item_id: str,
        qty: int,
        *,
        secured: int,
    ) -> None:
        """Change inventory quantity without ever inserting a negative CHECK value."""
        qty = int(qty)
        if qty > 0:
            conn.execute(
                "INSERT INTO inventory (telegram_id, item_id, secured, qty) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (telegram_id, item_id, secured) DO UPDATE SET qty = qty + excluded.qty",
                (telegram_id, item_id, secured, qty),
            )
        elif qty < 0:
            conn.execute(
                "UPDATE inventory SET qty = MAX(0, qty + ?) "
                "WHERE telegram_id = ? AND item_id = ? AND secured = ?",
                (qty, telegram_id, item_id, secured),
            )
        conn.execute(
            "DELETE FROM inventory WHERE telegram_id = ? AND item_id = ? AND secured = ? AND qty <= 0",
            (telegram_id, item_id, secured),
        )

    def _change_cargo(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        item_id: str,
        qty: int,
    ) -> None:
        """Change cargo quantity without violating the non-negative CHECK constraint."""
        qty = int(qty)
        if qty > 0:
            conn.execute(
                "INSERT INTO cargo (telegram_id, item_id, qty) VALUES (?, ?, ?) "
                "ON CONFLICT (telegram_id, item_id) DO UPDATE SET qty = qty + excluded.qty",
                (telegram_id, item_id, qty),
            )
        elif qty < 0:
            conn.execute(
                "UPDATE cargo SET qty = MAX(0, qty + ?) WHERE telegram_id = ? AND item_id = ?",
                (qty, telegram_id, item_id),
            )
        conn.execute(
            "DELETE FROM cargo WHERE telegram_id = ? AND item_id = ? AND qty <= 0",
            (telegram_id, item_id),
        )

    # --- turn-based combat ----------------------------------------------

    def combat_action(self, telegram_id: int, action: str) -> dict:
        before = self.get_player(telegram_id)
        combat_before = self.combat_state(telegram_id)
        parent_context = str(combat_before.get("return_state") or "expedition")
        run_id = self._active_run_id(telegram_id, parent_context)
        enemy_id = str(before.get("enemy_id") or "unknown")
        enemy_hp_before = int(before.get("enemy_hp") or 0)
        hp_before = int(before["hp"])
        ammo_before = int(before["ammo"])
        medkits_before = int(before["medkits"])

        if action == "wait":
            result = self._combat_wait(telegram_id)
        else:
            result = super().combat_action(telegram_id, action)

        after = self.get_player(telegram_id)
        terminal_without_enemy_hp = bool(result.get("fled") or result.get("dead"))
        enemy_hp_after = (
            enemy_hp_before
            if terminal_without_enemy_hp
            else int(after.get("enemy_hp") or 0)
        )
        damage_known = not terminal_without_enemy_hp
        damage_dealt = max(0, enemy_hp_before - enemy_hp_after) if damage_known else 0
        self.track_event(
            telegram_id,
            "combat_action",
            context="combat",
            run_id=run_id,
            entity_id=action,
            value=damage_dealt,
            metadata={
                "enemy_id": enemy_id,
                "parent_context": parent_context,
                "hp_before": hp_before,
                "hp_after": int(after["hp"]),
                "ammo_before": ammo_before,
                "ammo_after": int(after["ammo"]),
                "medkits_before": medkits_before,
                "medkits_after": int(after["medkits"]),
                "damage_known": damage_known,
                "won": bool(result.get("won")),
                "fled": bool(result.get("fled")),
                "dead": bool(result.get("dead")),
            },
        )

        if result.get("won") or result.get("fled") or result.get("dead"):
            outcome = "victory" if result.get("won") else "fled" if result.get("fled") else "death"
            self.track_event(
                telegram_id,
                "combat_finished",
                context="combat",
                run_id=run_id,
                entity_id=enemy_id,
                metadata={"outcome": outcome, "parent_context": parent_context},
            )
        if result.get("dead"):
            self._log_player_death(
                telegram_id,
                parent_context=parent_context,
                run_id=run_id,
                cause=f"combat:{enemy_id}",
                metadata={
                    "hp_before_action": hp_before,
                    "ammo_before_action": ammo_before,
                    "medkits_before_action": medkits_before,
                },
            )
        return result

    def _combat_wait(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                raise GameError("Бой уже закончен.")

            combat = conn.execute(
                "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not combat:
                raise GameError("Состояние боя потеряно.")
            if int(player["ammo"]) > 0:
                raise GameError("Ждать можно только когда закончились патроны.")
            if int(combat["distance"]) <= 1:
                raise GameError("Противник уже вплотную — используй ближний бой.")

            lines: list[str] = []
            if int(combat["bleeding"]) > 0:
                bleed_damage = int(combat["bleeding"])
                hp = int(player["hp"]) - bleed_damage
                lines.append(f"🩸 Кровотечение: -{bleed_damage} HP.")
                if hp <= 0:
                    lines.append(self._kill(conn, telegram_id))
                    return {"text": "\n".join(lines), "dead": True}
                conn.execute(
                    "UPDATE players SET hp = ? WHERE telegram_id = ?", (hp, telegram_id)
                )

            enemy = ENEMIES[player["enemy_id"]]
            new_distance = max(1, int(combat["distance"]) - 1)
            conn.execute(
                "UPDATE combat_state SET distance = ?, cover = 0 WHERE telegram_id = ?",
                (new_distance, telegram_id),
            )
            lines.append(f"Ты выжидаешь. {enemy['name']} сокращает дистанцию.")
            if new_distance == 1:
                lines.append("Противник подошёл вплотную — теперь доступен ближний бой.")
            return {"text": "\n".join(lines)}
