from __future__ import annotations

import json
from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from .rooms import (
    claim_second_player,
    create_room,
    get_room,
    save_group_prediction,
    save_match_prediction,
    validate_player_secret,
    verify_player_login,
    verify_room_access,
)
from .scoring import compile_room_scores
from .sync import maybe_sync_tournament
from .tournament import actual_group_order, group_complete, group_locked, load_tournament, match_locked, parse_utc, resolve_team, team_lookup


main_bp = Blueprint("main", __name__)
KNOCKOUT_STAGE_ORDER = [
    ("ROUND_OF_32", "Round of 32"),
    ("ROUND_OF_16", "Round of 16"),
    ("QUARTER_FINAL", "Quarter-finals"),
    ("SEMI_FINAL", "Semi-finals"),
    ("THIRD_PLACE", "Third-place play-off"),
    ("FINAL", "Final"),
]


def kickoff_label(value: str | None) -> str:
    kickoff = parse_utc(value)
    if kickoff is None:
        return "TBD"
    return kickoff.strftime("%d %b %Y - %H:%M UTC")


def access_granted(code: str) -> bool:
    return bool(session.get("room_access", {}).get(code.upper()))


def wants_json_response() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def save_feedback(message: str, ok: bool, status_code: int, code: str):
    if wants_json_response():
        return jsonify({"ok": ok, "message": message}), status_code
    flash(message)
    return redirect(url_for("main.room", code=code))


def login_required(view):
    @wraps(view)
    def wrapped(code, *args, **kwargs):
        membership = session.get("memberships", {}).get(code.upper())
        if membership is None:
            flash("Join the room first.")
            return redirect(url_for("main.index"))
        return view(code.upper(), *args, **kwargs)

    return wrapped


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.post("/create-room")
def create_room_view():
    player_name = request.form.get("player_name", "").strip()
    player_secret = request.form.get("player_secret", "").strip()
    if not player_name:
        flash("Enter your name to create a room.")
        return redirect(url_for("main.index"))
    secret_error = validate_player_secret(player_secret)
    if secret_error:
        flash(secret_error)
        return redirect(url_for("main.index"))

    created = create_room(player_name, player_secret)
    room = created["room"]
    memberships = session.setdefault("memberships", {})
    memberships[room["code"]] = {"slot": "one", "name": player_name}
    session.modified = True
    return redirect(url_for("main.room", code=room["code"]))


@main_bp.post("/join-room")
def join_room_view():
    code = request.form.get("code", "").strip().upper()
    password = request.form.get("password", "").strip()
    if not code or not password:
        flash("Code and password are required.")
        return redirect(url_for("main.index"))

    room, error = verify_room_access(code, password)
    if error:
        flash(error)
        return redirect(url_for("main.index"))

    room_access = session.setdefault("room_access", {})
    room_access[code] = True
    session.modified = True

    if session.get("memberships", {}).get(code):
        return redirect(url_for("main.room", code=code))
    return redirect(url_for("main.room_access_view", code=room["code"]))


@main_bp.get("/rules")
def rules():
    return render_template("rules.html")


@main_bp.get("/room/<code>/access")
def room_access_view(code):
    code = code.upper()
    if session.get("memberships", {}).get(code):
        return redirect(url_for("main.room", code=code))
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("main.index"))

    room = get_room(code)
    if room is None:
        flash("Room not found.")
        return redirect(url_for("main.index"))
    return render_template("room_access.html", room=room)


@main_bp.post("/room/<code>/relogin/<slot>")
def room_relogin(code, slot):
    code = code.upper()
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("main.index"))
    if slot not in {"one", "two"}:
        flash("Invalid player slot.")
        return redirect(url_for("main.index"))

    room = get_room(code)
    if room is None:
        flash("Room not found.")
        return redirect(url_for("main.index"))
    player = room["players"].get(slot)
    if not player:
        flash("That player slot is not available yet.")
        return redirect(url_for("main.room_access_view", code=code))
    player_secret = request.form.get("player_secret", "").strip()
    if not verify_player_login(room, slot, player_secret):
        flash("Incorrect personal login password.")
        return redirect(url_for("main.room_access_view", code=code))

    memberships = session.setdefault("memberships", {})
    memberships[code] = {"slot": slot, "name": player["name"]}
    session.modified = True
    return redirect(url_for("main.room", code=code))


