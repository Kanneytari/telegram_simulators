from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.game import GameService
from app.opportunities import OpportunityService
from app.project_play import ProjectPlayService


class EngagementMechanicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.sqlite3"))
        self.db.init()
        self.game = GameService(self.db, random.Random(7))
        self.player_id = 321
        self.game.ensure_player(self.player_id, "tester")
        self.projects = ProjectPlayService(self.game, random.Random(11))
        self.opportunities = OpportunityService(self.game, random.Random(13))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fast_project_work_spends_action_and_adds_risk(self) -> None:
        before_player = self.game.get_player(self.player_id)
        before_project = self.projects.state(self.player_id)

        self.projects.work(self.player_id, "fast")

        after_player = self.game.get_player(self.player_id)
        after_project = self.projects.state(self.player_id)
        self.assertEqual(after_player["actions_left"], before_player["actions_left"] - 1)
        self.assertGreater(after_project["progress"], before_project["progress"])
        self.assertGreater(after_project["risk"], before_project["risk"])

    def test_careful_project_work_adds_quality(self) -> None:
        before = self.projects.state(self.player_id)
        self.projects.work(self.player_id, "careful")
        after = self.projects.state(self.player_id)
        self.assertGreater(after["quality"], before["quality"])

    def test_opportunity_board_has_three_daily_choices(self) -> None:
        board = self.opportunities.board(self.player_id)
        self.assertEqual(len(board), 3)
        self.assertTrue(all(item["status"] == "open" for item in board))

    def test_starting_opportunity_spends_one_action(self) -> None:
        before = self.game.get_player(self.player_id)
        self.opportunities.start(self.player_id, 1)
        after = self.game.get_player(self.player_id)
        self.assertEqual(after["actions_left"], before["actions_left"] - 1)
        self.assertIsNotNone(self.opportunities.current(self.player_id))

    def test_completed_opportunity_is_saved_to_portfolio(self) -> None:
        board = self.opportunities.board(self.player_id)
        chosen_title = board[0]["title"]
        self.opportunities.start(self.player_id, 1)
        for _ in range(3):
            view = self.opportunities.current(self.player_id)
            self.assertIsNotNone(view)
            self.opportunities.resolve(self.player_id, 0)

        self.assertIsNone(self.opportunities.current(self.player_id))
        portfolio = self.opportunities.portfolio(self.player_id)
        self.assertEqual(len(portfolio), 1)
        self.assertEqual(portfolio[0]["title"], chosen_title)
        self.assertGreaterEqual(portfolio[0]["successes"], 0)
        self.assertLessEqual(portfolio[0]["successes"], 3)

    def test_higher_stat_means_higher_success_chance(self) -> None:
        low = self.opportunities.success_chance(2, 6)
        high = self.opportunities.success_chance(12, 6)
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
