import copy
import unittest
from unittest.mock import Mock, patch

from worldcup26.sync import FootballDataProvider


class FootballDataSyncTests(unittest.TestCase):
    def setUp(self):
        self.provider = FootballDataProvider("token", "https://api.football-data.org/v4", "WC")
        self.tournament = {
            "groups": [
                {
                    "id": "D",
                    "name": "Group D",
                    "teams": [
                        {"id": "usa", "name": "United States", "flag": "us", "fifa_code": "USA"},
                        {"id": "par", "name": "Paraguay", "flag": "py", "fifa_code": "PAR"},
                        {"id": "aus", "name": "Australia", "flag": "au", "fifa_code": "AUS"},
                        {"id": "tur", "name": "Turkiye", "flag": "tr", "fifa_code": "TUR"},
                    ],
                },
                {
                    "id": "A",
                    "name": "Group A",
                    "teams": [
                        {"id": "mex", "name": "Mexico", "flag": "mx", "fifa_code": "MEX"},
                        {"id": "rsa", "name": "South Africa", "flag": "za", "fifa_code": "RSA"},
                        {"id": "kor", "name": "Korea Republic", "flag": "kr", "fifa_code": "KOR"},
                        {"id": "cze", "name": "Czechia", "flag": "cz", "fifa_code": "CZE"},
                    ],
                }
            ],
            "matches": [
                {
                    "id": "M001",
                    "external_id": None,
                    "stage": "GROUP",
                    "group_id": "D",
                    "kickoff_utc": "2026-06-12T08:00:00Z",
                    "status": "SCHEDULED",
                    "venue": "Los Angeles Stadium",
                    "home_team_id": "usa",
                    "away_team_id": "par",
                    "home_score": None,
                    "away_score": None,
                },
                {
                    "id": "M073",
                    "external_id": None,
                    "stage": "ROUND_OF_32",
                    "group_id": None,
                    "kickoff_utc": "2026-06-28T19:00:00Z",
                    "status": "SCHEDULED",
                    "venue": "Los Angeles Stadium",
                    "home_team_id": None,
                    "away_team_id": None,
                    "home_score": None,
                    "away_score": None,
                },
            ],
        }

    @patch("worldcup26.sync.requests.get")
    def test_sync_updates_matches_and_group_positions(self, mock_get):
        matches_response = Mock()
        matches_response.raise_for_status = Mock()
        matches_response.json.return_value = {
            "matches": [
                {
                    "id": 9001,
                    "utcDate": "2026-06-12T08:00:00Z",
                    "status": "FINISHED",
                    "stage": "GROUP_STAGE",
                    "group": "GROUP_D",
                    "venue": "Los Angeles Stadium",
                    "homeTeam": {"name": "United States", "shortName": "USA", "tla": "USA"},
                    "awayTeam": {"name": "Paraguay", "shortName": "Paraguay", "tla": "PAR"},
                    "score": {"fullTime": {"home": 2, "away": 1}},
                },
                {
                    "id": 9073,
                    "utcDate": "2026-06-28T19:00:00Z",
                    "status": "TIMED",
                    "stage": "LAST_32",
                    "group": None,
                    "venue": "Los Angeles Stadium",
                    "homeTeam": {"name": "Czechia", "shortName": "Czechia", "tla": "CZE"},
                    "awayTeam": {"name": "South Korea", "shortName": "Korea Republic", "tla": "KOR"},
                    "score": {"fullTime": {"home": None, "away": None}},
                },
            ]
        }
        standings_response = Mock()
        standings_response.raise_for_status = Mock()
        standings_response.json.return_value = {
            "standings": [
                {
                    "type": "TOTAL",
                    "group": "GROUP_D",
                    "table": [
                        {"position": 1, "team": {"name": "Paraguay", "tla": "PAR"}},
                        {"position": 2, "team": {"name": "United States", "tla": "USA"}},
                        {"position": 3, "team": {"name": "Australia", "tla": "AUS"}},
                        {"position": 4, "team": {"name": "Turkiye", "tla": "TUR"}},
                    ],
                }
            ]
        }
        mock_get.side_effect = [matches_response, standings_response]

        tournament = copy.deepcopy(self.tournament)
        summary = self.provider.sync(tournament)

        self.assertEqual(summary["updated_matches"], 2)
        self.assertEqual(summary["updated_groups"], 1)

        group_match = tournament["matches"][0]
        self.assertEqual(group_match["external_id"], 9001)
        self.assertEqual(group_match["status"], "FINISHED")
        self.assertEqual(group_match["home_score"], 2)
        self.assertEqual(group_match["away_score"], 1)

        knockout_match = tournament["matches"][1]
        self.assertEqual(knockout_match["external_id"], 9073)
        self.assertEqual(knockout_match["home_team_id"], "cze")
        self.assertEqual(knockout_match["away_team_id"], "kor")
        self.assertEqual(knockout_match["stage"], "ROUND_OF_32")

        group = tournament["groups"][0]
        self.assertEqual(group["actual_positions"], ["par", "usa", "aus", "tur"])


if __name__ == "__main__":
    unittest.main()
