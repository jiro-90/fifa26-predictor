from __future__ import annotations

import random
from functools import wraps
from datetime import UTC

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from .africaweather_rooms import (
    add_team_members,
    create_room,
    get_room,
    join_team,
    save_group_prediction,
    save_podium_prediction,
    validate_player_secret,
    verify_room_access,
    verify_team_login,
)
from .africaweather_scoring import compile_room_scores, room_deadline_label, room_locked
from .sync import maybe_sync_tournament
from .tournament import actual_group_order, group_complete, group_has_finished_match, load_tournament, parse_utc, team_lookup


aw_bp = Blueprint("africaweather", __name__, url_prefix="/africaweather")
MEMBER_SLOT_COUNT = 6


def access_granted(code: str) -> bool:
    return bool(session.get("aw_room_access", {}).get(code.upper()))


def wants_json_response() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def save_feedback(message: str, ok: bool, status_code: int, code: str):
    if wants_json_response():
        return jsonify({"ok": ok, "message": message}), status_code
    flash(message)
    return redirect(url_for("africaweather.room", code=code))


def login_required(view):
    @wraps(view)
    def wrapped(code, *args, **kwargs):
        membership = session.get("aw_memberships", {}).get(code.upper())
        if membership is None:
            flash("Join the room first.")
            return redirect(url_for("africaweather.index"))
        return view(code.upper(), *args, **kwargs)

    return wrapped


def member_slots() -> range:
    return range(1, MEMBER_SLOT_COUNT + 1)


def collect_member_rows(form) -> list[dict[str, str]]:
    return [
        {
            "name": form.get(f"member_name_{slot}", ""),
            "gamer_name": form.get(f"member_gamer_{slot}", ""),
        }
        for slot in member_slots()
    ]


def parse_deadline_input(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parsed = parse_utc(raw) if raw.endswith("Z") or "+" in raw else parse_utc(f"{raw}:00Z")
    if parsed is None:
        return None
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_randomizer_names(raw_names: str) -> list[str]:
    return [line.strip() for line in raw_names.splitlines() if line.strip()]


def build_randomized_teams(names: list[str], team_count: int, prefix: str) -> list[dict[str, object]]:
    shuffled = names[:]
    random.SystemRandom().shuffle(shuffled)
    teams = [{"name": f"{prefix} {index + 1}", "members": []} for index in range(team_count)]
    for index, person in enumerate(shuffled):
        teams[index % team_count]["members"].append(person)
    return teams


@aw_bp.get("/")
def index():
    return render_template("africaweather/index.html", member_slots=member_slots())


@aw_bp.route("/tools", methods=["GET", "POST"])
def tools():
    names_text = ""
    team_count = 2
    team_prefix = "Team"
    randomized_teams = None

    if request.method == "POST":
        names_text = request.form.get("names", "")
        team_prefix = request.form.get("team_prefix", "").strip() or "Team"
        try:
            team_count = int(request.form.get("team_count", "2"))
        except ValueError:
            team_count = 0

        names = normalize_randomizer_names(names_text)
        if len(names) < 2:
            flash("Enter at least two names to randomize.")
        elif team_count < 2:
            flash("Choose at least two teams.")
        elif team_count > len(names):
            flash("Team count cannot be higher than the number of names.")
        else:
            randomized_teams = build_randomized_teams(names, team_count, team_prefix)

    return render_template(
        "africaweather/tools.html",
        names_text=names_text,
        team_count=team_count,
        team_prefix=team_prefix,
        randomized_teams=randomized_teams,
    )


@aw_bp.post("/create-room")
def create_room_view():
    room_name = request.form.get("room_name", "").strip()
    team_name = request.form.get("team_name", "").strip()
    team_secret = request.form.get("team_secret", "").strip()
    deadline_value = parse_deadline_input(request.form.get("prediction_deadline", ""))
    if not room_name:
        flash("Enter a room name.")
        return redirect(url_for("africaweather.index"))
    if not team_name:
        flash("Enter a team name.")
        return redirect(url_for("africaweather.index"))
    if not deadline_value:
        flash("Enter a valid room deadline in UTC.")
        return redirect(url_for("africaweather.index"))
    secret_error = validate_player_secret(team_secret)
    if secret_error:
        flash(secret_error.replace("Personal login password", "Team password"))
        return redirect(url_for("africaweather.index"))

    try:
        created = create_room(room_name, team_name, team_secret, collect_member_rows(request.form), deadline_value)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("africaweather.index"))

    room = created["room"]
    room_access = session.setdefault("aw_room_access", {})
    room_access[room["code"]] = True
    memberships = session.setdefault("aw_memberships", {})
    memberships[room["code"]] = {"team_id": created["team_id"], "team_name": team_name}
    session.modified = True
    return redirect(url_for("africaweather.room", code=room["code"]))


