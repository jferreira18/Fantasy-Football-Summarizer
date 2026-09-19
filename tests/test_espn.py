import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.espn import ESPNClient, ESPNFetchError
from src.espn.authentication import cookie_header
from src.espn.parsers import latest_completed, normalize, parse_transactions


class ESPNTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((Path(__file__).parent / "fixtures" / "espn_week1.json").read_text())

    def normalize(self):
        return normalize(self.raw["league"], self.raw["boxscores"], self.raw["transactions"], 123, 2026, 1)

    def test_historical_record_does_not_leak_current_standings(self):
        team = self.normalize()["teams"][0]
        self.assertEqual(team["wins"], 1)
        self.assertEqual(team["points_for"], 100)
        self.assertIsNone(team["rank"])
        self.assertIsNone(team["faab_remaining"])

    def test_nullable_roster_data_and_projection(self):
        snapshot = self.normalize()
        self.assertFalse(snapshot["availability"]["rosters"])
        self.assertIsNone(snapshot["rosters"][0]["players"][1]["score"])
        self.assertEqual(snapshot["matchups"][0]["home_projected"], 20)
        self.assertEqual(snapshot["settings"]["lineup_slots"], {"0": 1})

    def test_only_executed_waivers_and_once_only_bid(self):
        rows = self.normalize()["transactions"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r["faab_bid"] or 0 for r in rows), 8)
        self.assertEqual(rows[0]["transaction_id"], rows[1]["transaction_id"])

    def test_period_rollover_and_finalization_required(self):
        league = self.raw["league"]
        self.assertEqual(latest_completed(league), 2)
        league["schedule"][1]["winner"] = "UNDECIDED"
        self.assertEqual(latest_completed(league), 1)
        league["scoringPeriodId"] = 1
        self.assertIsNone(latest_completed(league))

    def test_postponed_and_multiperiod_fail_closed(self):
        self.raw["boxscores"]["schedule"][0]["winner"] = "UNDECIDED"
        with self.assertRaises(ValueError):
            self.normalize()
        self.raw["league"]["settings"]["scheduleSettings"]["matchupPeriods"]["1"] = [1, 2]
        with self.assertRaises(ValueError):
            self.normalize()

    def test_missing_required_score_fails(self):
        del self.raw["boxscores"]["schedule"][0]["home"]["totalPoints"]
        with self.assertRaises(ValueError):
            self.normalize()

    def test_hidden_trade_items_are_not_empty_activity(self):
        self.raw["transactions"]["transactions"].append({"id": "hidden", "scoringPeriodId": 1,
            "status": "EXECUTED", "type": "TRADE_ACCEPT", "items": []})
        self.assertFalse(self.normalize()["availability"]["transactions"])

    def test_cookie_validation(self):
        self.assertEqual(cookie_header("", ""), "")
        self.assertEqual(cookie_header("secret", "{swid}"), "espn_s2=secret; SWID={swid}")
        with self.assertRaises(ValueError):
            cookie_header("secret", "")
        with self.assertRaises(ValueError):
            cookie_header("secret\r\n", "swid")

    def test_pagination_duplicates_mark_unavailable(self):
        client = ESPNClient(123, 2026)
        page = {"transactions": [{"id": str(i)} for i in range(100)]}
        with patch.object(client, "_request", return_value=page) as request:
            result = client.get_transactions(1)
        self.assertFalse(result["available"])
        self.assertEqual(request.call_count, 2)

    def test_transaction_filter_rejection_falls_back_unavailable(self):
        client = ESPNClient(123, 2026)
        rows = [{"id": "1", "scoringPeriodId": 1}]
        with patch.object(client, "_request", side_effect=[ESPNFetchError("ESPN_FETCH_FAILED: HTTP 400"), {"transactions": rows}]) as request:
            result = client.get_transactions(1)
        self.assertEqual(result["transactions"], rows)
        self.assertFalse(result["available"])
        self.assertEqual(request.call_count, 2)

    def test_network_retries_and_sanitized_failure(self):
        client = ESPNClient(123, 2026, "secret", "swid")
        with patch("src.espn.client.urlopen", side_effect=URLError("secret")) as request, patch("src.espn.client.time.sleep"):
            with self.assertRaises(ESPNFetchError) as caught:
                client.get_league()
        self.assertEqual(request.call_count, 3)
        self.assertNotIn("secret", str(caught.exception))

    def test_auth_does_not_retry(self):
        client = ESPNClient(123, 2026)
        error = HTTPError("url", 403, "denied", {}, None)
        with patch("src.espn.client.urlopen", side_effect=error) as request:
            with self.assertRaises(ESPNFetchError):
                client.get_league()
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
