from __future__ import annotations

import re
from typing import Any

from flask import current_app

from .filedb import load_json, locked_json_update
from .rooms import (
    generate_room_code,
    generate_room_password,
    hash_password,
    utc_timestamp,
    validate_player_secret,
    verify_password,
)


def rooms_default() -> dict[str, Any]:
    return {"rooms": {}}


def team_prediction_default() -> dict[str, Any]:
    return {"groups": {}, "podium": []}


def load_rooms() -> dict[str, Any]:
    return load_json(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default())


def slugify_team_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return cleaned.strip("-") or "team"


def generate_team_id(team_name: str, existing_ids: set[str]) -> str:
    base = slugify_team_name(team_name)
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def normalize_members(member_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], str | None]:
    members = []
    for row in member_rows:
        name = row.get("name", "").strip()
        gamer_name = row.get("gamer_name", "").strip()
        if not name and not gamer_name:
            continue
        if not name or not gamer_name:
            return [], "Each team member needs both a name and a gamer name."
        members.append({"name": name, "gamer_name": gamer_name})
    if not members:
        return [], "Add at least one team member."
    return members, None


def normalize_optional_members(member_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], str | None]:
    members = []
    for row in member_rows:
        name = row.get("name", "").strip()
        gamer_name = row.get("gamer_name", "").strip()
        if not name and not gamer_name:
            continue
        if not name or not gamer_name:
            return [], "Each team member needs both a name and a gamer name."
        members.append({"name": name, "gamer_name": gamer_name})
    if not members:
        return [], "Add at least one new team member."
    return members, None


def create_room(
    room_name: str,
    team_name: str,
    team_secret: str,
    member_rows: list[dict[str, str]],
    prediction_deadline_utc: str,
) -> dict[str, Any]:
    members, error = normalize_members(member_rows)
    if error:
        raise ValueError(error)

    created: dict[str, Any] = {}

    def updater(payload):
        rooms = payload.setdefault("rooms", {})
        code = generate_room_code()
        while code in rooms:
            code = generate_room_code()
        password = generate_room_password()
        team_id = generate_team_id(team_name, set())
        created["code"] = code
        created["password"] = password
        created["team_id"] = team_id
        rooms[code] = {
            "code": code,
            "name": room_name.strip(),
            "prediction_deadline_utc": prediction_deadline_utc,
            "password_hash": hash_password(password),
            "share_password": password,
            "created_at": utc_timestamp(),
            "teams": {
                team_id: {
                    "id": team_id,
                    "name": team_name.strip(),
                    "created_at": utc_timestamp(),
                    "password_hash": hash_password(team_secret),
                    "members": members,
                }
            },
            "predictions": {
                team_id: team_prediction_default(),
            },
        }
        return payload

    updated = locked_json_update(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default(), updater)
    return {
        "room": updated["rooms"][created["code"]],
        "password": created["password"],
        "team_id": created["team_id"],
    }


def get_room(code: str) -> dict[str, Any] | None:
    return load_rooms()["rooms"].get(code.upper())


def verify_room_access(code: str, password: str) -> tuple[dict[str, Any] | None, str | None]:
    room = get_room(code)
    if room is None:
        return None, "Room not found."
    if not verify_password(password, room["password_hash"]):
        return None, "Incorrect password."
    return room, None


def team_exists(room: dict[str, Any], team_name: str) -> bool:
    normalized = team_name.strip().lower()
    return any(team["name"].strip().lower() == normalized for team in room.get("teams", {}).values())


def join_team(code: str, team_name: str, team_secret: str, member_rows: list[dict[str, str]]) -> tuple[dict[str, Any] | None, str | None, str | None]:
    room = get_room(code)
    if room is None:
        return None, "Room not found.", None
    if not team_name.strip():
        return None, "Enter a team name.", None
    if team_exists(room, team_name):
        return None, "Choose a different team name.", None

    members, error = normalize_members(member_rows)
    if error:
        return None, error, None

    team_id_holder: dict[str, str] = {}

    def updater(payload):
        room_payload = payload["rooms"][code]
        existing_ids = set(room_payload.get("teams", {}).keys())
        team_id = generate_team_id(team_name, existing_ids)
        team_id_holder["team_id"] = team_id
        room_payload.setdefault("teams", {})[team_id] = {
            "id": team_id,
            "name": team_name.strip(),
            "created_at": utc_timestamp(),
            "password_hash": hash_password(team_secret),
            "members": members,
        }
        room_payload.setdefault("predictions", {})[team_id] = team_prediction_default()
        return payload

    updated = locked_json_update(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default(), updater)
    return updated["rooms"][code], None, team_id_holder["team_id"]


def verify_team_login(room: dict[str, Any], team_id: str, team_secret: str) -> bool:
    team = room.get("teams", {}).get(team_id)
    if not team:
        return False
    return verify_password(team_secret, team["password_hash"])


def save_group_prediction(code: str, team_id: str, group_id: str, ordered_team_ids: list[str]):
    def updater(payload):
        room = payload["rooms"][code]
        room.setdefault("predictions", {}).setdefault(team_id, team_prediction_default())
        room["predictions"][team_id]["groups"][group_id] = ordered_team_ids
        room["predictions"][team_id]["groups"][f"{group_id}_updated_at"] = utc_timestamp()
        return payload

    return locked_json_update(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default(), updater)


def save_podium_prediction(code: str, team_id: str, ordered_team_ids: list[str]):
    def updater(payload):
        room = payload["rooms"][code]
        room.setdefault("predictions", {}).setdefault(team_id, team_prediction_default())
        room["predictions"][team_id]["podium"] = ordered_team_ids
        room["predictions"][team_id]["podium_updated_at"] = utc_timestamp()
        return payload

    return locked_json_update(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default(), updater)


def add_team_members(code: str, team_id: str, member_rows: list[dict[str, str]]):
    members, error = normalize_optional_members(member_rows)
    if error:
        return None, error

    def updater(payload):
        room = payload["rooms"][code]
        team = room.get("teams", {}).get(team_id)
        existing = team.setdefault("members", [])
        existing_keys = {(member["name"].strip().lower(), member["gamer_name"].strip().lower()) for member in existing}
        for member in members:
            key = (member["name"].strip().lower(), member["gamer_name"].strip().lower())
            if key not in existing_keys:
                existing.append(member)
                existing_keys.add(key)
        team["members_updated_at"] = utc_timestamp()
        return payload

    updated = locked_json_update(current_app.config["AFRICAWEATHER_ROOMS_FILE"], rooms_default(), updater)
    return updated["rooms"][code], None


__all__ = [
    "add_team_members",
    "create_room",
    "get_room",
    "join_team",
    "load_rooms",
    "rooms_default",
    "save_group_prediction",
    "save_podium_prediction",
    "team_prediction_default",
    "validate_player_secret",
    "verify_room_access",
    "verify_team_login",
]
