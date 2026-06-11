from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

import requests
from flask import current_app

from .filedb import load_json, save_json_atomic
from .tournament import load_tournament, parse_utc, save_tournament


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


class SyncProvider:
    def sync(self, tournament: dict[str, Any]) -> dict[str, Any]:
        return {"updated_matches": 0, "provider": "none", "notes": ["No provider configured"]}


class FootballDataProvider(SyncProvider):
    STAGE_MAP = {
        "GROUP_STAGE": "GROUP",
        "LAST_32": "ROUND_OF_32",
        "LAST_16": "ROUND_OF_16",
        "QUARTER_FINALS": "QUARTER_FINAL",
        "SEMI_FINALS": "SEMI_FINAL",
        "THIRD_PLACE": "THIRD_PLACE",
        "FINAL": "FINAL",
    }

    def __init__(self, api_key: str, base_url: str, competition: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.competition = competition

    @staticmethod
    def normalize_text(value: str | None) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower().replace("&", " and ")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    def build_team_alias_map(self, tournament: dict[str, Any]) -> dict[str, str]:
        explicit_aliases = {
            "south korea": "kor",
            "korea republic": "kor",
            "czech republic": "cze",
            "czechia": "cze",
            "turkey": "tur",
            "turkiye": "tur",
            "ivory coast": "civ",
            "cote d ivoire": "civ",
            "cote divoire": "civ",
            "curacao": "cuw",
            "cura ao": "cuw",
            "dr congo": "cod",
            "democratic republic of the congo": "cod",
            "england": "eng",
            "scotland": "sco",
        }
        aliases = {self.normalize_text(key): value for key, value in explicit_aliases.items()}
        for group in tournament.get("groups", []):
            for team in group.get("teams", []):
                aliases[self.normalize_text(team.get("id"))] = team["id"]
                aliases[self.normalize_text(team.get("name"))] = team["id"]
                aliases[self.normalize_text(team.get("fifa_code"))] = team["id"]
        return aliases

    def map_api_team(self, api_team: dict[str, Any] | None, aliases: dict[str, str]) -> str | None:
        if not api_team:
            return None
        candidates = [
            api_team.get("tla"),
            api_team.get("shortName"),
            api_team.get("name"),
        ]
        for candidate in candidates:
            mapped = aliases.get(self.normalize_text(candidate))
            if mapped:
                return mapped
        return None

    def map_stage(self, stage: str | None) -> str | None:
        return self.STAGE_MAP.get(stage or "")

    def map_group(self, group_name: str | None) -> str | None:
        if not group_name:
            return None
        normalized = group_name.removeprefix("GROUP_")
        return normalized if len(normalized) == 1 else None

    def match_sort_key(self, match: dict[str, Any]) -> tuple[Any, ...]:
        kickoff = parse_utc(match.get("kickoff_utc"))
        return (
            match.get("stage") or "",
            kickoff.isoformat() if kickoff else "",
            match.get("venue") or "",
            match.get("id") or "",
        )

    def find_local_match(
        self,
        api_match: dict[str, Any],
        local_matches: list[dict[str, Any]],
        aliases: dict[str, str],
        used_ids: set[str],
    ) -> dict[str, Any] | None:
        api_id = str(api_match.get("id"))
        for local_match in local_matches:
            if local_match.get("id") in used_ids:
                continue
            if str(local_match.get("external_id")) == api_id:
                return local_match

        mapped_stage = self.map_stage(api_match.get("stage"))
        mapped_group = self.map_group(api_match.get("group"))
        mapped_home = self.map_api_team(api_match.get("homeTeam"), aliases)
        mapped_away = self.map_api_team(api_match.get("awayTeam"), aliases)
        api_kickoff = api_match.get("utcDate")
        api_venue = self.normalize_text(api_match.get("venue"))

        best_match = None
        best_score = -1
        for local_match in local_matches:
            if local_match.get("id") in used_ids:
                continue

            score = 0
            if local_match.get("stage") == mapped_stage:
                score += 3
            if local_match.get("group_id") == mapped_group and mapped_group:
                score += 3
            if local_match.get("kickoff_utc") == api_kickoff and api_kickoff:
                score += 5
            if api_venue and self.normalize_text(local_match.get("venue")) == api_venue:
                score += 4
            if mapped_home and local_match.get("home_team_id") == mapped_home:
                score += 6
            if mapped_away and local_match.get("away_team_id") == mapped_away:
                score += 6
            if (
                mapped_home
                and mapped_away
                and {local_match.get("home_team_id"), local_match.get("away_team_id")} == {mapped_home, mapped_away}
            ):
                score += 2

            if score > best_score:
                best_match = local_match
                best_score = score

        return best_match if best_score >= 8 else None

    def update_match_from_api(
        self,
        local_match: dict[str, Any],
        api_match: dict[str, Any],
        aliases: dict[str, str],
    ):
        local_match["external_id"] = api_match.get("id")
        local_match["status"] = api_match.get("status", local_match.get("status", "SCHEDULED"))
        local_match["kickoff_utc"] = api_match.get("utcDate", local_match.get("kickoff_utc"))
        if api_match.get("venue"):
            local_match["venue"] = api_match.get("venue")

        mapped_stage = self.map_stage(api_match.get("stage"))
        if mapped_stage:
            local_match["stage"] = mapped_stage

        mapped_group = self.map_group(api_match.get("group"))
        if mapped_group:
            local_match["group_id"] = mapped_group

        mapped_home = self.map_api_team(api_match.get("homeTeam"), aliases)
        mapped_away = self.map_api_team(api_match.get("awayTeam"), aliases)
        if mapped_home:
            local_match["home_team_id"] = mapped_home
        if mapped_away:
            local_match["away_team_id"] = mapped_away

        score_node = api_match.get("score", {})
        full_time = score_node.get("fullTime", {})
        if full_time.get("home") is not None:
            local_match["home_score"] = full_time.get("home")
        if full_time.get("away") is not None:
            local_match["away_score"] = full_time.get("away")

        local_match["result_updated_at"] = utc_timestamp()

    def update_group_positions(self, tournament: dict[str, Any], standings_payload: dict[str, Any], aliases: dict[str, str]) -> int:
        groups = {group["id"]: group for group in tournament.get("groups", [])}
        updated = 0
        for standing in standings_payload.get("standings", []):
            if standing.get("type") != "TOTAL":
                continue
            group_id = self.map_group(standing.get("group"))
            if not group_id or group_id not in groups:
                continue

            actual_positions = []
            for row in standing.get("table", []):
                team_id = self.map_api_team(row.get("team"), aliases)
                if team_id:
                    actual_positions.append(team_id)

            if len(actual_positions) == len(groups[group_id].get("teams", [])):
                groups[group_id]["actual_positions"] = actual_positions
                updated += 1
        return updated

    def sync(self, tournament: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Auth-Token": self.api_key}
        matches_url = f"{self.base_url}/competitions/{self.competition}/matches"
        standings_url = f"{self.base_url}/competitions/{self.competition}/standings"
        matches_response = requests.get(matches_url, headers=headers, timeout=20)
        matches_response.raise_for_status()
        matches_payload = matches_response.json()
        standings_response = requests.get(standings_url, headers=headers, timeout=20)
        standings_response.raise_for_status()
        standings_payload = standings_response.json()

        api_matches = matches_payload.get("matches", [])
        aliases = self.build_team_alias_map(tournament)
        local_matches = sorted(tournament.get("matches", []), key=self.match_sort_key)
        updated_matches = 0
        used_local_ids: set[str] = set()

        for api_match in api_matches:
            local_match = self.find_local_match(api_match, local_matches, aliases, used_local_ids)
            if local_match is None:
                continue
            self.update_match_from_api(local_match, api_match, aliases)
            used_local_ids.add(local_match["id"])
            updated_matches += 1

        updated_groups = self.update_group_positions(tournament, standings_payload, aliases)

        return {
            "updated_matches": updated_matches,
            "updated_groups": updated_groups,
            "provider": "football-data.org",
            "notes": [
                f"Fetched {len(api_matches)} competition matches",
                f"Mapped {updated_matches} local matches",
                f"Updated {updated_groups} group standings",
            ],
        }


def select_provider():
    provider_name = current_app.config["PROVIDER"]
    if provider_name == "football-data" and current_app.config["FOOTBALL_DATA_API_KEY"]:
        return FootballDataProvider(
            current_app.config["FOOTBALL_DATA_API_KEY"],
            current_app.config["FOOTBALL_DATA_BASE_URL"],
            current_app.config["FOOTBALL_DATA_COMPETITION"],
        )
    return SyncProvider()


def sync_tournament() -> dict[str, Any]:
    tournament = load_tournament(current_app.config["TOURNAMENT_FILE"])
    provider = select_provider()
    summary = provider.sync(tournament)
    save_tournament(current_app.config["TOURNAMENT_FILE"], tournament)
    save_json_atomic(
        current_app.config["LAST_SYNC_FILE"],
        {"last_sync_at": utc_timestamp(), "summary": summary},
    )
    return summary


def maybe_sync_tournament() -> dict[str, Any] | None:
    state = load_json(current_app.config["LAST_SYNC_FILE"], {})
    last_sync_at = state.get("last_sync_at")
    if last_sync_at:
        last_sync = datetime.fromisoformat(last_sync_at)
        seconds = (datetime.now(UTC) - last_sync).total_seconds()
        if seconds < current_app.config["SYNC_INTERVAL_SECONDS"]:
            return None
    return sync_tournament()
