"""Normalize ESPN data without allowing current state to masquerade as history."""
from datetime import datetime, timezone
import math


def number(value, *, required=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        if required:
            raise ValueError("ESPN required score is missing or nonnumeric")
        return None
    return value


def periods(data):
    mapping = data.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriods")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("ESPN matchup-period mapping missing")
    return {int(k): [int(v) for v in values] for k, values in mapping.items()}


def latest_completed(data):
    status = data.get("status", {})
    current = data.get("scoringPeriodId")
    final = status.get("finalScoringPeriod")
    latest = status.get("latestScoringPeriod")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (current, final, latest)):
        raise ValueError("ESPN completion status missing")
    # ESPN advancing its own scoring period is necessary. A calendar date is not evidence.
    upper = min(current - 1, final, latest)
    mapping = periods(data)
    schedule = data.get("schedule", [])
    for week in range(upper, 0, -1):
        ids = [pid for pid, weeks in mapping.items() if weeks == [week]]
        games = [g for g in schedule if g.get("matchupPeriodId") in ids]
        if games and all(not g.get("away") or g.get("winner") in ("HOME", "AWAY", "TIE") for g in games):
            return week
    return None


def side_score(side, week, *, single_period=True):
    by_period = side.get("pointsByScoringPeriod", {})
    if str(week) in by_period:
        return number(by_period[str(week)], required=True)
    if single_period:
        return number(side.get("totalPoints"), required=True)
    raise ValueError("Missing per-scoring-period score")


def parse_roster(side, week, season):
    entries = side.get("rosterForCurrentScoringPeriod", {}).get("entries")
    if not isinstance(entries, list):
        return None
    players = []
    for entry in entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        stats = [s for s in player.get("stats", []) if s.get("scoringPeriodId") == week
                 and s.get("seasonId") == season and s.get("statSplitTypeId") == 1]
        def stat(source):
            values = [number(s.get("appliedTotal")) for s in stats if s.get("statSourceId") == source]
            return values[0] if len(values) == 1 else None
        slot = entry.get("lineupSlotId")
        if not isinstance(slot, int) or not isinstance(player.get("id"), int):
            raise ValueError("Malformed roster entry")
        players.append({"id": player["id"], "name": player.get("fullName", str(player["id"])),
                        "score": stat(0), "projected": stat(1), "slot_id": slot,
                        "eligible_slots": player.get("eligibleSlots", []), "starter": slot not in (20, 21)})
    return {"team_id": side["teamId"], "players": players}


def parse_transactions(rows, week):
    result, warnings = [], []
    for row in rows:
        if row.get("scoringPeriodId") != week:
            continue
        if row.get("status") != "EXECUTED":
            continue  # Failed/pending offers must not count as acquisitions or FAAB spending.
        kind = {"FREEAGENT": "FREE_AGENT", "WAIVER": "WAIVER", "TRADE_ACCEPT": "TRADE", "TRADE": "TRADE"}.get(row.get("type"))
        if not kind:
            continue
        timestamp = row.get("processDate") or row.get("acceptedDate")
        date = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp else ""
        items = row.get("items") or []
        if not items:
            warnings.append("Executed transaction has no visible player items; transaction detail is incomplete.")
            continue
        # One row per player leg, shared transaction_id preserves aggregate transaction counts.
        for index, item in enumerate(items):
            action = item.get("type")
            player = item.get("playerId")
            team = item.get("toTeamId") if action in ("ADD", "TRADE") else item.get("fromTeamId")
            if not isinstance(team, int) or team <= 0:
                team = row.get("teamId")
            if not isinstance(team, int) or not isinstance(player, int):
                warnings.append("Transaction player/team identifier missing.")
                continue
            result.append({"id": f"{row['id']}:{index}", "transaction_id": str(row["id"]),
                           "date": date, "week": week, "team_id": team,
                           "type": "DROP" if action == "DROP" else kind,
                           "player_added": player if action in ("ADD", "TRADE") else None,
                           "player_dropped": player if action == "DROP" else None,
                           "player_name": None,
                           "faab_bid": number(row.get("bidAmount")) if action == "ADD" and kind == "WAIVER" else None})
    return result, warnings


