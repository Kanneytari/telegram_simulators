from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.game import GameService
from app.session import SessionService


class SessionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.sqlite3"))
        self.db.init()
        self.game = GameService(self.db, random.Random(11))
        self.player_id = 777
        self.game.ensure_player(self.player_id, "session_tester")
        self.session = SessionService(self.game, random.Random(12))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inbox_has_six_items(self) -> None:
        progress = self.session.inbox_progress(self.player_id)
        self.assertEqual(progress["total"], 6)
        self.assertEqual(progress["unread"], 6)

    def test_resolving_inbox_does_not_spend_action(self) -> None:
        before = self.game.get_player(self.player_id)["actions_left"]
        item = self.session.next_inbox_item(self.player_id)
        self.session.resolve_inbox(self.player_id, item["slot"], 0)
        after = self.game.get_player(self.player_id)["actions_left"]
        self.assertEqual(before, after)
        self.assertEqual(self.session.inbox_progress(self.player_id)["unread"], 5)

    def test_focus_spends_one_action_and_has_three_steps(self) -> None:
        before = self.game.get_player(self.player_id)["actions_left"]
        self.session.start_focus(self.player_id)
        self.assertEqual(self.game.get_player(self.player_id)["actions_left"], before - 1)

        first = self.session.resolve_focus(self.player_id, 0)
        second = self.session.resolve_focus(self.player_id, 1)
        third = self.session.resolve_focus(self.player_id, 2)
        self.assertFalse(first["finished"])
        self.assertFalse(second["finished"])
        self.assertTrue(third["finished"])

    def test_only_two_focus_runs_per_day(self) -> None:
        for _ in range(2):
            self.session.start_focus(self.player_id)
            for _ in range(3):
                self.session.resolve_focus(self.player_id, 1)
        self.assertEqual(self.session.focus_runs_left(self.player_id), 0)
        with self.assertRaises(Exception):
            self.session.start_focus(self.player_id)

    def test_inbox_choice_cannot_be_repeated(self) -> None:
        item = self.session.next_inbox_item(self.player_id)
        self.session.resolve_inbox(self.player_id, item["slot"], 0)
        with self.assertRaises(Exception):
            self.session.resolve_inbox(self.player_id, item["slot"], 1)


if __name__ == "__main__":
    unittest.main()