@aw_bp.post("/join-room")
def join_room_view():
    code = request.form.get("code", "").strip().upper()
    password = request.form.get("password", "").strip()
    if not code or not password:
        flash("Code and password are required.")
        return redirect(url_for("africaweather.index"))

    room, error = verify_room_access(code, password)
    if error:
        flash(error)
        return redirect(url_for("africaweather.index"))

    room_access = session.setdefault("aw_room_access", {})
    room_access[code] = True
    session.modified = True

    if session.get("aw_memberships", {}).get(code):
        return redirect(url_for("africaweather.room", code=code))
    return redirect(url_for("africaweather.room_access_view", code=room["code"]))


@aw_bp.get("/rules")
def rules():
    return render_template("africaweather/rules.html")


@aw_bp.get("/room/<code>/access")
def room_access_view(code):
    code = code.upper()
    if session.get("aw_memberships", {}).get(code):
        return redirect(url_for("africaweather.room", code=code))
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("africaweather.index"))

    room = get_room(code)
    if room is None:
        flash("Room not found.")
        return redirect(url_for("africaweather.index"))
    return render_template("africaweather/room_access.html", room=room, member_slots=member_slots())


@aw_bp.post("/room/<code>/relogin/<team_id>")
def room_relogin(code, team_id):
    code = code.upper()
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("africaweather.index"))

    room = get_room(code)
    if room is None:
        flash("Room not found.")
        return redirect(url_for("africaweather.index"))

    team_secret = request.form.get("team_secret", "").strip()
    if not verify_team_login(room, team_id, team_secret):
        flash("Incorrect team password.")
        return redirect(url_for("africaweather.room_access_view", code=code))

    team = room.get("teams", {}).get(team_id)
    memberships = session.setdefault("aw_memberships", {})
    memberships[code] = {"team_id": team_id, "team_name": team["name"]}
    session.modified = True
    return redirect(url_for("africaweather.room", code=code))


@aw_bp.post("/room/<code>/join")
def room_join_new_team(code):
    code = code.upper()
    if not access_granted(code):
        flash("Enter the room code and password first.")
        return redirect(url_for("africaweather.index"))

    team_name = request.form.get("team_name", "").strip()
    team_secret = request.form.get("team_secret", "").strip()
    secret_error = validate_player_secret(team_secret)
    if secret_error:
        flash(secret_error.replace("Personal login password", "Team password"))
        return redirect(url_for("africaweather.room_access_view", code=code))

    room, error, team_id = join_team(code, team_name, team_secret, collect_member_rows(request.form))
    if error:
        flash(error)
        return redirect(url_for("africaweather.room_access_view", code=code))

    memberships = session.setdefault("aw_memberships", {})
    memberships[code] = {"team_id": team_id, "team_name": room["teams"][team_id]["name"]}
    session.modified = True
    return redirect(url_for("africaweather.room", code=code))


@aw_bp.get("/room/<code>")
@login_required
def room(code):
    maybe_sync_tournament()
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    room = get_room(code)
    if room is None:
        flash("Room no longer exists.")
        return redirect(url_for("africaweather.index"))

    membership = session["aw_memberships"][code]
    current_team_id = membership["team_id"]
    scores = compile_room_scores(room, tournament)
    score_entries = sorted(scores.items(), key=lambda item: (-item[1]["total"], item[1]["name"].lower()))
    for _team_id, card in score_entries:
        card["group_total"] = sum(item["total"] for item in card["groups"])
        card["podium_total"] = card["podium"]["total"]

    teams = team_lookup(tournament)
    matches = tournament.get("matches", [])
    deadline_label = room_deadline_label(room)
    room_is_locked = room_locked(room)
    current_predictions = room.get("predictions", {}).get(current_team_id, {})
    podium_saved = current_predictions.get("podium") or []
    podium_saved = [team_id for team_id in podium_saved if team_id in teams]
    podium_saved = podium_saved if len(podium_saved) == 3 and len(set(podium_saved)) == 3 else []
    podium_selection = podium_saved or ["", "", ""]
    actual_top_three = tournament.get("tournament", {}).get("actual_top_three") or []
    actual_top_three_teams = [teams[team_id] for team_id in actual_top_three if team_id in teams]

    podium_score_cards = [
        {
            "team_id": team_id,
            "name": card["name"],
            "members": room["teams"][team_id].get("members", []),
            "prediction": room.get("predictions", {}).get(team_id, {}).get("podium") or [],
            "prediction_teams": [
                teams[predicted_id]
                for predicted_id in (room.get("predictions", {}).get(team_id, {}).get("podium") or [])
                if predicted_id in teams
            ],
            **card["podium"],
        }
        for team_id, card in score_entries
    ]

    group_sections = []
    for group in tournament.get("groups", []):
        saved_top_two = current_predictions.get("groups", {}).get(group["id"])
        saved_top_two = saved_top_two if isinstance(saved_top_two, list) and len(saved_top_two) == 2 else []
        score_cards = []
        for team_id, card in score_entries:
            prediction = room.get("predictions", {}).get(team_id, {}).get("groups", {}).get(group["id"]) or []
            prediction_teams = [teams[predicted_id] for predicted_id in prediction if predicted_id in teams]
            score_cards.append(
                {
                    "team_id": team_id,
                    "name": card["name"],
                    "members": room["teams"][team_id].get("members", []),
                    "prediction_teams": prediction_teams,
                    **next(item for item in card["groups"] if item["group_id"] == group["id"]),
                }
            )

        actual_order = next((item.get("actual_order") for item in score_cards if item.get("actual_order")), None)
        if actual_order is None and (group.get("actual_positions") or group_complete(group["id"], matches) or group_has_finished_match(group["id"], matches)):
            actual_order = actual_group_order(group, matches, teams)

        group_sections.append(
            {
                "group": {
                    **group,
                    "locked": room_is_locked,
                    "saved_top_two": saved_top_two,
                    "actual_top_two": [teams[team_id] for team_id in (actual_order or [])[:2] if team_id in teams],
                    "table_is_final": bool(group.get("actual_positions") or group_complete(group["id"], matches)),
                },
                "score_cards": score_cards,
                "all_saved": bool(saved_top_two),
            }
        )

    return render_template(
        "africaweather/room.html",
        room=room,
        membership=membership,
        score_entries=score_entries,
        podium={
            "locked": room_is_locked,
            "deadline_label": deadline_label,
            "saved_order": podium_saved,
            "selection": podium_selection,
            "actual_top_three": actual_top_three_teams,
            "score_cards": podium_score_cards,
        },
        group_sections=group_sections,
        deadline_label=deadline_label,
        invite_link=url_for("africaweather.index", code=room["code"], _external=True),
        public_link=url_for("africaweather.public_room", code=room["code"], _external=True),
        member_slots=member_slots(),
    )