@main_bp.post("/room/<code>/join")
def room_join_new_player(code):
    code = code.upper()
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("main.index"))

    player_name = request.form.get("player_name", "").strip()
    player_secret = request.form.get("player_secret", "").strip()
    secret_error = validate_player_secret(player_secret)
    if secret_error:
        flash(secret_error)
        return redirect(url_for("main.room_access_view", code=code))
    room, error = claim_second_player(code, player_name, player_secret)
    if error:
        flash(error)
        return redirect(url_for("main.room_access_view", code=code))

    memberships = session.setdefault("memberships", {})
    memberships[code] = {"slot": "two", "name": room["players"]["two"]["name"]}
    session.modified = True
    return redirect(url_for("main.room", code=code))


@main_bp.get("/room/<code>")
@login_required
def room(code):
    maybe_sync_tournament()
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    room = get_room(code)
    if room is None:
        flash("Room no longer exists.")
        return redirect(url_for("main.index"))

    membership = session["memberships"][code]
    opponent_slot = "two" if membership["slot"] == "one" else "one"
    opponent = room["players"].get(opponent_slot)
    scores = compile_room_scores(room, tournament)
    score_entries = sorted(scores.items(), key=lambda item: item[1]["total"], reverse=True)
    for _slot, card in score_entries:
        card["group_total"] = sum(item["total"] for item in card["groups"])
        card["match_total"] = sum(item["total"] for item in card["matches"])

    group_score_lookup = {
        slot: {item["group_id"]: item for item in card["groups"]}
        for slot, card in score_entries
    }
    match_score_lookup = {
        slot: {item["match_id"]: item for item in card["matches"]}
        for slot, card in score_entries
    }
    teams = team_lookup(tournament)
    matches_by_group: dict[str, list[dict]] = {}
    knockout_sections_lookup = {stage: {"stage": stage, "label": label, "matches": []} for stage, label in KNOCKOUT_STAGE_ORDER}

    def build_score_cards(item_id: str, lookup: dict[str, dict[str, dict]]):
        return [
            {
                "slot": slot,
                "name": card["name"],
                **lookup[slot][item_id],
            }
            for slot, card in score_entries
        ]

    def build_match_card(match: dict):
        prediction = room["predictions"].get(membership["slot"], {}).get("matches", {}).get(match["id"], {})
        locked = match_locked(match)
        home_team = resolve_team(match.get("home_team_id"), teams)
        away_team = resolve_team(match.get("away_team_id"), teams)
        teams_known = home_team["name"] != "TBD" and away_team["name"] != "TBD"
        opponent_prediction = room["predictions"].get(opponent_slot, {}).get("matches", {}).get(match["id"], {})
        return {
            **match,
            "home_team": home_team,
            "away_team": away_team,
            "kickoff_label": kickoff_label(match.get("kickoff_utc")),
            "locked": locked,
            "teams_known": teams_known,
            "prediction": prediction,
            "opponent_prediction": opponent_prediction if locked and opponent_prediction else None,
            "score_cards": build_score_cards(match["id"], match_score_lookup),
        }

    group_sections = []
    for group in tournament.get("groups", []):
        saved_order = room["predictions"].get(membership["slot"], {}).get("groups", {}).get(group["id"])
        ordered_ids = saved_order or [team["id"] for team in group.get("teams", [])]
        ordered_teams = [teams[team_id] for team_id in ordered_ids if team_id in teams]
        locked = group_locked(group["id"], tournament.get("matches", []))
        opponent_order = room["predictions"].get(opponent_slot, {}).get("groups", {}).get(group["id"])
        opponent_teams = []
        if locked and opponent_order:
            opponent_teams = [teams[team_id] for team_id in opponent_order if team_id in teams]
        group_score_cards = build_score_cards(group["id"], group_score_lookup)
        actual_order = next((item.get("actual_order") for item in group_score_cards if item.get("actual_order")), None)
        if actual_order is None and (group.get("actual_positions") or group_complete(group["id"], tournament.get("matches", []))):
            actual_order = actual_group_order(group, tournament.get("matches", []), teams)
        group_sections.append(
            {
                "group": {
                    **group,
                    "locked": locked,
                    "saved_order": saved_order,
                    "ordered_teams": ordered_teams,
                    "opponent_teams": opponent_teams,
                    "actual_order_teams": [teams[team_id] for team_id in actual_order if team_id in teams] if actual_order else [],
                },
                "matches": [],
                "score_cards": group_score_cards,
            }
        )
        matches_by_group[group["id"]] = group_sections[-1]["matches"]

    for match in tournament.get("matches", []):
        card = build_match_card(match)
        if match.get("group_id") and match["group_id"] in matches_by_group:
            matches_by_group[match["group_id"]].append(card)
        elif match.get("stage") in knockout_sections_lookup:
            knockout_sections_lookup[match["stage"]]["matches"].append(card)

    knockout_sections = []
    for stage, _label in KNOCKOUT_STAGE_ORDER:
        section = knockout_sections_lookup[stage]
        if not section["matches"]:
            continue
        section["locked"] = all(match["locked"] for match in section["matches"])
        knockout_sections.append(section)

    return render_template(
        "room.html",
        room=room,
        scores=scores,
        score_entries=score_entries,
        group_sections=group_sections,
        knockout_sections=knockout_sections,
        membership=membership,
        opponent=opponent,
        room_password=room.get("share_password"),
        invite_link=url_for("main.index", code=room["code"], _external=True),
    )


