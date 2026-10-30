import unittest
from unittest.mock import patch

import pandas as pd

from scanner.signal_replay import (
    closed_window,
    evaluate_signal_outcomes,
    replay_signals,
)


def bars(index):
    return pd.DataFrame({
        "Open": [100.0] * len(index),
        "High": [101.0] * len(index),
        "Low": [99.0] * len(index),
        "Close": [100.5] * len(index),
        "Volume": [1] * len(index),
    }, index=index)


class SignalReplayTests(unittest.TestCase):
    def test_outcome_counts_stop_when_stop_and_target_share_a_bar(self):
        signals = pd.DataFrame([{
            "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
            "signal_type": "MARKET/IMMEDIATE",
            "direction": "BUY",
            "entry": 100.0,
            "sl": 98.0,
            "tp1": 104.0,
        }])
        bars_frame = bars(pd.date_range(
            "2024-01-01T00:00:00Z", periods=1, freq="15min"
        ))
        bars_frame.loc[:, "High"] = 105.0
        bars_frame.loc[:, "Low"] = 97.0

        result = evaluate_signal_outcomes(signals, bars_frame)

        self.assertEqual(result.iloc[0]["outcome"], "stop_loss")
        self.assertEqual(result.iloc[0]["r_multiple"], -1.0)
        self.assertTrue(result.iloc[0]["tp1_reached"])
        self.assertTrue(result.iloc[0]["stop_reached"])
        self.assertAlmostEqual(result.iloc[0]["mfe_r"], 2.5)
        self.assertAlmostEqual(result.iloc[0]["mae_r"], 1.5)
        self.assertIn("intrabar path unknown", result.iloc[0]["excursion_method"])
        self.assertTrue(result.iloc[0]["tp1_reached"])
        self.assertTrue(result.iloc[0]["stop_reached"])
        self.assertAlmostEqual(result.iloc[0]["mfe_r"], 2.5)
        self.assertAlmostEqual(result.iloc[0]["mae_r"], 1.5)
        self.assertIn("intrabar path unknown", result.iloc[0]["excursion_method"])

    def test_pending_limit_can_expire_without_a_fill(self):
        signals = pd.DataFrame([{
            "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
            "signal_type": "BUY LIMIT",
            "direction": "BUY",
            "entry": 98.0,
            "sl": 97.0,
            "tp1": 103.0,
        }])
        bars_frame = bars(pd.date_range(
            "2024-01-01T00:00:00Z", periods=2, freq="15min"
        ))

        result = evaluate_signal_outcomes(signals, bars_frame, max_holding_bars=2)

        self.assertEqual(result.iloc[0]["fill_status"], "unfilled")
        self.assertEqual(result.iloc[0]["outcome"], "unfilled")
        self.assertIsNone(result.iloc[0]["r_multiple"])
        self.assertIsNone(result.iloc[0]["mfe_r"])

    def test_replay_records_second_target_and_favorable_close_time(self):
        signals = pd.DataFrame([{
            "setup_id": "fixture-1",
            "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
            "signal_type": "MARKET/IMMEDIATE",
            "direction": "BUY",
            "entry": 100.0,
            "sl": 98.0,
            "tp1": 110.0,
            "tp2": 112.0,
        }])
        index = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="15min")
        candles = bars(index)
        candles.loc[:, "High"] = [103.0, 111.0, 113.0]
        candles.loc[:, "Low"] = [99.0, 100.0, 100.0]
        candles.loc[:, "Close"] = [102.0, 109.0, 112.0]

        result = evaluate_signal_outcomes(signals, candles)

        self.assertEqual(result.iloc[0]["fill_time"], index[0])
        self.assertTrue(result.iloc[0]["tp1_reached"])
        self.assertTrue(result.iloc[0]["tp2_reached"])
        self.assertEqual(result.iloc[0]["favorable_close_bars"], 1)
        self.assertEqual(result.iloc[0]["favorable_close_minutes"], 15)
        self.assertIsNone(result.iloc[0]["mfe_r"])

    def test_replay_records_second_target_and_favorable_close_time(self):
        signals = pd.DataFrame([{
            "setup_id": "fixture-1",
            "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
            "signal_type": "MARKET/IMMEDIATE",
            "direction": "BUY",
            "entry": 100.0,
            "sl": 98.0,
            "tp1": 110.0,
            "tp2": 112.0,
        }])
        index = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="15min")
        candles = bars(index)
        candles.loc[:, "High"] = [103.0, 111.0, 113.0]
        candles.loc[:, "Low"] = [99.0, 100.0, 100.0]
        candles.loc[:, "Close"] = [102.0, 109.0, 112.0]

        result = evaluate_signal_outcomes(signals, candles)

        self.assertEqual(result.iloc[0]["fill_time"], index[0])
        self.assertTrue(result.iloc[0]["tp1_reached"])
        self.assertTrue(result.iloc[0]["tp2_reached"])
        self.assertEqual(result.iloc[0]["favorable_close_bars"], 1)
        self.assertEqual(result.iloc[0]["favorable_close_minutes"], 15)

    def test_closed_window_excludes_higher_timeframe_bar_until_close(self):
        index = pd.date_range("2026-09-29T10:00:00Z", periods=4, freq="1h")
        frame = bars(index)

        window = closed_window(frame, "H1", "2026-09-29T12:00:00Z", 200)

        self.assertEqual(list(window.index), list(index[:2]))

    @patch("scanner.signal_replay.score_setup")
    @patch("scanner.signal_replay.analyze_symbol")
    def test_replay_uses_only_closed_bars_and_keeps_warmup(
        self, mock_analyze, mock_score
    ):
        h4_index = pd.date_range(
            end="2024-01-10T12:00:00Z", periods=60, freq="4h"
        )
        h1_index = pd.date_range(
            end="2024-01-10T12:00:00Z", periods=20, freq="1h"
        )
        m15_index = pd.date_range(
            "2024-01-10T12:00:00Z", periods=4, freq="15min"
        )
        h4_frame = bars(h4_index)
        h1_frame = bars(h1_index)
        m15_frame = bars(m15_index)
        mock_analyze.return_value = {
            "bias": "bullish",
            "signal": {
                "type": "BUY STOP",
                "direction": "BUY",
                "entry": 101.0,
                "sl": 99.0,
                "tp1": 105.0,
                "tp2": 107.0,
                "rr": 2.0,
                "entry_condition": "test trigger",
                "conditions": ["BOS"],
            },
        }
        mock_score.return_value = {"grade": "A", "score": 7}

        signals = replay_signals(
            h4_frame,
            h1_frame,
            m15_frame,
            start_time="2024-01-10T12:30:00Z",
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals.iloc[0]["decision_time"], pd.Timestamp("2024-01-10T12:45:00Z"))
        self.assertEqual(signals.attrs["decision_count"], 3)
        self.assertEqual(signals.attrs["duplicate_suppressed_count"], 1)
        evaluated = evaluate_signal_outcomes(signals, m15_frame)
        self.assertEqual(evaluated.attrs["decision_count"], 3)
        first_call = mock_analyze.call_args_list[0]
        first_h4, first_h1, first_m15, _ = first_call.args
        kwargs = first_call.kwargs
        decision_time = kwargs["as_of"]
        self.assertGreater(len(first_h4), 50)
        self.assertGreater(len(first_h1), 10)
        self.assertLessEqual(first_h4.index[-1] + pd.Timedelta(hours=4), decision_time)
        self.assertLessEqual(first_h1.index[-1] + pd.Timedelta(hours=1), decision_time)
        self.assertLessEqual(first_m15.index[-1] + pd.Timedelta(minutes=15), decision_time)

    def test_open_trade_blocks_overlapping_signal_and_cost_is_subtracted(self):
        signals = pd.DataFrame([
            {
                "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
                "signal_type": "MARKET/IMMEDIATE",
                "direction": "BUY",
                "entry": 100.0,
                "sl": 98.0,
                "tp1": 104.0,
            },
            {
                "decision_time": pd.Timestamp("2024-01-01T00:00:00Z"),
                "signal_type": "MARKET/IMMEDIATE",
                "direction": "BUY",
                "entry": 100.0,
                "sl": 98.0,
                "tp1": 104.0,
            },
        ])
        bars_frame = bars(pd.date_range(
            "2024-01-01T00:00:00Z", periods=3, freq="15min"
        ))
        bars_frame.loc[:, "High"] = 105.0

        result = evaluate_signal_outcomes(
            signals, bars_frame, transaction_cost_r=0.1
        )

        self.assertEqual(result.iloc[0]["outcome"], "take_profit")
        self.assertAlmostEqual(result.iloc[0]["gross_r_multiple"], 2.0)
        self.assertAlmostEqual(result.iloc[0]["r_multiple"], 1.9)
        self.assertEqual(result.iloc[1]["outcome"], "overlap_blocked")

    def test_replay_rejects_naive_candle_indexes(self):
        naive = pd.date_range("2024-01-01", periods=2, freq="15min")
        aware = pd.date_range("2024-01-01T00:00:00Z", periods=2, freq="1h")

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            replay_signals(bars(aware), bars(aware), bars(naive))


if __name__ == "__main__":
    unittest.main()
