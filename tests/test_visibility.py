import json
import tempfile
import unittest
from pathlib import Path

from app import app
from worldcup26.rooms import hash_password, verify_room_access


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
                        "one": {"name": "Alice", "joined_at": "2026-01-01T00:00:00+00:00", "login_hash": hash_password("alice-pass")},
                        "two": {"name": "Bob", "joined_at": "2026-01-01T00:01:00+00:00", "login_hash": hash_password("bob-pass")},
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


class RoomRejoinTests(unittest.TestCase):
    def test_existing_players_can_relogin_after_code_and_password_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            room_payload = {
                "rooms": {
                    "ROOM01": {
                        "code": "ROOM01",
                        "password_hash": hash_password("secret"),
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "players": {
                            "one": {"name": "Alice", "joined_at": "2026-01-01T00:00:00+00:00", "login_hash": hash_password("alice-pass")},
                            "two": {"name": "Bob", "joined_at": "2026-01-01T00:01:00+00:00", "login_hash": hash_password("bob-pass")},
                        },
                        "predictions": {
                            "one": {"matches": {}, "groups": {}},
                            "two": {"matches": {}, "groups": {}},
                        },
                    }
                }
            }
            (data_dir / "rooms.json").write_text(json.dumps(room_payload), encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps({"tournament": {}, "groups": [], "matches": []}), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
            )

            with app.app_context():
                room, error = verify_room_access("ROOM01", "secret")
                self.assertIsNone(error)
                self.assertEqual(room["players"]["one"]["name"], "Alice")

            with app.test_client() as client:
                response = client.post("/join-room", data={"code": "ROOM01", "password": "secret"}, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].endswith("/room/ROOM01/access"))

                relogin = client.post("/room/ROOM01/relogin/one", data={"player_secret": "alice-pass"}, follow_redirects=False)
                self.assertEqual(relogin.status_code, 302)
                self.assertTrue(relogin.headers["Location"].endswith("/room/ROOM01"))

                blocked = client.post("/room/ROOM01/relogin/two", data={"player_secret": "wrong-pass"}, follow_redirects=True)
                self.assertIn("Incorrect personal login password.", blocked.get_data(as_text=True))

    def test_join_room_page_for_new_second_player_does_not_need_name_up_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            room_payload = {
                "rooms": {
                    "ROOM01": {
                        "code": "ROOM01",
                        "password_hash": hash_password("secret"),
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "players": {
                            "one": {"name": "Alice", "joined_at": "2026-01-01T00:00:00+00:00", "login_hash": hash_password("alice-pass")},
                            "two": None,
                        },
                        "predictions": {
                            "one": {"matches": {}, "groups": {}},
                            "two": {"matches": {}, "groups": {}},
                        },
                    }
                }
            }
            (data_dir / "rooms.json").write_text(json.dumps(room_payload), encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps({"tournament": {}, "groups": [], "matches": []}), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
            )

            with app.test_client() as client:
                response = client.post("/join-room", data={"code": "ROOM01", "password": "secret"}, follow_redirects=True)
                body = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Join as Player 2", body)
                self.assertIn("Continue as Alice", body)
                self.assertIn("Personal login password", body)

    def test_share_password_persists_until_second_player_joins(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            tournament = {
                "tournament": {"name": "Test Cup"},
                "groups": [],
                "matches": [],
            }
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(tournament), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
                SERVER_NAME="localhost",
            )

            with app.test_client() as client:
                created = client.post("/create-room", data={"player_name": "Alice", "player_secret": "alice-pass"}, follow_redirects=True)
                first_body = created.get_data(as_text=True)
                self.assertIn("Room password", first_body)
                self.assertIn("Copy invite text", first_body)

                refreshed = client.get(created.request.path)
                second_body = refreshed.get_data(as_text=True)
                self.assertIn("Room password", second_body)

                room_code = created.request.path.rsplit("/", 1)[-1]
                room_state = json.loads((data_dir / "rooms.json").read_text(encoding="utf-8"))
                share_password = room_state["rooms"][room_code]["share_password"]

                with app.test_client() as joiner:
                    access = joiner.post(
                        "/join-room",
                        data={"code": room_code, "password": share_password},
                        follow_redirects=False,
                    )
                    self.assertEqual(access.status_code, 302)
                    self.assertTrue(access.headers["Location"].endswith(f"/room/{room_code}/access"))

                    joined = joiner.post(
                        f"/room/{room_code}/join",
                        data={"player_name": "Bob", "player_secret": "bob-pass"},
                        follow_redirects=False,
                    )
                    self.assertEqual(joined.status_code, 302)
                    self.assertTrue(joined.headers["Location"].endswith(f"/room/{room_code}"))

                after_join = client.get(created.request.path)
                after_join_body = after_join.get_data(as_text=True)
                self.assertNotIn("Copy invite text", after_join_body)
                self.assertNotIn("Room password", after_join_body)
