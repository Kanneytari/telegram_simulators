from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
            conn.execute("UPDATE players SET money = 20000 WHERE telegram_id = ?", (self.player_id,))
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


if __name__ == "__main__":
    unittest.main()