@main_bp.post("/room/<code>/groups/<group_id>")
@login_required
def save_group(code, group_id):
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    if group_locked(group_id, tournament.get("matches", [])):
        return save_feedback("That group is locked already.", ok=False, status_code=409, code=code)

    try:
        ordered_team_ids = json.loads(request.form.get("team_order", "[]"))
    except json.JSONDecodeError:
        return save_feedback("Invalid group order payload.", ok=False, status_code=400, code=code)
    valid_ids = {
        team["id"]
        for group in tournament.get("groups", [])
        if group["id"] == group_id
        for team in group.get("teams", [])
    }
    if set(ordered_team_ids) != valid_ids or len(ordered_team_ids) != len(valid_ids):
        return save_feedback("Invalid group order payload.", ok=False, status_code=400, code=code)

    membership = session["memberships"][code]
    save_group_prediction(code, membership["slot"], group_id, ordered_team_ids)
    return save_feedback(f"{group_id} standings saved.", ok=True, status_code=200, code=code)


@main_bp.post("/room/<code>/matches/<match_id>")
@login_required
def save_match(code, match_id):
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    match = next((item for item in tournament.get("matches", []) if item["id"] == match_id), None)
    if match is None:
        return save_feedback("Match not found.", ok=False, status_code=404, code=code)
    teams = team_lookup(tournament)
    if (
        resolve_team(match.get("home_team_id"), teams)["name"] == "TBD"
        or resolve_team(match.get("away_team_id"), teams)["name"] == "TBD"
    ):
        return save_feedback("That knockout match is not ready for predictions yet.", ok=False, status_code=409, code=code)
    if match_locked(match):
        return save_feedback("That match is locked already.", ok=False, status_code=409, code=code)

    try:
        home = int(request.form.get("home", ""))
        away = int(request.form.get("away", ""))
    except ValueError:
        return save_feedback("Use whole-number score predictions.", ok=False, status_code=400, code=code)
    if home < 0 or away < 0:
        return save_feedback("Scores cannot be negative.", ok=False, status_code=400, code=code)

    membership = session["memberships"][code]
    save_match_prediction(code, membership["slot"], match_id, home, away)
    return save_feedback("Match prediction saved.", ok=True, status_code=200, code=code)
