import json
import unittest
from unittest.mock import patch

from src.llm.client import NarrativeError, generate_narrative
from src.reports.weekly_report import audit_narrative, generate_report, resolve_pointer


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {"season": 2026, "week": 4,
                         "weekly_scoring": {"average": 110.25},
                         "top_matchups": [{"winner": '<script>alert("7")</script>', "margin": 2.5}]}
        self.narrative = {"sections": [
            {"title": "Week at a Glance", "paragraphs": ["League average: {{/weekly_scoring/average}}."]},
            {"title": "Matchup of the Week", "paragraphs": [
                "{{/top_matchups/0/winner}} won by {{/top_matchups/0/margin}} points."]}]}

    def test_live_report_audits_and_escapes_references(self):
        with patch("src.reports.weekly_report.generate_narrative", return_value=self.narrative):
            report = generate_report(self.analysis, api_key="fake", model="configured-model")
        self.assertNotIn("<script>", report["html"])
        self.assertIn("&lt;script&gt;", report["html"])
        self.assertTrue(report["audit"]["email_eligible"])
        self.assertEqual(report["audit"]["references"][-1]["value"], 2.5)
        self.assertEqual(report["audit"]["references"][-1]["pointer"], "/top_matchups/0/margin")
        self.assertEqual(len(report["audit"]["analysis_sha256"]), 64)

    def test_rejects_invented_numeric_literals_and_words(self):
        for text in ["Scored 44 points.", "Won by four.", "Finished first.", "Improved ½.", "Won twice."]:
            with self.subTest(text=text):
                self.narrative["sections"][0]["paragraphs"] = [text]
                with self.assertRaises(NarrativeError):
                    audit_narrative(self.narrative, self.analysis)

    def test_rejects_missing_null_container_and_negative_index(self):
        self.analysis["missing"] = None
        for pointer in ["/missing", "/unknown", "/top_matchups", "/top_matchups/-1/margin", "/bad~2key"]:
            with self.subTest(pointer=pointer), self.assertRaises(NarrativeError):
                resolve_pointer(self.analysis, pointer)
        self.assertEqual(resolve_pointer({"a/b": {"~c": 2}}, "/a~1b/~0c"), 2)

    def test_does_not_allow_missing_featured_matchup(self):
        self.narrative["sections"].pop()
        with self.assertRaises(NarrativeError):
            audit_narrative(self.narrative, self.analysis)

    def test_preview_is_offline_and_not_email_eligible(self):
        with patch("src.reports.weekly_report.generate_narrative", side_effect=AssertionError("network")):
            report = generate_report(self.analysis, no_llm=True)
        self.assertFalse(report["audit"]["email_eligible"])
        self.assertIn("110.25", report["html"])
        self.assertIn("Python-only preview", report["markdown"])

    def test_ollama_audit_failure_uses_grounded_fallback(self):
        bad = {"sections": [{"title": "Week at a Glance", "paragraphs": ["Scored 44."]},
                            {"title": "Matchup of the Week", "paragraphs": [
                                "{{/top_matchups/0/winner}} won by {{/top_matchups/0/margin}}."]}]}
        self.analysis["league_summary"] = {"league_name": "Demo League"}
        self.analysis["weekly_scoring"].update({"weekly_average_score": 110.25,
                                                "weekly_median_score": 108,
                                                "highest_score": 130,
                                                "lowest_score": 80,
                                                "highest_combined_score": 240,
                                                "lowest_combined_score": 160})
        self.analysis["top_matchups"][0].update({"loser": "Other", "margin_of_victory": 2.5,
                                                  "combined_score": 220, "interest_score": 8,
                                                  "winner_weekly_score_rank": 1,
                                                  "loser_weekly_score_rank": 2})
        with patch("src.reports.weekly_report.generate_narrative", return_value=bad):
            report = generate_report(self.analysis, provider="ollama", model="qwen2.5:7b")
        self.assertEqual(report["audit"]["mode"], "ollama_python_fallback")
        self.assertTrue(report["audit"]["email_eligible"])
        self.assertIn("fallback_reason", report["audit"])

    def test_requires_explicit_live_model(self):
        with self.assertRaises(NarrativeError):
            generate_narrative(self.analysis, api_key="fake", model="")
        with self.assertRaises(NarrativeError):
            generate_narrative(self.analysis, provider="ollama", model="")

    def test_provider_refusal_and_incomplete_fail_closed(self):
        for response in [{"status": "incomplete"}, {"status": "completed", "output": [
                {"content": [{"type": "refusal", "refusal": "No"}]}]}]:
            with patch("src.llm.client.urlopen") as opener:
                opener.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
                with self.assertRaises(NarrativeError):
                    generate_narrative(self.analysis, api_key="fake", model="configured-model")

    def test_responses_request_uses_strict_schema(self):
        response = {"status": "completed", "output": [{"content": [
            {"type": "output_text", "text": json.dumps(self.narrative)}]}]}
        with patch("src.llm.client.urlopen") as opener:
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            self.assertEqual(generate_narrative(self.analysis, api_key="fake", model="configured-model"), self.narrative)
        payload = json.loads(opener.call_args.args[0].data)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertFalse(payload["store"])

    def test_ollama_request_uses_local_chat_schema(self):
        response = {"message": {"content": json.dumps(self.narrative)}}
        with patch("src.llm.client.urlopen") as opener:
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            self.assertEqual(generate_narrative(self.analysis, provider="ollama", model="qwen2.5:7b"), self.narrative)
        request = opener.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen2.5:7b")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
