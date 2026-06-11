import argparse
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TOURNAMENT_FILE = BASE_DIR / "data" / "tournament.json"
ROOMS_FILE = BASE_DIR / "data" / "rooms.json"
LAST_SYNC_FILE = BASE_DIR / "data" / "last_sync.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def find_match(tournament, match_id: str):
    for match in tournament.get("matches", []):
        if match["id"] == match_id:
            return match
    raise SystemExit(f"Match {match_id} not found.")


def reset_runtime_state():
    save_json(ROOMS_FILE, {"rooms": {}})
    save_json(LAST_SYNC_FILE, {})
    print("Reset rooms.json and last_sync.json")


def list_matches(limit: int):
    tournament = load_json(TOURNAMENT_FILE)
    for match in tournament.get("matches", [])[:limit]:
        print(
            f'{match["id"]}: {match["stage"]} '
            f'group={match.get("group_id")} '
            f'kickoff={match.get("kickoff_utc")} '
            f'{match.get("home_team_id")} vs {match.get("away_team_id")} '
            f'status={match.get("status")}'
        )


def set_match_kickoff(match_id: str, kickoff_utc: str):
    tournament = load_json(TOURNAMENT_FILE)
    match = find_match(tournament, match_id)
    match["kickoff_utc"] = kickoff_utc
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Updated {match_id} kickoff to {kickoff_utc}")


def set_group_kickoff(group_id: str, kickoff_utc: str):
    tournament = load_json(TOURNAMENT_FILE)
    count = 0
    for match in tournament.get("matches", []):
        if match.get("group_id") == group_id:
            match["kickoff_utc"] = kickoff_utc
            count += 1
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Updated {count} matches in group {group_id} to kickoff {kickoff_utc}")


def finish_match(match_id: str, home: int, away: int):
    tournament = load_json(TOURNAMENT_FILE)
    match = find_match(tournament, match_id)
    match["status"] = "FINISHED"
    match["home_score"] = home
    match["away_score"] = away
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Marked {match_id} as FINISHED with score {home}-{away}")


def set_match_teams(match_id: str, home_team_id: str, away_team_id: str):
    tournament = load_json(TOURNAMENT_FILE)
    match = find_match(tournament, match_id)
    match["home_team_id"] = home_team_id
    match["away_team_id"] = away_team_id
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Set {match_id} teams to {home_team_id} vs {away_team_id}")


def set_group_positions(group_id: str, team_ids: list[str]):
    tournament = load_json(TOURNAMENT_FILE)
    group = next((group for group in tournament.get("groups", []) if group["id"] == group_id), None)
    if group is None:
        raise SystemExit(f"Group {group_id} not found.")
    valid_ids = {team["id"] for team in group.get("teams", [])}
    if set(team_ids) != valid_ids or len(team_ids) != len(valid_ids):
        raise SystemExit(f"Group {group_id} expects exactly these teams: {sorted(valid_ids)}")
    group["actual_positions"] = team_ids
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Set Group {group_id} actual positions to: {' > '.join(team_ids)}")


def reset_group_positions(group_id: str):
    tournament = load_json(TOURNAMENT_FILE)
    group = next((group for group in tournament.get("groups", []) if group["id"] == group_id), None)
    if group is None:
        raise SystemExit(f"Group {group_id} not found.")
    group.pop("actual_positions", None)
    save_json(TOURNAMENT_FILE, tournament)
    print(f"Removed actual_positions from Group {group_id}")


def main():
    parser = argparse.ArgumentParser(description="Local demo helpers for FIFA 26 Duel")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("reset-runtime", help="Clear rooms and sync state")

    list_parser = sub.add_parser("list-matches", help="Print a few matches")
    list_parser.add_argument("--limit", type=int, default=12)

    kickoff_parser = sub.add_parser("set-kickoff", help="Set one match kickoff")
    kickoff_parser.add_argument("match_id")
    kickoff_parser.add_argument("kickoff_utc")

    group_kickoff_parser = sub.add_parser("set-group-kickoff", help="Set all group match kickoffs")
    group_kickoff_parser.add_argument("group_id")
    group_kickoff_parser.add_argument("kickoff_utc")

    finish_parser = sub.add_parser("finish-match", help="Set a match to FINISHED with a score")
    finish_parser.add_argument("match_id")
    finish_parser.add_argument("home", type=int)
    finish_parser.add_argument("away", type=int)

    teams_parser = sub.add_parser("set-match-teams", help="Assign teams to a knockout match")
    teams_parser.add_argument("match_id")
    teams_parser.add_argument("home_team_id")
    teams_parser.add_argument("away_team_id")

    group_parser = sub.add_parser("set-group-positions", help="Set final standings for one group")
    group_parser.add_argument("group_id")
    group_parser.add_argument("team_ids", nargs="+")

    group_reset_parser = sub.add_parser("reset-group-positions", help="Remove stored group standings")
    group_reset_parser.add_argument("group_id")

    args = parser.parse_args()
    if args.command == "reset-runtime":
        reset_runtime_state()
    elif args.command == "list-matches":
        list_matches(args.limit)
    elif args.command == "set-kickoff":
        set_match_kickoff(args.match_id, args.kickoff_utc)
    elif args.command == "set-group-kickoff":
        set_group_kickoff(args.group_id, args.kickoff_utc)
    elif args.command == "finish-match":
        finish_match(args.match_id, args.home, args.away)
    elif args.command == "set-match-teams":
        set_match_teams(args.match_id, args.home_team_id, args.away_team_id)
    elif args.command == "set-group-positions":
        set_group_positions(args.group_id, args.team_ids)
    elif args.command == "reset-group-positions":
        reset_group_positions(args.group_id)


if __name__ == "__main__":
    main()