@aw_bp.post("/room/<code>/team-members")
@login_required
def add_members(code):
    room = get_room(code)
    if room is None:
        return save_feedback("Room not found.", ok=False, status_code=404, code=code)

    membership = session["aw_memberships"][code]
    _room, error = add_team_members(code, membership["team_id"], collect_member_rows(request.form))
    if error:
        return save_feedback(error, ok=False, status_code=400, code=code)
    return save_feedback("Team members added.", ok=True, status_code=200, code=code)


@aw_bp.get("/public/<code>")
def public_room(code):
    code = code.upper()
    room = get_room(code)
    if room is None:
        flash("Room not found.")
        return redirect(url_for("africaweather.index"))

    locked = room_locked(room)
    deadline_label = room_deadline_label(room)
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    scores = compile_room_scores(room, tournament)
    score_entries = sorted(scores.items(), key=lambda item: (-item[1]["total"], item[1]["name"].lower()))
    for _team_id, card in score_entries:
        card["group_total"] = sum(item["total"] for item in card["groups"])
        card["podium_total"] = card["podium"]["total"]

    return render_template(
        "africaweather/public_room.html",
        room=room,
        locked=locked,
        deadline_label=deadline_label,
        score_entries=score_entries,
    )


@aw_bp.post("/room/<code>/podium")
@login_required
def save_podium(code):
    room = get_room(code)
    if room is None:
        return save_feedback("Room not found.", ok=False, status_code=404, code=code)
    if room_locked(room):
        return save_feedback("Top 3 selection is locked already.", ok=False, status_code=409, code=code)

    team_ids = request.form.getlist("team_ids")
    if len(team_ids) != 3:
        return save_feedback("Choose exactly three teams.", ok=False, status_code=400, code=code)

    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    valid_ids = {team["id"] for group in tournament.get("groups", []) for team in group.get("teams", [])}
    if any(team_id not in valid_ids for team_id in team_ids) or len(set(team_ids)) != 3:
        return save_feedback("Choose three different valid teams.", ok=False, status_code=400, code=code)

    membership = session["aw_memberships"][code]
    save_podium_prediction(code, membership["team_id"], team_ids)
    return save_feedback("Top 3 saved.", ok=True, status_code=200, code=code)


@aw_bp.post("/room/<code>/groups/<group_id>")
@login_required
def save_group(code, group_id):
    room = get_room(code)
    if room is None:
        return save_feedback("Room not found.", ok=False, status_code=404, code=code)
    if room_locked(room):
        return save_feedback("This room is locked already.", ok=False, status_code=409, code=code)

    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    team_ids = request.form.getlist("team_ids")
    if len(team_ids) != 2:
        return save_feedback("Choose exactly two teams.", ok=False, status_code=400, code=code)
    valid_ids = {
        team["id"]
        for group in tournament.get("groups", [])
        if group["id"] == group_id
        for team in group.get("teams", [])
    }
    if any(team_id not in valid_ids for team_id in team_ids) or len(set(team_ids)) != 2:
        return save_feedback("Choose two different teams from this group.", ok=False, status_code=400, code=code)

    membership = session["aw_memberships"][code]
    save_group_prediction(code, membership["team_id"], group_id, team_ids)
    return save_feedback(f"{group_id} top two saved.", ok=True, status_code=200, code=code)
