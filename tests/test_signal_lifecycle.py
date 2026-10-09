import unittest
from datetime import datetime, timezone

from dashboard.signal_lifecycle import (
    evaluate_setup,
    planned_reward_risk,
    remaining_reward_risk,
)


class SignalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        self.setup = {
            "id": 1,
            "symbol": "XAUUSD",
            "signal_type": "SELL LIMIT",
            "detected_at": "2026-10-02T11:30:00Z",
            "bias": "bearish",
            "grade": "A",
            "score": 8,
            "entry": 4160.551,
            "sl": 4188.80764,
            "tp1": 4104.03771,
        }
        self.bar = {"high": 4168.0, "low": 4158.0, "close": 4162.0}

    def test_planned_rr_matches_two_to_one_strategy(self):
        self.assertAlmostEqual(planned_reward_risk(self.setup), 2.0, places=1)

    def test_remaining_rr_is_based_on_current_price(self):
        self.assertGreater(remaining_reward_risk(self.setup, 4162.0), 1.0)

    def test_ready_setup_under_age_limit(self):
        result = evaluate_setup(self.setup, self.bar, now=self.now)
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["age_minutes"], 30)

    def test_stale_at_configured_age_limit(self):
        self.setup["detected_at"] = "2026-10-02T11:00:00Z"
        result = evaluate_setup(self.setup, self.bar, now=self.now, max_age_minutes=60)
        self.assertEqual(result["state"], "STALE")

    def test_stop_breach_invalidates_setup(self):
        result = evaluate_setup(
            self.setup,
            {"high": 4190.0, "low": 4158.0, "close": 4189.0},
            now=self.now,
        )
        self.assertEqual(result["state"], "INVALIDATED")
        self.assertIn("stop-loss", result["reason"])

    def test_news_block_applies_to_existing_candidate(self):
        result = evaluate_setup(
            self.setup,
            self.bar,
            now=self.now,
            news_blocked=True,
            news_reason="USD high-impact event in 10m",
        )
        self.assertEqual(result["state"], "NEWS BLOCKED")
        self.assertEqual(result["reason"], "USD high-impact event in 10m")

    def test_remaining_rr_below_one_invalidates_setup(self):
        result = evaluate_setup(
            self.setup,
            {"high": 4145.0, "low": 4139.0, "close": 4140.0},
            now=self.now,
        )
        self.assertEqual(result["state"], "INVALIDATED")
        self.assertIn("below 1:1", result["reason"])

    def test_below_minimum_score_invalidates_setup(self):
        self.setup["score"] = 3
        result = evaluate_setup(self.setup, self.bar, now=self.now)
        self.assertEqual(result["state"], "INVALIDATED")
        self.assertIn("minimum grade", result["reason"])

    def test_persisted_user_states_take_precedence(self):
        reviewed = evaluate_setup(self.setup, self.bar, now=self.now, reviewed=True)
        logged = evaluate_setup(self.setup, self.bar, now=self.now, trade_logged=True)
        self.assertEqual(reviewed["state"], "REVIEWED")
        self.assertEqual(logged["state"], "TRADE LOGGED")

    def test_missing_live_price_is_not_actionable(self):
        result = evaluate_setup(self.setup, None, now=self.now)
        self.assertEqual(result["state"], "PRICE UNKNOWN")

    def test_stale_market_bar_cannot_certify_ready_state(self):
        old_bar = {**self.bar, "bar_time": "2026-10-02T10:00:00Z"}
        result = evaluate_setup(self.setup, old_bar, now=self.now, max_market_age_minutes=30)
        self.assertEqual(result["state"], "PRICE UNKNOWN")
        self.assertIn("live-price limit", result["reason"])


if __name__ == "__main__":
    unittest.main()