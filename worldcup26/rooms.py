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


def load_rooms() -> dict[str, Any]:
    return load_json(current_app.config["ROOMS_FILE"], rooms_default())


def generate_room_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_room_password() -> str:
    return secrets.token_urlsafe(8)[:10]


def create_room(player_name: str) -> dict[str, Any]:
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
            "created_at": utc_timestamp(),
            "players": {
                "one": {"name": player_name, "joined_at": utc_timestamp()},
                "two": None,
            },
            "predictions": {
                "one": {"matches": {}, "groups": {}},
                "two": {"matches": {}, "groups": {}},
            },
        }
        return payload

    updated = locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
    return {"room": updated["rooms"][created["code"]], "password": created["password"]}


def join_room(code: str, password: str, player_name: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    code = code.upper().strip()
    rooms = load_rooms()["rooms"]
    room = rooms.get(code)
    if room is None:
        return None, "Room not found.", None
    if not verify_password(password, room["password_hash"]):
        return None, "Incorrect password.", None
    if room["players"]["one"]["name"].strip().lower() == player_name.strip().lower():
        return None, "Choose a different player name from Player 1.", None
    if room["players"].get("two") is None:
        def updater(payload):
            payload["rooms"][code]["players"]["two"] = {
                "name": player_name,
                "joined_at": utc_timestamp(),
            }
            return payload

        updated = locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
        return updated["rooms"][code], None, "two"
    existing_two = room["players"]["two"]["name"]
    if existing_two == player_name:
        return room, None, "two"
    return None, "Room already has two players.", None


def get_room(code: str) -> dict[str, Any] | None:
    return load_rooms()["rooms"].get(code.upper())


def save_match_prediction(code: str, slot: str, match_id: str, home: int, away: int):
    def updater(payload):
        room = payload["rooms"][code]
        room["predictions"].setdefault(slot, {"matches": {}, "groups": {}})
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
        room["predictions"].setdefault(slot, {"matches": {}, "groups": {}})
        room["predictions"][slot]["groups"][group_id] = ordered_team_ids
        room["predictions"][slot]["groups"][f"{group_id}_updated_at"] = utc_timestamp()
        return payload

    return locked_json_update(current_app.config["ROOMS_FILE"], rooms_default(), updater)
