"""Small read-only ESPN adapter with bounded retries and sanitized errors."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .authentication import cookie_header
from .parsers import latest_completed, normalize, periods


class ESPNFetchError(RuntimeError):
    """Required ESPN data cannot safely produce a report."""


class ESPNClient:
    def __init__(self, league_id, season, espn_s2="", swid=""):
        self.league_id, self.season = int(league_id), int(season)
        if self.league_id <= 0 or self.season < 2019:
            raise ValueError("A positive league ID and season >= 2019 are required")
        self._cookie = cookie_header(espn_s2, swid)
        self._base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{self.season}/segments/0/leagues/{self.league_id}"
        self._league = None

    def _request(self, views, week=None, filters=None):
        params = [("view", v) for v in views]
        if week is not None:
            params.append(("scoringPeriodId", str(week)))
        headers = {"Accept": "application/json", "User-Agent": "FantasyLeagueIntelligence/1.0"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        if filters:
            headers["X-Fantasy-Filter"] = json.dumps(filters)
        for attempt in range(3):
            try:
                with urlopen(Request(self._base + "?" + urlencode(params), headers=headers), timeout=30) as response:
                    # Bound payload size to avoid unbounded allocation on malformed responses.
                    payload = response.read(25_000_001)
                    if len(payload) > 25_000_000:
                        raise ESPNFetchError("ESPN_FETCH_FAILED: response too large")
                    data = json.loads(payload)
                    if not isinstance(data, dict):
                        raise ESPNFetchError("ESPN_FETCH_FAILED: unexpected response shape")
                    return data
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise ESPNFetchError("ESPN_FETCH_FAILED: access denied; check league ID and ESPN cookies") from None
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise ESPNFetchError(f"ESPN_FETCH_FAILED: HTTP {exc.code}") from None
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise ESPNFetchError("ESPN_FETCH_FAILED: network request failed") from None
            except (ValueError, UnicodeError):
                raise ESPNFetchError("ESPN_FETCH_FAILED: invalid JSON response") from None
            time.sleep(2 ** attempt)
        raise ESPNFetchError("ESPN_FETCH_FAILED: retries exhausted")

    def get_league(self):
        if self._league is None:
            self._league = self._request(["mSettings", "mTeam", "mStandings", "mMatchup", "mMatchupScore"])
        return self._league

    def get_status(self):
        data = self.get_league()
        return {**data.get("status", {}), "scoringPeriodId": data.get("scoringPeriodId")}

    def get_settings(self):
        return self.get_league().get("settings", {})

    def latest_completed_week(self):
        try:
            return latest_completed(self.get_league())
        except (ValueError, KeyError, TypeError) as exc:
            raise ESPNFetchError(f"ESPN_FETCH_FAILED: {exc}") from None

    def get_boxscores(self, week):
        try:
            mapping = periods(self.get_league())
            ids = [pid for pid, weeks in mapping.items() if week in weeks]
            if len(ids) != 1 or mapping[ids[0]] != [week]:
                raise ValueError("Multi-scoring-period matchups are not yet supported")
            return self._request(["mMatchupScore", "mScoreboard"], week,
                                 {"schedule": {"filterMatchupPeriodIds": {"value": ids}}})
        except (ValueError, KeyError, TypeError) as exc:
            raise ESPNFetchError(f"ESPN_FETCH_FAILED: {exc}") from None

    def get_transactions(self, week):
        """Fetch paginated executed activity; an incomplete result is explicitly unavailable.

        Offset support is undocumented. Repeated pages, missing rows, and overflows
        therefore invalidate availability instead of silently truncating totals.
        """
        collected, seen = [], set()
        for page in range(100):
            filters = {"transactions": {"filterType": {"value": ["WAIVER", "FREEAGENT", "TRADE_ACCEPT", "TRADE"]},
                                        "filterScoringPeriodId": {"value": week}, "limit": 100, "offset": page * 100}}
            try:
                data = self._request(["mTransactions2"], week, filters)
            except ESPNFetchError as exc:
                if page != 0 or "HTTP 400" not in str(exc):
                    raise
                # Some leagues reject transaction filters while accepting the
                # view itself. Use the unfiltered payload for visible context,
                # but mark completeness unavailable because pagination and
                # server-side week/type filtering could not be verified.
                data = self._request(["mTransactions2"], week)
                rows = data.get("transactions")
                return {"transactions": rows if isinstance(rows, list) else collected,
                        "available": False}
            rows = data.get("transactions")
            if not isinstance(rows, list):
                return {"transactions": collected, "available": False}
            if not rows:
                return {"transactions": collected, "available": True}
            for row in rows:
                identity = row.get("id")
                if identity is None or identity in seen:
                    return {"transactions": collected, "available": False}
                seen.add(identity)
                collected.append(row)
            if len(rows) < 100:
                return {"transactions": collected, "available": True}
        return {"transactions": collected, "available": False}

    def fetch_week(self, week):
        try:
            week = int(week)
            latest = self.latest_completed_week()
            if latest is None or week < 1 or week > latest:
                raise ESPNFetchError("ESPN_FETCH_FAILED: requested week has not completed")
            league = self.get_league()
            box = self.get_boxscores(week)
            transactions = self.get_transactions(week)
            raw = {"league": league, "boxscores": box, "transactions": transactions}
            snapshot = normalize(league, box, transactions, self.league_id, self.season, week)
            return raw, snapshot
        except ESPNFetchError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            raise ESPNFetchError(f"ESPN_FETCH_FAILED: normalization rejected data ({type(exc).__name__})") from None

    def get_teams(self):
        week = self.latest_completed_week()
        if week is None:
            raise ESPNFetchError("ESPN_FETCH_FAILED: no completed week")
        return self.fetch_week(week)[1]["teams"]

    def get_standings(self):
        return self.get_teams()

    def get_rosters(self, week):
        return self.fetch_week(week)[1]["rosters"]

    def get_matchups(self, week):
        return self.fetch_week(week)[1]["matchups"]
