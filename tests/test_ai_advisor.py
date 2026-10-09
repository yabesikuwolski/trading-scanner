import json
import unittest
from unittest.mock import patch

import config
from scanner.ai_advisor import build_ai_prompt, log_ai_review, parse_ai_response, review_setup


class AiAdvisorTests(unittest.TestCase):
    def test_build_prompt_contains_important_trade_rules(self):
        prompt = build_ai_prompt({
            "symbol": "XAUUSD",
            "signal_type": "SELL LIMIT",
            "direction": "SELL",
            "entry": 4350.0,
            "sl": 4358.0,
            "tp1": 4342.0,
        })

        self.assertIn("Return valid JSON only", prompt)
        self.assertIn("advisory only", prompt)
        self.assertIn("XAUUSD", prompt)

    def test_parse_ai_response_handles_json_string(self):
        result = parse_ai_response('{"quality_score": 82, "decision": "TRADE", "confidence": "HIGH"}')

        self.assertEqual(result["quality_score"], 82)
        self.assertEqual(result["decision"], "TRADE")

    def test_review_setup_uses_fallback_when_ai_unavailable(self):
        with patch.object(config, "AI_ADVISOR_ENABLED", True), \
             patch.object(config, "OLLAMA_BASE_URL", "http://localhost:11434"), \
             patch.object(config, "OLLAMA_MODEL", "qwen2.5:7b-instruct"), \
             patch("scanner.ai_advisor.request.urlopen", side_effect=Exception("offline")):
            review = review_setup("XAUUSD", {"signal": {"type": "SELL LIMIT", "direction": "SELL", "entry": 4350.0, "sl": 4358.0, "tp1": 4342.0, "rr": 1.5}, "conditions": ["Bearish sweep"], "bias": "bearish", "setup_id": "id-1"}, {"grade": "A", "score": 7})

        self.assertEqual(review["decision"], "NO_TRADE")
        self.assertIn("AI review unavailable", review["summary"])

    def test_logger_records_ai_review(self):
        record = log_ai_review("XAUUSD", {"decision": "TRADE", "quality_score": 80, "confidence": "HIGH", "summary": "Strong setup", "reasons": ["Good structure"], "invalidations": [], "risk_note": "Acceptable"})

        self.assertEqual(record["symbol"], "XAUUSD")
        self.assertEqual(record["decision"], "TRADE")
        self.assertEqual(record["quality_score"], 80)


if __name__ == "__main__":
    unittest.main()
