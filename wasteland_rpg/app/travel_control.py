from __future__ import annotations

from .content import LOCATIONS, ROUTES
from .game import GameError


def turn_travel(game, telegram_id: int) -> dict:
    """Reverse the current road direction without teleporting the player.

    `travel.step` is the position measured from `origin_id` toward `target_id`.
    Reversing the route swaps the endpoints and mirrors the position, so the
    existing forward-only road event logic can keep working unchanged.
    """
    run_id = game._active_run_id(telegram_id, "travel") if hasattr(game, "_active_run_id") else None

    with game.db.connect() as conn:
        player = game._player(conn, telegram_id)
        if player["state"] != "travel":
            raise GameError("Сейчас ты не в дороге.")

        travel = conn.execute(
            "SELECT * FROM travel WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not travel:
            raise GameError("Маршрут не найден.")

        route_id = str(travel["route_id"])
        route = ROUTES[route_id]
        stages = int(route["stages"])
        old_step = int(travel["step"])
        old_origin_id = str(travel["origin_id"])
        old_target_id = str(travel["target_id"])

        # The player has not crossed a road section yet. Returning is just
        # cancelling the departure: no encounter and no cargo loss.
        if old_step <= 0:
            conn.execute(
                "UPDATE player_world SET location_id = ? WHERE telegram_id = ?",
                (old_origin_id, telegram_id),
            )
            conn.execute(
                "UPDATE players SET state = 'base', hp = ?, pending_event = NULL, "
                "threat = 0, steps = 0 WHERE telegram_id = ?",
                (game.max_hp(player), telegram_id),
            )
            conn.execute("DELETE FROM travel WHERE telegram_id = ?", (telegram_id,))
            result = {
                "kind": "returned",
                "arrived": True,
                "turned": True,
                "immediate": True,
                "route_id": route_id,
                "destination_id": old_origin_id,
                "step": 0,
                "remaining": 0,
                "text": (
                    f"Ты решил не продолжать путь и вернулся в "
                    f"{LOCATIONS[old_origin_id]['icon']} {LOCATIONS[old_origin_id]['name']}."
                ),
            }
        else:
            new_step = max(0, min(stages, stages - old_step))
            conn.execute(
                "UPDATE travel SET origin_id = ?, target_id = ?, step = ? "
                "WHERE telegram_id = ?",
                (old_target_id, old_origin_id, new_step, telegram_id),
            )
            result = {
                "kind": "turned",
                "arrived": False,
                "turned": True,
                "immediate": False,
                "route_id": route_id,
                "destination_id": old_origin_id,
                "previous_target_id": old_target_id,
                "step": new_step,
                "remaining": stages - new_step,
                "text": (
                    f"Ты развернулся. Теперь путь ведёт к "
                    f"{LOCATIONS[old_origin_id]['icon']} {LOCATIONS[old_origin_id]['name']}. "
                    f"До города: {stages - new_step} участков."
                ),
            }

    if hasattr(game, "track_event"):
        game.track_event(
            telegram_id,
            "travel_turned",
            context="travel",
            run_id=run_id,
            entity_id=result["route_id"],
            value=int(result["remaining"]),
            metadata={
                "from_target_id": old_target_id,
                "to_target_id": old_origin_id,
                "step_before": old_step,
                "step_after": int(result["step"]),
                "immediate_return": bool(result["immediate"]),
            },
        )
        if result["immediate"]:
            game.track_event(
                telegram_id,
                "travel_finished",
                context="travel",
                run_id=run_id,
                entity_id=result["route_id"],
                metadata={
                    "target_id": old_origin_id,
                    "steps": 0,
                    "outcome": "returned_before_first_section",
                },
            )

    return result
