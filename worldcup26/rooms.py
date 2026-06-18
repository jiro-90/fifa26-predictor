from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from flask import current_app

from .filedb import load_json, locked_json_update


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, digest: str) -> bool:
    return hash_password(password) == digest


def rooms_default() -> dict[str, Any]:
    return {"rooms": {}}


def prediction_slot_default() -> dict[str, Any]:
    return {"matches": {}, "groups": {}, "top_five": []}


def load_rooms() -> dict[str, Any]:
    return load_json(current_app.config["ROOMS_FILE"], rooms_default())


def generate_room_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_room_password() -> str:
    return secrets.token_urlsafe(8)[:10]


def validate_player_secret(player_secret: str) -> str | None:
    if len(player_secret.strip()) < 4:
        return "Personal login password must be at least 4 characters."
    return None


def create_room(player_name: str, player_secret: str) -> dict[str, Any]:
    created: dict[str, Any] = {}

    def updater(payload):
        rooms = payload.setdefault("rooms", {})
        code = generate_room_code()
        while code in rooms:
            code = generate_room_code()
        password = generate_room_password()
        created["code"] = code
        created["password"] = password
        rooms[code] = {
            "code": code,
            "password_hash": hash_password(password),
            "share_password": password,
            "created_at": utc_timestamp(),
            "players": {
                "one": {
                    "name": player_name,
                    "joined_at": utc_timestamp(),
                    "login_hash": hash_password(player_secret),
                },
                "two": None,
            },
            "predictions": {
                "one": prediction_slot_default(),
                "two": prediction_slot_default(),
            },
        }
        return payload

    updated = locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
    return {"room": updated["rooms"][created["code"]], "password": created["password"]}


def verify_room_access(code: str, password: str) -> tuple[dict[str, Any] | None, str | None]:
    code = code.upper().strip()
    rooms = load_rooms()["rooms"]
    room = rooms.get(code)
    if room is None:
        return None, "Room not found."
    if not verify_password(password, room["password_hash"]):
        return None, "Incorrect password."
    return room, None


def claim_second_player(code: str, player_name: str, player_secret: str) -> tuple[dict[str, Any] | None, str | None]:
    room = get_room(code)
    if room is None:
        return None, "Room not found."

    normalized_name = player_name.strip().lower()
    if not normalized_name:
        return None, "Enter a player name."
    if room["players"]["one"]["name"].strip().lower() == normalized_name:
        return None, "Choose a different player name from Player 1."
    if room["players"].get("two") is not None:
        return None, "Room already has two players."

    def updater(payload):
        payload["rooms"][code]["players"]["two"] = {
            "name": player_name,
            "joined_at": utc_timestamp(),
            "login_hash": hash_password(player_secret),
        }
        payload["rooms"][code].pop("share_password", None)
        return payload

    updated = locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
    return updated["rooms"][code], None


def verify_player_login(room: dict[str, Any], slot: str, player_secret: str) -> bool:
    player = room["players"].get(slot)
    if not player:
        return False
    login_hash = player.get("login_hash")
    if not login_hash:
        return True
    return verify_password(player_secret, login_hash)


def get_room(code: str) -> dict[str, Any] | None:
    return load_rooms()["rooms"].get(code.upper())


def save_match_prediction(code: str, slot: str, match_id: str, home: int, away: int):
    def updater(payload):
        room = payload["rooms"][code]
        room["predictions"].setdefault(slot, prediction_slot_default())
        room["predictions"][slot]["matches"][match_id] = {
            "home": home,
            "away": away,
            "updated_at": utc_timestamp(),
        }
        return payload

    return locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)


def save_group_prediction(code: str, slot: str, group_id: str, ordered_team_ids: list[str]):
    def updater(payload):
        room = payload["rooms"][code]
        room["predictions"].setdefault(slot, prediction_slot_default())
        room["predictions"][slot]["groups"][group_id] = ordered_team_ids
        room["predictions"][slot]["groups"][f"{group_id}_updated_at"] = utc_timestamp()
        return payload

    return locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)


def save_top_five_prediction(code: str, slot: str, ordered_team_ids: list[str]):
    def updater(payload):
        room = payload["rooms"][code]
        room["predictions"].setdefault(slot, prediction_slot_default())
        room["predictions"][slot]["top_five"] = ordered_team_ids
        room["predictions"][slot]["top_five_updated_at"] = utc_timestamp()
        return payload

    return locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