def normalize(data, box, transaction_data, league_id, season, week):
    mapping = periods(data)
    period_ids = [pid for pid, weeks in mapping.items() if week in weeks]
    if len(period_ids) != 1 or mapping[period_ids[0]] != [week]:
        raise ValueError("Multi-scoring-period matchups are not yet supported")
    completed = latest_completed(data)
    if completed is None or week > completed or week < 1:
        raise ValueError("Requested ESPN scoring period is not completed")
    schedule = data.get("schedule", [])
    games = [g for g in box.get("schedule", []) if g.get("matchupPeriodId") == period_ids[0]]
    if not games:
        raise ValueError("No matchups returned for requested week")
    team_rows = data.get("teams", [])
    if not team_rows or len({t["id"] for t in team_rows}) != len(team_rows):
        raise ValueError("Missing or duplicate teams")
    records = {t["id"]: dict(wins=0, losses=0, ties=0, points_for=0., points_against=0.) for t in team_rows}
    for pid, weeks in mapping.items():
        if max(weeks) > week:
            continue
        if len(weeks) != 1:
            raise ValueError("Historical multi-scoring-period matchups are unsupported")
        prior = [g for g in schedule if g.get("matchupPeriodId") == pid]
        if not prior:
            raise ValueError("Historical schedule is incomplete")
        for game in prior:
            home, away = game.get("home"), game.get("away")
            if not home:
                raise ValueError("Matchup has no home team")
            if away and game.get("winner") not in ("HOME", "AWAY", "TIE"):
                raise ValueError("Historical matchup has not finalized")
            # Standings use regular-season results; playoff games do not add regular-season wins.
            if game.get("playoffTierType", "NONE") != "NONE":
                continue
            hs, aws = side_score(home, weeks[0]), side_score(away, weeks[0]) if away else None
            for side, points, against in ((home, hs, aws), (away, aws, hs)):
                if side is None:
                    continue
                rec = records[side["teamId"]]
                rec["points_for"] += points
                if against is not None:
                    rec["points_against"] += against
                    rec["wins" if points > against else "losses" if points < against else "ties"] += 1
    members = {m["id"]: m.get("displayName") or " ".join([m.get("firstName", ""), m.get("lastName", "")]).strip() for m in data.get("members", [])}
    teams, warnings = [], []
    for team in team_rows:
        rec = records[team["id"]]
        current = team.get("record", {}).get("overall", {})
        agrees = all(current.get(key) == rec[key] for key in ("wins", "losses", "ties"))
        rank = team.get("playoffSeed") if week == completed and agrees else None
        teams.append({"id": team["id"], "name": team.get("name") or (team.get("location", "") + " " + team.get("nickname", "")).strip() or str(team["id"]),
                      "managers": [members[o] for o in team.get("owners", []) if members.get(o)],
                      "rank": rank if isinstance(rank, int) and rank > 0 else None,
                      **rec, "faab_remaining": None})
    if any(t["rank"] is None for t in teams):
        warnings.append("Official historical standings ranks unavailable; current ranks are not used for backfills.")
    warnings.append("Historical FAAB balances and failed/contested waiver offers are unavailable.")
    matchups, rosters, seen = [], [], set()
    for game in games:
        home, away = game.get("home"), game.get("away")
        if not home or (away and game.get("winner") not in ("HOME", "AWAY", "TIE")):
            raise ValueError("Requested matchup is not finalized")
        match = {"id": str(game["id"]), "home_team_id": home["teamId"],
                 "away_team_id": away["teamId"] if away else None,
                 "home_score": side_score(home, week), "away_score": side_score(away, week) if away else None,
                 "home_projected": None, "away_projected": None}
        for label, side in (("home", home), ("away", away)):
            if side is None:
                continue
            if side["teamId"] not in records or side["teamId"] in seen:
                raise ValueError("Unknown or duplicate matchup team")
            seen.add(side["teamId"])
            roster = parse_roster(side, week, season)
            if roster is not None:
                rosters.append(roster)
                starters = [p for p in roster["players"] if p["starter"]]
                if starters and all(p["projected"] is not None for p in starters):
                    match[label + "_projected"] = sum(p["projected"] for p in starters)
        matchups.append(match)
    if seen != set(records):
        raise ValueError("Requested scoreboard is missing teams")
    transactions, txn_warnings = parse_transactions(transaction_data.get("transactions", []), week)
    warnings.extend(txn_warnings)
    txn_available = transaction_data.get("available", False) and not txn_warnings
    if not txn_available:
        warnings.append("Transactions unavailable or incomplete; transaction totals must not be interpreted as complete.")
    settings = data["settings"]
    return {"schema_version": 1, "league_id": league_id, "league_name": settings.get("name", str(league_id)),
            "season": season, "week": week, "completed": True,
            "settings": {"lineup_slots": {str(k): v for k, v in settings.get("rosterSettings", {}).get("lineupSlotCounts", {}).items() if int(k) not in (20, 21) and v > 0},
                         "playoff_team_count": settings.get("scheduleSettings", {}).get("playoffTeamCount"),
                         "faab_budget": number(settings.get("acquisitionSettings", {}).get("acquisitionBudget"))},
            "teams": teams, "matchups": matchups, "rosters": rosters, "transactions": transactions,
            "availability": {"transactions": txn_available, "projections": all(m["home_projected"] is not None and (m["away_team_id"] is None or m["away_projected"] is not None) for m in matchups),
                             "rosters": len(rosters) == len(teams)}, "warnings": warnings}
