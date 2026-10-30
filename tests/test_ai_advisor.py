import json
import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

import config
from database.db_manager import get_connection, init_db, save_setup
from scanner.ai_advisor import (
    AIReviewValidationError,
    build_ai_prompt,
    build_review_context,
    build_setup_summary,
    log_ai_review,
    parse_ai_response,
    review_setup,
)


VALID_REVIEW = {
    "quality_score": 82,
    "decision": "TRADE",
    "confidence": "HIGH",
    "summary": "Strong structural alignment.",
    "reasons": ["H4 and H1 evidence align."],
    "invalidations": ["A close through the stop level invalidates the setup."],
    "risk_note": "Simulation sizing is feasible.",
}


class AiAdvisorTests(unittest.TestCase):
    def test_build_prompt_states_advisory_and_deterministic_constraints(self):
        prompt = build_ai_prompt({"symbol": "XAUUSD", "entry": 4350.0})

        self.assertIn("Return valid JSON only", prompt)
        self.assertIn("advisory only", prompt)
        self.assertIn("do not override or recalculate", prompt)
        self.assertIn("XAUUSD", prompt)

    def test_parse_ai_response_accepts_complete_schema(self):
        result = parse_ai_response(json.dumps(VALID_REVIEW))
        self.assertEqual(result, VALID_REVIEW)

    def test_parse_ai_response_rejects_invalid_json_and_incomplete_schema(self):
        for body in ("not json", '{"decision":"NO_TRADE"}'):
            with self.subTest(body=body), self.assertRaises(AIReviewValidationError):
                parse_ai_response(body)

    def test_parse_ai_response_rejects_wrong_decision_and_score_range(self):
        for updates in ({"decision": "MAYBE"}, {"quality_score": 101}, {"quality_score": True}):
            invalid = {**VALID_REVIEW, **updates}
            with self.subTest(updates=updates), self.assertRaises(AIReviewValidationError):
                parse_ai_response(json.dumps(invalid))

    def test_parse_ai_response_rejects_bad_confidence_and_reason_types(self):
        for updates in ({"confidence": "VERY_HIGH"}, {"reasons": "one reason"}):
            invalid = {**VALID_REVIEW, **updates}
            with self.subTest(updates=updates), self.assertRaises(AIReviewValidationError):
                parse_ai_response(json.dumps(invalid))

    def test_parse_ai_response_rejects_fields_outside_the_schema(self):
        invalid = {**VALID_REVIEW, "position_size": 0.01}
        with self.assertRaisesRegex(AIReviewValidationError, "unexpected fields"):
            parse_ai_response(json.dumps(invalid))

    def test_disabled_review_does_not_call_ollama_or_fabricate_decision(self):
        with patch.object(config, "AI_ADVISOR_ENABLED", False), \
             patch("scanner.ai_advisor.request.urlopen") as urlopen:
            review = review_setup("XAUUSD", {}, {})
        self.assertEqual(review, {"status": "disabled", "decision": None})
        urlopen.assert_not_called()

    def test_unavailable_review_has_no_verdict(self):
        with patch.object(config, "AI_ADVISOR_ENABLED", True), \
             patch("scanner.ai_advisor.request.urlopen", side_effect=TimeoutError("offline")), \
             patch("scanner.ai_advisor.log_ai_review"):
            review = review_setup("XAUUSD", {}, {})
        self.assertEqual(review["status"], "unavailable")
        self.assertIsNone(review["decision"])

    def test_invalid_model_output_has_no_verdict(self):
        response = BytesIO(json.dumps({"response": '{"decision":"NO_TRADE"}'}).encode())
        with patch.object(config, "AI_ADVISOR_ENABLED", True), \
             patch("scanner.ai_advisor.request.urlopen", return_value=response), \
             patch("scanner.ai_advisor.log_ai_review"):
            review = review_setup("XAUUSD", {}, {})
        self.assertEqual(review["status"], "invalid_response")
        self.assertIsNone(review["decision"])

    def test_valid_review_includes_market_and_account_context_in_model_input(self):
        response = BytesIO(json.dumps({"response": json.dumps(VALID_REVIEW)}).encode())
        context = {
            "market_data": {"source": "BIQUOTE", "timeframes": {"M15": {"freshness": "fresh"}}},
            "simulation_account": {"account_feasibility": "INFEASIBLE", "risk_budget": 0.2},
        }
        with patch.object(config, "AI_ADVISOR_ENABLED", True), \
             patch("scanner.ai_advisor.request.urlopen", return_value=response) as urlopen, \
             patch("scanner.ai_advisor.log_ai_review"):
            review = review_setup("XAUUSD", {"signal": {"entry": 10}}, {"grade": "A"}, context)
        self.assertEqual(review["status"], "available")
        request_data = json.loads(urlopen.call_args.args[0].data.decode())
        self.assertIn("INFEASIBLE", request_data["prompt"])
        self.assertIn("fresh", request_data["prompt"])

    def test_summary_contains_strategy_evidence_and_review_context(self):
        summary = build_setup_summary(
            "XAUUSD",
            {"bos": {"type": "bullish_bos"}, "fvgs": [{"filled": False, "top": 2}], "signal": {}},
            {},
            {"market_data": {"source": "BIQUOTE"}},
        )
        self.assertEqual(summary["technical_evidence"]["bos"]["type"], "bullish_bos")
        self.assertEqual(summary["technical_evidence"]["active_fvgs"], [{"filled": False, "top": 2}])
        self.assertIn("market_data", summary["review_context"])

    def test_review_context_marks_feasibility_and_unknown_market_data(self):
        with patch.object(config, "SIMULATION_ACCOUNT_CURRENCY", "USD"):
            context = build_review_context(
                {}, {"risk_amount": 0.2, "risk_pct": 2, "sizing_status": "MISSING_CONTRACT_SPECS"},
                10, news_filter_enabled=False,
            )
        self.assertEqual(context["simulation_account"]["account_feasibility"], "UNKNOWN")
        self.assertEqual(context["simulation_account"]["currency"], "USD")
        self.assertEqual(context["news"]["status"], "disabled")
        self.assertEqual(context["market_data"]["timeframes"], {})

    def test_logger_writes_to_requested_audit_file(self):
        with tempfile.TemporaryDirectory() as directory:
            audit_path = os.path.join(directory, "reviews.jsonl")
            record = log_ai_review(
                "XAUUSD", {**VALID_REVIEW, "status": "available"},
                summary="Strong setup", audit_path=audit_path,
            )
            with open(audit_path, encoding="utf-8") as handle:
                saved = json.loads(handle.readline())
        self.assertEqual(record["symbol"], "XAUUSD")
        self.assertEqual(saved["status"], "available")
        self.assertEqual(saved["decision"], "TRADE")

    def test_save_setup_persists_ai_state_without_fake_review_timestamp(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "DB_PATH", os.path.join(directory, "scanner.sqlite3")):
            init_db()
            setup_id = save_setup(
                "XAUUSD", "M15", {"signal": {}, "levels": {}}, {},
                ai_review={"status": "unavailable", "decision": None},
            )
            conn = get_connection()
            row = conn.execute("SELECT ai_status, ai_decision, ai_reviewed_at FROM setups WHERE id=?", (setup_id,)).fetchone()
            conn.close()
        self.assertEqual(row["ai_status"], "unavailable")
        self.assertIsNone(row["ai_decision"])
        self.assertIsNotNone(row["ai_reviewed_at"])


if __name__ == "__main__":
    unittest.main()
