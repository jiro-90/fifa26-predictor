from __future__ import annotations

import json
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .rooms import create_room, get_room, join_room, save_group_prediction, save_match_prediction
from .scoring import compile_room_scores
from .sync import maybe_sync_tournament, sync_tournament
from .tournament import group_locked, load_tournament, match_locked, parse_utc, resolve_team, team_lookup


main_bp = Blueprint("main", __name__)


def kickoff_label(value: str | None) -> str:
    kickoff = parse_utc(value)
    if kickoff is None:
        return "TBD"
    return kickoff.strftime("%d %b %Y · %H:%M UTC")


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
    if not player_name:
        flash("Enter your name to create a room.")
        return redirect(url_for("main.index"))

    created = create_room(player_name)
    room = created["room"]
    memberships = session.setdefault("memberships", {})
    memberships[room["code"]] = {"slot": "one", "name": player_name}
    session.modified = True
    session["new_room_password"] = created["password"]
    return redirect(url_for("main.room", code=room["code"]))


@main_bp.post("/join-room")
def join_room_view():
    code = request.form.get("code", "").strip().upper()
    password = request.form.get("password", "").strip()
    player_name = request.form.get("player_name", "").strip()
    if not code or not password or not player_name:
        flash("Code, password and player name are all required.")
        return redirect(url_for("main.index"))

    room, error, slot = join_room(code, password, player_name)
    if error:
        flash(error)
        return redirect(url_for("main.index"))

    memberships = session.setdefault("memberships", {})
    memberships[code] = {"slot": slot, "name": player_name}
    session.modified = True
    return redirect(url_for("main.room", code=code))


@main_bp.get("/rules")
def rules():
    return render_template("rules.html")


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

    group_cards = []
    for group in tournament.get("groups", []):
        saved_order = room["predictions"].get(membership["slot"], {}).get("groups", {}).get(group["id"])
        ordered_ids = saved_order or [team["id"] for team in group.get("teams", [])]
        ordered_teams = [teams[team_id] for team_id in ordered_ids if team_id in teams]
        locked = group_locked(group["id"], tournament.get("matches", []))
        opponent_order = room["predictions"].get(opponent_slot, {}).get("groups", {}).get(group["id"])
        opponent_teams = []
        if locked and opponent_order:
            opponent_teams = [teams[team_id] for team_id in opponent_order if team_id in teams]
        group_cards.append(
            {
                **group,
                "locked": locked,
                "ordered_teams": ordered_teams,
                "opponent_teams": opponent_teams,
            }
        )

    matches = []
    for match in tournament.get("matches", []):
        prediction = room["predictions"].get(membership["slot"], {}).get("matches", {}).get(match["id"], {})
        locked = match_locked(match)
        home_team = resolve_team(match.get("home_team_id"), teams)
        away_team = resolve_team(match.get("away_team_id"), teams)
        teams_known = home_team["name"] != "TBD" and away_team["name"] != "TBD"
        opponent_prediction = room["predictions"].get(opponent_slot, {}).get("matches", {}).get(match["id"], {})
        matches.append(
            {
                **match,
                "home_team": home_team,
                "away_team": away_team,
                "kickoff_label": kickoff_label(match.get("kickoff_utc")),
                "locked": locked,
                "teams_known": teams_known,
                "prediction": prediction,
                "opponent_prediction": opponent_prediction if locked and opponent_prediction else None,
            }
        )

    return render_template(
        "room.html",
        room=room,
        scores=scores,
        score_entries=score_entries,
        group_cards=group_cards,
        matches=matches,
        membership=membership,
        opponent=opponent,
        room_password=session.pop("new_room_password", None),
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
    if resolve_team(match.get("home_team_id"), teams)["name"] == "TBD" or resolve_team(match.get("away_team_id"), teams)["name"] == "TBD":
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


@main_bp.post("/admin/sync")
def admin_sync():
    admin_key = current_app.config["ADMIN_SYNC_KEY"]
    if not admin_key or request.headers.get("X-Admin-Sync-Key") != admin_key:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    summary = sync_tournament()
    return jsonify({"ok": True, "summary": summary})
