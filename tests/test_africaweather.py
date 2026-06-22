import json
import tempfile
import unittest
from pathlib import Path

from app import app
from worldcup26.africaweather_scoring import score_group_top_two, score_podium_prediction
from worldcup26.rooms import hash_password


class AfricaweatherScoringTests(unittest.TestCase):
    def setUp(self):
        self.teams = {
            "bra": {"id": "bra", "name": "Brazil", "flag": "br"},
            "arg": {"id": "arg", "name": "Argentina", "flag": "ar"},
            "fra": {"id": "fra", "name": "France", "flag": "fr"},
            "usa": {"id": "usa", "name": "United States", "flag": "us"},
        }

    def test_group_top_two_scores_exact_and_off_by_one(self):
        group = {
            "id": "A",
            "name": "Group A",
            "teams": [
                {"id": "bra", "name": "Brazil"},
                {"id": "arg", "name": "Argentina"},
                {"id": "fra", "name": "France"},
                {"id": "usa", "name": "United States"},
            ],
            "actual_positions": ["arg", "bra", "fra", "usa"],
        }
        scored = score_group_top_two(["bra", "arg"], group, [], self.teams, locked=True)
        self.assertEqual(scored["total"], 2)
        self.assertIn("Brazil: off by one, +1", scored["breakdown"])
        self.assertIn("Argentina: off by one, +1", scored["breakdown"])

    def test_group_top_two_scores_against_live_table(self):
        group = {
            "id": "A",
            "name": "Group A",
            "teams": [
                {"id": "bra", "name": "Brazil"},
                {"id": "arg", "name": "Argentina"},
                {"id": "fra", "name": "France"},
                {"id": "usa", "name": "United States"},
            ],
        }
        matches = [
            {
                "id": "M001",
                "group_id": "A",
                "status": "FINISHED",
                "home_team_id": "bra",
                "away_team_id": "arg",
                "home_score": 2,
                "away_score": 0,
            },
            {
                "id": "M002",
                "group_id": "A",
                "status": "FINISHED",
                "home_team_id": "fra",
                "away_team_id": "usa",
                "home_score": 1,
                "away_score": 0,
            },
            {
                "id": "M003",
                "group_id": "A",
                "status": "SCHEDULED",
                "home_team_id": "bra",
                "away_team_id": "fra",
                "home_score": None,
                "away_score": None,
            },
        ]
        scored = score_group_top_two(["bra", "fra"], group, matches, self.teams, locked=False)
        self.assertEqual(scored["total"], 6)
        self.assertIn("Live table applied", scored["breakdown"])

    def test_podium_scoring_follows_new_rules(self):
        tournament = {
            "tournament": {"actual_top_three": ["bra", "arg", "fra"]},
            "groups": [],
            "matches": [{"id": "M001", "kickoff_utc": "2000-01-01T00:00:00Z"}],
        }
        scored = score_podium_prediction(["bra", "fra", "arg"], tournament, self.teams, locked=True)
        self.assertEqual(scored["total"], 10)
        self.assertIn("Brazil: exact podium spot, +4", scored["breakdown"])
        self.assertIn("France: off by one, +3", scored["breakdown"])
        self.assertIn("Argentina: off by one, +3", scored["breakdown"])


