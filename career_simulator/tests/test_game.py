from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.admin import AdminError, AdminService
from app.db import Database
from app.game import GameService


class GameServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmp.name) / "test.sqlite3")
        self.db = Database(db_path)
        self.db.init()
        self.game = GameService(self.db, random.Random(7))
        self.player_id = 123
        self.game.ensure_player(self.player_id, "tester")
        self.admin = AdminService(self.db, self.game, {self.player_id})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_new_player_has_project_and_actions(self) -> None:
        player = self.game.get_player(self.player_id)
        project = self.game.get_active_project(self.player_id)
        self.assertEqual(player["actions_left"], 5)
        self.assertEqual(player["career_day"], 1)
        self.assertIsNotNone(project)

    def test_action_spends_one_action(self) -> None:
        before = self.game.get_player(self.player_id)
        self.game.perform_action(self.player_id, "learn")
        after = self.game.get_player(self.player_id)
        self.assertEqual(after["actions_left"], before["actions_left"] - 1)
        self.assertGreater(after["skill"], before["skill"])

    def test_daily_event_can_only_be_resolved_once(self) -> None:
        event = self.game.get_daily_event(self.player_id)
        self.game.resolve_event(self.player_id, event["id"], 0)
        with self.assertRaises(Exception):
            self.game.resolve_event(self.player_id, event["id"], 1)

    def test_only_one_investment_per_day(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE players SET money = 20000 WHERE telegram_id = ?",
                (self.player_id,),
            )
        self.game.buy_investment(self.player_id, "course")
        with self.assertRaises(Exception):
            self.game.buy_investment(self.player_id, "portfolio")

    def test_showing_empty_work_hurts_reputation(self) -> None:
        before = self.game.get_player(self.player_id)
        self.game.perform_action(self.player_id, "show")
        after = self.game.get_player(self.player_id)
        self.assertLess(after["reputation"], before["reputation"])

    def test_game_day_resets_at_four_moscow(self) -> None:
        tz = ZoneInfo("Europe/Moscow")
        before_reset = datetime(2026, 8, 22, 3, 59, tzinfo=tz)
        after_reset = datetime(2026, 8, 22, 4, 1, tzinfo=tz)
        self.assertEqual(self.game.game_day_key(before_reset), "2026-08-21")
        self.assertEqual(self.game.game_day_key(after_reset), "2026-08-22")

    def test_fast_day_requires_all_actions_spent(self) -> None:
        self.admin.set_fast_mode(self.player_id, True)
        with self.assertRaises(AdminError):
            self.admin.advance_day(self.player_id)

    def test_fast_day_advances_and_restores_actions(self) -> None:
        self.admin.set_fast_mode(self.player_id, True)
        for _ in range(5):
            self.game.perform_action(self.player_id, "rest")

        before = self.game.get_player(self.player_id)
        self.admin.advance_day(self.player_id)
        after = self.game.get_player(self.player_id)

        self.assertEqual(after["career_day"], before["career_day"] + 1)
        self.assertEqual(after["actions_left"], 5)

    def test_fast_day_keeps_previous_daily_records(self) -> None:
        self.admin.set_fast_mode(self.player_id, True)
        event = self.game.get_daily_event(self.player_id)
        self.game.resolve_event(self.player_id, event["id"], 0)

        for _ in range(5):
            self.game.perform_action(self.player_id, "rest")
        self.admin.advance_day(self.player_id)

        with self.db.connect() as conn:
            archived = conn.execute(
                """
                SELECT 1 FROM daily_events
                WHERE player_id = ? AND day_key = 'fast:1'
                """,
                (self.player_id,),
            ).fetchone()
        self.assertIsNotNone(archived)

        next_event = self.game.get_daily_event(self.player_id)
        self.assertIsNone(next_event["choice_index"])

    def test_reset_preserves_fast_mode(self) -> None:
        self.admin.set_fast_mode(self.player_id, True)
        self.admin.reset_player(self.player_id)
        self.game.ensure_player(self.player_id, "tester")

        player = self.game.get_player(self.player_id)
        self.assertEqual(player["career_day"], 1)
        self.assertEqual(player["money"], 2500)
        self.assertTrue(self.admin.is_fast_mode(self.player_id))


if __name__ == "__main__":
    unittest.main()
