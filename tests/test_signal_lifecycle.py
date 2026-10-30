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
            "entry": 4180.0,
            "sl": 4208.0,
            "tp1": 4124.0,
        }
        self.bar = {
            "bar_time": "2026-10-02T11:45:00Z",
            "high": 4175.0,
            "low": 4170.0,
            "close": 4172.0,
        }

    def test_planned_rr_matches_two_to_one_strategy(self):
        self.assertAlmostEqual(planned_reward_risk(self.setup), 2.0, places=1)

    def test_remaining_rr_is_based_on_current_price(self):
        self.assertGreater(remaining_reward_risk(self.setup, 4172.0), 1.0)

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
            {**self.bar, "high": 4210.0, "close": 4209.0},
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
            {**self.bar, "high": 4165.0, "low": 4155.0, "close": 4160.0},
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

    def test_limit_setup_waits_until_entry_is_touched(self):
        result = evaluate_setup(self.setup, self.bar, now=self.now)
        self.assertEqual(result["state"], "READY")
        self.assertIsNone(result["entry_touched_at"])

    def test_entry_touch_is_reported_without_claiming_a_fill(self):
        touched_bar = {
            **self.bar,
            "high": 4182.0,
            "low": 4178.0,
            "close": 4180.0,
        }
        result = evaluate_setup(self.setup, touched_bar, now=self.now)
        self.assertEqual(result["state"], "ENTRY TOUCHED")
        self.assertIn("does not confirm a broker fill", result["reason"])
        self.assertEqual(result["entry_touched_at"], "2026-10-02T11:45:00+00:00")

    def test_entry_touch_persists_after_price_moves_away(self):
        touched_setup = {**self.setup, "entry_touched_at": "2026-10-02T11:45:00+00:00"}
        result = evaluate_setup(touched_setup, self.bar, now=self.now)
        self.assertEqual(result["state"], "ENTRY TOUCHED")
        self.assertEqual(result["entry_touched_at"], touched_setup["entry_touched_at"])

    def test_missing_market_timestamp_is_unknown_not_ready(self):
        bar = {key: value for key, value in self.bar.items() if key != "bar_time"}
        result = evaluate_setup(self.setup, bar, now=self.now)
        self.assertEqual(result["state"], "PRICE UNKNOWN")
        self.assertIn("no valid timestamp", result["reason"])


if __name__ == "__main__":
    unittest.main()
