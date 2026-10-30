import unittest
from datetime import datetime, timezone

import pandas as pd

from scanner.market_data_quality import evaluate_market_data_freshness, market_data_is_fresh


class MarketDataQualityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)

    def _frame(self, timestamp):
        return pd.DataFrame(
            {"Open": [1.0], "High": [1.1], "Low": [0.9], "Close": [1.0]},
            index=pd.DatetimeIndex([timestamp]),
        )

    def test_freshness_respects_each_timeframe_bar_duration(self):
        frames = {
            "H4": self._frame(pd.Timestamp("2026-10-09T08:00:00Z")),
            "H1": self._frame(pd.Timestamp("2026-10-09T11:30:00Z")),
            "M15": self._frame(pd.Timestamp("2026-10-09T12:45:00Z")),
        }
        freshness = evaluate_market_data_freshness(frames, now=self.now, max_extra_age_minutes=30)
        self.assertTrue(market_data_is_fresh(freshness))
        self.assertEqual({item["status"] for item in freshness.values()}, {"fresh"})
        self.assertEqual(freshness["H4"]["age_minutes"], 60.0)

    def test_stale_missing_naive_and_future_timestamps_are_not_fresh(self):
        frames = {
            "H4": self._frame(pd.Timestamp("2026-10-09T08:00:00Z")),
            "H1": self._frame(pd.Timestamp("2026-10-09T11:30:00Z")),
            "M15": self._frame(pd.Timestamp("2026-10-09T10:00:00Z")),
        }
        stale = evaluate_market_data_freshness(frames, now=self.now)
        self.assertEqual(stale["M15"]["status"], "stale")
        self.assertFalse(market_data_is_fresh(stale))

        missing = evaluate_market_data_freshness({}, now=self.now)
        self.assertEqual(missing["M15"]["status"], "missing")
        naive = evaluate_market_data_freshness(
            {**frames, "M15": self._frame(pd.Timestamp("2026-10-09T12:50:00"))},
            now=self.now,
        )
        self.assertEqual(naive["M15"]["status"], "unknown_timezone")
        future = evaluate_market_data_freshness(
            {**frames, "M15": self._frame(pd.Timestamp("2026-10-09T13:05:00Z"))},
            now=self.now,
        )
        self.assertEqual(future["M15"]["status"], "incomplete_candle")


if __name__ == "__main__":
    unittest.main()
