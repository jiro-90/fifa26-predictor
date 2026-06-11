import unittest

from worldcup26.scoring import score_group_prediction, score_match_prediction


class MatchScoringTests(unittest.TestCase):
    def test_awards_goal_and_result_points(self):
        prediction = {"home": 0, "away": 2}
        match = {"status": "FINISHED", "home_score": 0, "away_score": 3}
        scored = score_match_prediction(prediction, match)
        self.assertEqual(scored["total"], 2)

    def test_requires_finished_match(self):
        prediction = {"home": 1, "away": 1}
        match = {"status": "SCHEDULED", "home_score": None, "away_score": None}
        scored = score_match_prediction(prediction, match)
        self.assertEqual(scored["total"], 0)


class GroupScoringTests(unittest.TestCase):
    def test_awards_exact_and_off_by_one_points(self):
        group = {
            "id": "A",
            "name": "Group A",
            "teams": [
                {"id": "alpha", "name": "Alpha"},
                {"id": "bravo", "name": "Bravo"},
                {"id": "charlie", "name": "Charlie"},
                {"id": "delta", "name": "Delta"},
            ],
        }
        teams = {team["id"]: team for team in group["teams"]}
        matches = [
            {"group_id": "A", "status": "FINISHED", "home_team_id": "alpha", "away_team_id": "bravo", "home_score": 1, "away_score": 0},
            {"group_id": "A", "status": "FINISHED", "home_team_id": "charlie", "away_team_id": "delta", "home_score": 0, "away_score": 1},
            {"group_id": "A", "status": "FINISHED", "home_team_id": "alpha", "away_team_id": "charlie", "home_score": 1, "away_score": 1},
            {"group_id": "A", "status": "FINISHED", "home_team_id": "bravo", "away_team_id": "delta", "home_score": 0, "away_score": 2},
            {"group_id": "A", "status": "FINISHED", "home_team_id": "alpha", "away_team_id": "delta", "home_score": 0, "away_score": 1},
            {"group_id": "A", "status": "FINISHED", "home_team_id": "bravo", "away_team_id": "charlie", "home_score": 2, "away_score": 1},
        ]
        predicted = ["delta", "bravo", "alpha", "charlie"]
        scored = score_group_prediction(predicted, group, matches, teams)
        self.assertEqual(scored["total"], 8)

    def test_returns_pending_if_group_incomplete(self):
        group = {
            "id": "A",
            "name": "Group A",
            "teams": [
                {"id": "alpha", "name": "Alpha"},
                {"id": "bravo", "name": "Bravo"},
                {"id": "charlie", "name": "Charlie"},
                {"id": "delta", "name": "Delta"},
            ],
        }
        teams = {team["id"]: team for team in group["teams"]}
        matches = [{"group_id": "A", "status": "SCHEDULED", "home_team_id": "alpha", "away_team_id": "bravo", "home_score": None, "away_score": None}]
        scored = score_group_prediction(["alpha", "bravo", "charlie", "delta"], group, matches, teams)
        self.assertEqual(scored["total"], 0)


if __name__ == "__main__":
    unittest.main()
