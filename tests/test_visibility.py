import json
import tempfile
import unittest
from pathlib import Path

from app import app


class PredictionVisibilityTests(unittest.TestCase):
    def build_tournament(self, kickoff_utc: str):
        return {
            "tournament": {"name": "Test Cup"},
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
                }
            ],
            "matches": [
                {
                    "id": "M001",
                    "external_id": None,
                    "stage": "GROUP",
                    "group_id": "D",
                    "kickoff_utc": kickoff_utc,
                    "status": "SCHEDULED",
                    "venue": "Dallas Stadium",
                    "home_team_id": "usa",
                    "away_team_id": "par",
                    "home_score": None,
                    "away_score": None,
                }
            ],
        }

    def build_room(self):
        return {
            "rooms": {
                "ROOM01": {
                    "code": "ROOM01",
                    "password_hash": "x",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "players": {
                        "one": {"name": "Alice", "joined_at": "2026-01-01T00:00:00+00:00"},
                        "two": {"name": "Bob", "joined_at": "2026-01-01T00:01:00+00:00"},
                    },
                    "predictions": {
                        "one": {
                            "matches": {"M001": {"home": 1, "away": 0}},
                            "groups": {"D": ["usa", "par", "aus", "tur"]},
                        },
                        "two": {
                            "matches": {"M001": {"home": 2, "away": 1}},
                            "groups": {"D": ["par", "usa", "tur", "aus"]},
                        },
                    },
                }
            }
        }

    def render_room(self, tournament_payload):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "rooms.json").write_text(json.dumps(self.build_room()), encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(tournament_payload), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["memberships"] = {"ROOM01": {"slot": "one", "name": "Alice"}}
                response = client.get("/room/ROOM01")
                return response.get_data(as_text=True)

    def test_opponent_predictions_hidden_before_lock(self):
        body = self.render_room(self.build_tournament("2099-06-12T18:00:00Z"))
        self.assertIn("Hidden until kick-off.", body)
        self.assertIn("Hidden until the first match in this group kicks off.", body)
        self.assertNotIn(">2 - 1<", body)

    def test_opponent_predictions_visible_after_lock(self):
        body = self.render_room(self.build_tournament("2000-06-12T18:00:00Z"))
        self.assertIn("2 - 1", body)
        self.assertIn("<span>1.</span>", body)
        self.assertIn("Paraguay", body)


if __name__ == "__main__":
    unittest.main()
