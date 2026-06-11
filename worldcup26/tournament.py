from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .filedb import load_json, save_json_atomic


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def tournament_default() -> dict[str, Any]:
    return {"tournament": {}, "groups": [], "matches": []}


def load_tournament(path: Path) -> dict[str, Any]:
    return load_json(path, tournament_default())


def save_tournament(path: Path, payload: dict[str, Any]):
    save_json_atomic(path, payload)


def group_first_kickoff(group_id: str, matches: list[dict[str, Any]]) -> datetime | None:
    group_matches = [m for m in matches if m.get("group_id") == group_id]
    kickoff_values = [parse_utc(match.get("kickoff_utc")) for match in group_matches]
    kickoff_values = [kickoff for kickoff in kickoff_values if kickoff is not None]
    return min(kickoff_values) if kickoff_values else None


def match_locked(match: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or utc_now()
    kickoff = parse_utc(match.get("kickoff_utc"))
    if kickoff is None:
        return False
    return now >= kickoff


def group_locked(group_id: str, matches: list[dict[str, Any]], now: datetime | None = None) -> bool:
    now = now or utc_now()
    kickoff = group_first_kickoff(group_id, matches)
    if kickoff is None:
        return False
    return now >= kickoff


def team_lookup(tournament: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for group in tournament.get("groups", []):
        for team in group.get("teams", []):
            lookup[team["id"]] = team
    return lookup


def resolve_team(team_id: str | None, teams: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if team_id and team_id in teams:
        return teams[team_id]
    return {
        "id": team_id or "tbd",
        "name": "TBD",
        "flag": None,
    }


def group_lookup(tournament: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {group["id"]: group for group in tournament.get("groups", [])}


def match_lookup(tournament: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {match["id"]: match for match in tournament.get("matches", [])}


@dataclass
class GroupStandingRow:
    team_id: str
    team_name: str
    points: int = 0
    goal_difference: int = 0
    goals_for: int = 0
    played: int = 0


def actual_group_order(group: dict[str, Any], matches: list[dict[str, Any]], teams: dict[str, dict[str, Any]]):
    explicit = group.get("actual_positions")
    if explicit:
        return explicit

    rows: dict[str, GroupStandingRow] = {
        team["id"]: GroupStandingRow(team_id=team["id"], team_name=team["name"])
        for team in group.get("teams", [])
    }

    group_matches = [
        match
        for match in matches
        if match.get("group_id") == group.get("id") and match.get("status") == "FINISHED"
    ]
    for match in group_matches:
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        home_score = match.get("home_score")
        away_score = match.get("away_score")
        if home_score is None or away_score is None:
            continue
        home = rows[home_id]
        away = rows[away_id]
        home.played += 1
        away.played += 1
        home.goals_for += home_score
        away.goals_for += away_score
        home.goal_difference += home_score - away_score
        away.goal_difference += away_score - home_score

        if home_score > away_score:
            home.points += 3
        elif away_score > home_score:
            away.points += 3
        else:
            home.points += 1
            away.points += 1

    ordered = sorted(
        rows.values(),
        key=lambda row: (-row.points, -row.goal_difference, -row.goals_for, row.team_name),
    )
    return [row.team_id for row in ordered]


def group_complete(group_id: str, matches: list[dict[str, Any]]) -> bool:
    group_matches = [match for match in matches if match.get("group_id") == group_id]
    return bool(group_matches) and all(match.get("status") == "FINISHED" for match in group_matches)
