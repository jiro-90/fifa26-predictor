from __future__ import annotations

from typing import Any

from .tournament import actual_group_order, group_complete, group_locked, match_locked, resolve_team


def result_code(home_goals: int | None, away_goals: int | None) -> str | None:
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "H"
    if away_goals > home_goals:
        return "A"
    return "D"


def score_match_prediction(prediction: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    breakdown = []
    total = 0
    predicted_home = prediction.get("home")
    predicted_away = prediction.get("away")
    if predicted_home is None or predicted_away is None:
        if match_locked(match):
            return {"total": -1, "breakdown": ["Missed match prediction deadline: -1"]}
        return {"total": 0, "breakdown": ["No prediction submitted yet"]}
    if match.get("status") != "FINISHED":
        return {"total": 0, "breakdown": ["Pending result"]}

    actual_home = match.get("home_score")
    actual_away = match.get("away_score")

    if predicted_home == actual_home:
        total += 1
        breakdown.append("Exact home goals: +1")
    else:
        breakdown.append("Home goals missed: +0")

    if predicted_away == actual_away:
        total += 1
        breakdown.append("Exact away goals: +1")
    else:
        breakdown.append("Away goals missed: +0")

    if result_code(predicted_home, predicted_away) == result_code(actual_home, actual_away):
        total += 1
        breakdown.append("Correct match result: +1")
    else:
        breakdown.append("Wrong match result: +0")

    return {"total": total, "breakdown": breakdown}


def score_group_prediction(
    predicted_order: list[str] | None,
    group: dict[str, Any],
    matches: list[dict[str, Any]],
    teams: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not predicted_order:
        if group_locked(group.get("id"), matches):
            return {"total": -1, "breakdown": ["Missed group prediction deadline: -1"]}
        return {"total": 0, "breakdown": ["No group prediction submitted yet"]}
    if not group.get("actual_positions") and not group_complete(group.get("id"), matches):
        return {"total": 0, "breakdown": ["Group not finished yet"]}

    actual_order = actual_group_order(group, matches, teams)
    actual_positions = {team_id: index for index, team_id in enumerate(actual_order)}
    total = 0
    breakdown = []

    for guessed_index, team_id in enumerate(predicted_order):
        actual_index = actual_positions.get(team_id)
        if actual_index is None:
            continue
        delta = abs(guessed_index - actual_index)
        team_name = teams[team_id]["name"]
        if delta == 0:
            total += 3
            breakdown.append(f"{team_name}: exact position, +3")
        elif delta == 1:
            total += 1
            breakdown.append(f"{team_name}: off by one, +1")
        else:
            breakdown.append(f"{team_name}: off by {delta}, +0")

    return {"total": total, "breakdown": breakdown, "actual_order": actual_order}


def compile_room_scores(room: dict[str, Any], tournament: dict[str, Any]) -> dict[str, Any]:
    players = room.get("players", {})
    predictions = room.get("predictions", {})
    matches = tournament.get("matches", [])
    groups = tournament.get("groups", [])
    teams = {
        team["id"]: team
        for group in groups
        for team in group.get("teams", [])
    }

    totals: dict[str, Any] = {}
    for slot, player in players.items():
        if not player:
            continue
        player_predictions = predictions.get(slot, {})
        match_points = []
        group_points = []
        total = 0

        for match in matches:
            match_prediction = player_predictions.get("matches", {}).get(match["id"], {})
            scored = score_match_prediction(match_prediction, match)
            total += scored["total"]
            match_points.append(
                {
                    "match_id": match["id"],
                    "label": (
                        f'{resolve_team(match.get("home_team_id"), teams)["name"]} '
                        f'vs {resolve_team(match.get("away_team_id"), teams)["name"]}'
                    ),
                    **scored,
                }
            )

        for group in groups:
            group_prediction = player_predictions.get("groups", {}).get(group["id"])
            scored = score_group_prediction(group_prediction, group, matches, teams)
            total += scored["total"]
            group_points.append({"group_id": group["id"], "label": group["name"], **scored})

        totals[slot] = {
            "name": player.get("name", slot.title()),
            "total": total,
            "matches": match_points,
            "groups": group_points,
        }
    return totals
