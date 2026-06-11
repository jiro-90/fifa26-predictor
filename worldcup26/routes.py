from __future__ import annotations

import json
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

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
from .tournament import group_locked, load_tournament, match_locked, parse_utc, resolve_team, team_lookup


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
    teams = team_lookup(tournament)
    matches_by_group: dict[str, list[dict]] = {}
    knockout_sections_lookup = {stage: {"stage": stage, "label": label, "matches": []} for stage, label in KNOCKOUT_STAGE_ORDER}

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
        group_sections.append(
            {
                "group": {
                    **group,
                    "locked": locked,
                    "ordered_teams": ordered_teams,
                    "opponent_teams": opponent_teams,
                },
                "matches": [],
            }
        )
        matches_by_group[group["id"]] = group_sections[-1]["matches"]

    for match in tournament.get("matches", []):
        card = build_match_card(match)
        if match.get("group_id") and match["group_id"] in matches_by_group:
            matches_by_group[match["group_id"]].append(card)
        elif match.get("stage") in knockout_sections_lookup:
            knockout_sections_lookup[match["stage"]]["matches"].append(card)

    knockout_sections = [
        knockout_sections_lookup[stage]
        for stage, _label in KNOCKOUT_STAGE_ORDER
        if knockout_sections_lookup[stage]["matches"]
    ]

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


@main_bp.get("/room/<code>/breakdown")
@login_required
def breakdown(code):
    maybe_sync_tournament()
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    room = get_room(code)
    if room is None:
        flash("Room no longer exists.")
        return redirect(url_for("main.index"))

    scores = compile_room_scores(room, tournament)
    score_entries = sorted(scores.items(), key=lambda item: item[1]["total"], reverse=True)

    for _slot, card in score_entries:
        card["group_total"] = sum(item["total"] for item in card["groups"])
        card["match_total"] = sum(item["total"] for item in card["matches"])
        card["group_scored"] = [item for item in card["groups"] if item["total"] > 0]
        card["group_pending"] = [item for item in card["groups"] if item["total"] == 0]
        card["match_scored"] = [item for item in card["matches"] if item["total"] > 0]
        card["match_pending"] = [item for item in card["matches"] if item["total"] == 0]

    return render_template(
        "breakdown.html",
        room=room,
        score_entries=score_entries,
    )


@main_bp.post("/room/<code>/groups/<group_id>")
@login_required
def save_group(code, group_id):
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    if group_locked(group_id, tournament.get("matches", [])):
        flash("That group is locked already.")
        return redirect(url_for("main.room", code=code))

    try:
        ordered_team_ids = json.loads(request.form.get("team_order", "[]"))
    except json.JSONDecodeError:
        flash("Invalid group order payload.")
        return redirect(url_for("main.room", code=code))
    valid_ids = {
        team["id"]
        for group in tournament.get("groups", [])
        if group["id"] == group_id
        for team in group.get("teams", [])
    }
    if set(ordered_team_ids) != valid_ids or len(ordered_team_ids) != len(valid_ids):
        flash("Invalid group order payload.")
        return redirect(url_for("main.room", code=code))

    membership = session["memberships"][code]
    save_group_prediction(code, membership["slot"], group_id, ordered_team_ids)
    flash(f"{group_id} standings saved.")
    return redirect(url_for("main.room", code=code))


@main_bp.post("/room/<code>/matches/<match_id>")
@login_required
def save_match(code, match_id):
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    match = next((item for item in tournament.get("matches", []) if item["id"] == match_id), None)
    if match is None:
        flash("Match not found.")
        return redirect(url_for("main.room", code=code))
    teams = team_lookup(tournament)
    if (
        resolve_team(match.get("home_team_id"), teams)["name"] == "TBD"
        or resolve_team(match.get("away_team_id"), teams)["name"] == "TBD"
    ):
        flash("That knockout match is not ready for predictions yet.")
        return redirect(url_for("main.room", code=code))
    if match_locked(match):
        flash("That match is locked already.")
        return redirect(url_for("main.room", code=code))

    try:
        home = int(request.form.get("home", ""))
        away = int(request.form.get("away", ""))
    except ValueError:
        flash("Use whole-number score predictions.")
        return redirect(url_for("main.room", code=code))
    if home < 0 or away < 0:
        flash("Scores cannot be negative.")
        return redirect(url_for("main.room", code=code))

    membership = session["memberships"][code]
    save_match_prediction(code, membership["slot"], match_id, home, away)
    flash("Match prediction saved.")
    return redirect(url_for("main.room", code=code))