class AfricaweatherVisibilityTests(unittest.TestCase):
    def build_tournament(self, kickoff_utc: str):
        return {
            "tournament": {"name": "Test Cup", "actual_top_three": ["bra", "arg", "fra"]},
            "groups": [
                {
                    "id": "A",
                    "name": "Group A",
                    "teams": [
                        {"id": "bra", "name": "Brazil", "flag": "br", "fifa_code": "BRA"},
                        {"id": "arg", "name": "Argentina", "flag": "ar", "fifa_code": "ARG"},
                        {"id": "fra", "name": "France", "flag": "fr", "fifa_code": "FRA"},
                        {"id": "usa", "name": "United States", "flag": "us", "fifa_code": "USA"},
                    ],
                    "actual_positions": ["bra", "arg", "fra", "usa"],
                }
            ],
            "matches": [
                {
                    "id": "M001",
                    "external_id": None,
                    "stage": "GROUP",
                    "group_id": "A",
                    "kickoff_utc": kickoff_utc,
                    "status": "SCHEDULED",
                    "venue": "Test Stadium",
                    "home_team_id": "bra",
                    "away_team_id": "arg",
                    "home_score": None,
                    "away_score": None,
                }
            ],
        }

    def build_room(self, prediction_deadline_utc: str):
        return {
            "rooms": {
                "ROOM01": {
                    "code": "ROOM01",
                    "name": "Africaweather Test",
                    "prediction_deadline_utc": prediction_deadline_utc,
                    "password_hash": hash_password("shared"),
                    "share_password": "shared",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "teams": {
                        "storm": {
                            "id": "storm",
                            "name": "Storm",
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "password_hash": hash_password("storm-pass"),
                            "members": [{"name": "Alice", "gamer_name": "CloudAce"}],
                        },
                        "rain": {
                            "id": "rain",
                            "name": "Rain",
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "password_hash": hash_password("rain-pass"),
                            "members": [{"name": "Bob", "gamer_name": "Drizzle"}],
                        },
                    },
                    "predictions": {
                        "storm": {"groups": {"A": ["bra", "arg"]}, "podium": ["bra", "arg", "fra"]},
                        "rain": {"groups": {"A": ["arg", "bra"]}, "podium": ["arg", "fra", "bra"]},
                    },
                }
            }
        }

    def render_room(self, tournament_payload, prediction_deadline_utc: str):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(json.dumps(self.build_room(prediction_deadline_utc)), encoding="utf-8")
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(tournament_payload), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.get("/africaweather/room/ROOM01")
                return response.get_data(as_text=True)

    def test_other_team_predictions_hidden_before_lock(self):
        body = self.render_room(self.build_tournament("2000-06-12T18:00:00Z"), "2099-06-12T18:00:00Z")
        self.assertIn("Hidden until the room deadline passes.", body)

    def test_other_team_predictions_visible_after_lock(self):
        body = self.render_room(self.build_tournament("2099-06-12T18:00:00Z"), "2000-06-12T18:00:00Z")
        self.assertIn("Rain", body)
        self.assertIn("Argentina", body)
        self.assertIn("France", body)

    def test_public_view_hidden_before_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2099-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2000-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                body = client.get("/africaweather/public/ROOM01").get_data(as_text=True)

        self.assertIn("public leaderboard opens once the room deadline has passed", body)
        self.assertNotIn("Storm</strong>", body)

    def test_team_can_add_members_after_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2099-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2099-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.post(
                    "/africaweather/room/ROOM01/team-members",
                    data={
                        "member_name_1": "Carol",
                        "member_gamer_1": "Thunder",
                        "member_name_2": "",
                        "member_gamer_2": "",
                        "member_name_3": "",
                        "member_gamer_3": "",
                        "member_name_4": "",
                        "member_gamer_4": "",
                    },
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                self.assertEqual(response.status_code, 200)
                payload = json.loads(response.get_data(as_text=True))
                self.assertTrue(payload["ok"])

            saved = json.loads((data_dir / "africaweather_rooms.json").read_text(encoding="utf-8"))
            members = saved["rooms"]["ROOM01"]["teams"]["storm"]["members"]
            self.assertIn({"name": "Carol", "gamer_name": "Thunder"}, members)

    def test_team_can_rename_before_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2099-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2099-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.post(
                    "/africaweather/room/ROOM01/team-name",
                    data={"team_name": "Storm Chasers"},
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                self.assertEqual(response.status_code, 200)
                payload = json.loads(response.get_data(as_text=True))
                self.assertTrue(payload["ok"])

            saved = json.loads((data_dir / "africaweather_rooms.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["rooms"]["ROOM01"]["teams"]["storm"]["name"], "Storm Chasers")

    def test_team_can_edit_members_before_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2099-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2099-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.post(
                    "/africaweather/room/ROOM01/team-members/edit",
                    data={
                        "existing_member_name_0": "Alice Updated",
                        "existing_member_gamer_0": "CloudBoss",
                    },
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                self.assertEqual(response.status_code, 200)
                payload = json.loads(response.get_data(as_text=True))
                self.assertTrue(payload["ok"])

            saved = json.loads((data_dir / "africaweather_rooms.json").read_text(encoding="utf-8"))
            members = saved["rooms"]["ROOM01"]["teams"]["storm"]["members"]
            self.assertEqual(members, [{"name": "Alice Updated", "gamer_name": "CloudBoss"}])

    def test_team_cannot_edit_members_after_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2000-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2099-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.post(
                    "/africaweather/room/ROOM01/team-members/edit",
                    data={
                        "existing_member_name_0": "Alice Updated",
                        "existing_member_gamer_0": "CloudBoss",
                    },
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                self.assertEqual(response.status_code, 409)

    def test_team_cannot_rename_after_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "africaweather_rooms.json").write_text(
                json.dumps(self.build_room("2000-06-12T18:00:00Z")),
                encoding="utf-8",
            )
            (data_dir / "rooms.json").write_text('{"rooms": {}}', encoding="utf-8")
            (data_dir / "last_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "tournament.json").write_text(json.dumps(self.build_tournament("2099-06-12T18:00:00Z")), encoding="utf-8")

            app.config.update(
                TESTING=True,
                DATA_DIR=data_dir,
                AFRICAWEATHER_ROOMS_FILE=data_dir / "africaweather_rooms.json",
                ROOMS_FILE=data_dir / "rooms.json",
                LAST_SYNC_FILE=data_dir / "last_sync.json",
                TOURNAMENT_FILE=data_dir / "tournament.json",
                SYNC_INTERVAL_SECONDS=999999,
            )

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["aw_memberships"] = {"ROOM01": {"team_id": "storm", "team_name": "Storm"}}
                response = client.post(
                    "/africaweather/room/ROOM01/team-name",
                    data={"team_name": "Storm Chasers"},
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                self.assertEqual(response.status_code, 409)

    def test_randomizer_tool_splits_names_into_requested_team_count(self):
        with app.test_client() as client:
            response = client.post(
                "/africaweather/tools",
                data={
                    "names": "Alice\nBob\nCarol\nDan",
                    "team_count": "2",
                    "team_prefix": "Squad",
                },
            )
            body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Squad 1", body)
        self.assertIn("Squad 2", body)
        self.assertIn("Alice", body)
        self.assertIn("Dan", body)


if __name__ == "__main__":
    unittest.main()
