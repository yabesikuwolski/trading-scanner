import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from scanner.m5_strategy import evaluate_m5_trigger


class M5StrategyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
        rows = [(4353.0, 4355.0, 4351.0, 4353.0)] * 13
        rows.append((4355.0, 4356.0, 4348.0, 4350.0))
        self.bars = pd.DataFrame(
            rows,
            columns=["Open", "High", "Low", "Close"],
            index=pd.date_range(
                end=self.now - timedelta(minutes=10), periods=14, freq="5min"
            ),
        )
        self.bars["Volume"] = 1.0
        self.bars.attrs["closed_verified"] = True
        self.analysis = {
            "signal": {"direction": "SELL", "type": "SELL LIMIT", "sl": 4360.0}
        }

    def test_closed_m5_break_confirms_and_returns_trigger_levels(self):
        confirmation, reason = evaluate_m5_trigger(
            self.analysis, self.bars, now=self.now
        )

        self.assertIsNone(reason)
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation["timeframe"], "M5")
        self.assertEqual(confirmation["direction"], "SELL")
        self.assertEqual(confirmation["entry_reference"], 4350.0)
        self.assertEqual(confirmation["rr"], 2.0)

    def test_missing_stale_unverified_and_open_m5_data_do_not_confirm(self):
        confirmation, reason = evaluate_m5_trigger(self.analysis, None, now=self.now)
        self.assertIsNone(confirmation)
        self.assertEqual(reason, "M5 candles missing")

        stale = self.bars.copy()
        stale.index = stale.index - timedelta(minutes=40)
        stale.attrs["closed_verified"] = True
        confirmation, reason = evaluate_m5_trigger(self.analysis, stale, now=self.now)
        self.assertIsNone(confirmation)
        self.assertIn("stale", reason)

        unverified = self.bars.copy()
        unverified.attrs["closed_verified"] = False
        confirmation, reason = evaluate_m5_trigger(self.analysis, unverified, now=self.now)
        self.assertIsNone(confirmation)
        self.assertIn("closure was not verified", reason)

        open_bar = self.bars.copy()
        open_bar.index = open_bar.index + timedelta(minutes=8)
        confirmation, reason = evaluate_m5_trigger(self.analysis, open_bar, now=self.now)
        self.assertIsNone(confirmation)
        self.assertEqual(reason, "latest M5 candle is still open")

    def test_unbroken_previous_candle_level_does_not_confirm(self):
        unbroken = self.bars.copy()
        unbroken.iloc[-1, unbroken.columns.get_loc("Close")] = 4354.0

        confirmation, reason = evaluate_m5_trigger(
            self.analysis, unbroken, now=self.now
        )

        self.assertIsNone(confirmation)
        self.assertEqual(reason, "latest M5 close did not break the previous candle low")


if __name__ == "__main__":
    unittest.main()
