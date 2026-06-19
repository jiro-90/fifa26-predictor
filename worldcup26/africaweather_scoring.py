from __future__ import annotations

from typing import Any

from .tournament import actual_group_order, group_complete, group_has_finished_match, parse_utc, utc_now


def room_locked(room: dict[str, Any]) -> bool:
    deadline = parse_utc(room.get("prediction_deadline_utc"))
    if deadline is None:
        return False
    return utc_now() >= deadline


def room_deadline_label(room: dict[str, Any]) -> str:
    deadline = parse_utc(room.get("prediction_deadline_utc"))
    if deadline is None:
        return "TBD"
    return deadline.strftime("%d %b %Y - %H:%M UTC")


def score_group_top_two(
    predicted_order: list[str] | None,
    group: dict[str, Any],
    matches: list[dict[str, Any]],
    teams: dict[str, dict[str, Any]],
    locked: bool,
) -> dict[str, Any]:
    if not predicted_order or len(predicted_order) != 2:
        if locked:
            return {"total": 0, "breakdown": ["No top-two prediction submitted"], "actual_order": None}
        return {"total": 0, "breakdown": ["No top-two prediction submitted yet"], "actual_order": None}
    has_live_table = group.get("actual_positions") or group_complete(group.get("id"), matches) or group_has_finished_match(group.get("id"), matches)
    if not has_live_table:
        return {"total": 0, "breakdown": ["Group not finished yet"], "actual_order": None}

    actual_order = actual_group_order(group, matches, teams)
    actual_positions = {team_id: index for index, team_id in enumerate(actual_order)}
    total = 0
    breakdown = []
    is_final = bool(group.get("actual_positions") or group_complete(group.get("id"), matches))

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

    phase_note = "Final standings applied" if is_final else "Live table applied"
    return {"total": total, "breakdown": [phase_note, *breakdown], "actual_order": actual_order}


def score_podium_prediction(
    predicted_order: list[str] | None,
    tournament: dict[str, Any],
    teams: dict[str, dict[str, Any]],
    locked: bool,
) -> dict[str, Any]:
    actual_order = tournament.get("tournament", {}).get("actual_top_three") or []
    if not predicted_order or len(predicted_order) != 3:
        if locked:
            return {"total": 0, "breakdown": ["No top-three prediction submitted"], "actual_order": actual_order}
        return {"total": 0, "breakdown": ["No top-three prediction submitted yet"], "actual_order": actual_order}
    if len(actual_order) != 3:
        return {"total": 0, "breakdown": ["Final top three not available yet"], "actual_order": actual_order}

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
            total += 4
            breakdown.append(f"{team_name}: exact podium spot, +4")
        elif delta == 1:
            total += 3
            breakdown.append(f"{team_name}: off by one, +3")
        elif delta == 2:
            total += 1
            breakdown.append(f"{team_name}: off by two, +1")
        else:
            breakdown.append(f"{team_name}: off by {delta}, +0")

    return {"total": total, "breakdown": breakdown, "actual_order": actual_order}


def compile_room_scores(room: dict[str, Any], tournament: dict[str, Any]) -> dict[str, Any]:
    groups = tournament.get("groups", [])
    matches = tournament.get("matches", [])
    teams = {team["id"]: team for group in groups for team in group.get("teams", [])}
    predictions = room.get("predictions", {})
    locked = room_locked(room)
    totals: dict[str, Any] = {}

    for team_id, team in room.get("teams", {}).items():
        team_predictions = predictions.get(team_id, {})
        group_points = []
        total = 0
        for group in groups:
            predicted = team_predictions.get("groups", {}).get(group["id"])
            scored = score_group_top_two(predicted, group, matches, teams, locked)
            total += scored["total"]
            group_points.append({"group_id": group["id"], "label": group["name"], **scored})

        podium_scored = score_podium_prediction(team_predictions.get("podium"), tournament, teams, locked)
        total += podium_scored["total"]
        totals[team_id] = {
            "name": team.get("name", team_id),
            "total": total,
            "groups": group_points,
            "podium": podium_scored,
            "member_count": len(team.get("members", [])),
        }

    return totals
