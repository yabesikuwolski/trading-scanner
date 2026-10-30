import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

import config
from database.db_manager import apply_setup_event, init_db, resolve_setup_outcome
from scanner.market_analyzer import analyze_symbol, detect_fvg, generate_signal, get_htf_bias
from scanner.scoring_engine import score_setup
from scanner.setup_state import (
    build_setup_id,
    is_same_setup,
    should_start_new_setup,
    transition_state,
)


def market_bars(close=101.0):
    return pd.DataFrame({
        "Open": [close - 0.2] * 20,
        "High": [close + 1.0] * 20,
        "Low": [close - 1.0] * 20,
        "Close": [close] * 20,
    })


class GenerateSignalTests(unittest.TestCase):
    def test_retest_without_rejection_generates_limit_signal(self):
        signal = generate_signal(
            market_bars(), "bullish", [(10, 105.0)], [], [], [(10, 98.0)],
            [{"type": "bullish_fvg", "bottom": 98.0, "top": 99.5,
              "index": 0, "filled": False}],
            {"type": "fvg_retest", "level": 100.0}, None, ["FVG", "Retest"],
            101.0,
        )

        self.assertEqual(signal["type"], "BUY LIMIT")
        self.assertEqual(signal["entry"], 98.0)
        self.assertEqual(signal["zone"], "BULLISH_FVG:98.00000:99.50000")
        self.assertLess(signal["entry"], 101.0)
        self.assertLess(signal["sl"], signal["entry"])
        self.assertGreater(signal["tp1"], signal["entry"])
        self.assertIn("Retest", signal["conditions"])

    def test_bullish_fvg_after_price_breaks_above_gap_generates_limit_signal(self):
        signal = generate_signal(
            market_bars(close=101.0), "bullish", [(10, 105.0)], [], [], [(10, 98.0)],
            [{"type": "bullish_fvg", "bottom": 98.0, "top": 99.5,
              "index": 0, "filled": False}],
            None, None, ["FVG"],
            101.0,
        )

        self.assertEqual(signal["type"], "BUY LIMIT")
        self.assertEqual(signal["entry"], 98.0)
        self.assertNotIn("Liquidity Sweep", signal["conditions"])

    def test_retest_with_rejection_generates_immediate_signal(self):
        signal = generate_signal(
            market_bars(), "bullish", [(10, 105.0)], [], [], [(10, 98.0)],
            [], {"type": "fvg_retest", "level": 100.0},
            {"type": "hammer"}, ["Retest", "Rejection Candle"], 101.0,
        )

        self.assertEqual(signal["type"], "MARKET/IMMEDIATE")
        self.assertEqual(signal["entry"], 101.0)
        self.assertEqual(signal["zone"], "BULLISH_fvg_retest_100.00000")

    def test_unbroken_structure_generates_buy_stop(self):
        signal = generate_signal(
            market_bars(), "bullish", [(10, 102.0)], [], [], [(10, 98.0)], [],
            None, None, ["HTF Bias"], 101.0,
        )

        self.assertEqual(signal["type"], "BUY STOP")
        self.assertEqual(signal["entry"], 102.0)
        self.assertEqual(signal["zone"], "H1_SWING_HIGH:102.00000")
        self.assertIn("H1 close above", signal["entry_condition"])

    def test_retest_generates_sell_limit(self):
        signal = generate_signal(
            market_bars(), "bearish", [], [(10, 95.0)], [(10, 104.0)], [],
                        [{"type": "bearish_fvg", "bottom": 102.5, "top": 103.5,
                            "index": 0, "filled": False}],
                        {"type": "fvg_retest", "level": 102.0}, None,
                        ["FVG", "Retest"], 101.0,
        )

        self.assertEqual(signal["type"], "SELL LIMIT")
        self.assertEqual(signal["entry"], 103.5)
        self.assertGreater(signal["entry"], 101.0)
        self.assertGreater(signal["sl"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])

    def test_unbroken_structure_generates_sell_stop(self):
        signal = generate_signal(
            market_bars(), "bearish", [], [(10, 100.0)], [(10, 104.0)], [],
            [], None, None, ["HTF Bias"], 101.0,
        )

        self.assertEqual(signal["type"], "SELL STOP")
        self.assertEqual(signal["entry"], 100.0)
        self.assertIn("H1 close below", signal["entry_condition"])

    def test_invalid_stop_geometry_rejects_signal(self):
        signal = generate_signal(
            market_bars(), "bullish", [(10, 105.0)], [], [], [(10, 100.5)],
            [{"type": "bullish_fvg", "bottom": 98.0, "top": 99.5,
              "index": 0, "filled": False}],
            {"type": "fvg_retest", "level": 100.0}, None, ["Retest"], 101.0,
        )

        self.assertIsNone(signal)

    def test_previously_retested_fvg_is_not_a_limit_setup(self):
        signal = generate_signal(
            market_bars(), "bullish", [(10, 105.0)], [], [], [(10, 98.0)],
            [{"type": "bullish_fvg", "bottom": 99.0, "top": 100.0,
              "index": 0, "filled": False}],
            None, None, ["FVG"], 101.0,
        )

        self.assertEqual(signal["type"], "BUY STOP")

    def test_no_valid_structure_returns_no_signal(self):
        signal = generate_signal(
            market_bars(close=103.0), "bullish", [(10, 102.0)], [], [],
            [(10, 98.0)], [],
            {"type": "fvg_retest", "level": 104.0}, None,
            ["Retest"], 103.0,
        )

        self.assertIsNone(signal)

    def test_neutral_bias_never_generates_signal(self):
        signal = generate_signal(
            market_bars(), "neutral", [(10, 105.0)], [(10, 95.0)], [], [],
            [], None, None, [], 101.0,
        )

        self.assertIsNone(signal)

    def test_analyze_symbol_requires_directional_liquidity_sweep(self):
        frame = market_bars()
        with patch("scanner.market_analyzer.get_htf_bias", return_value="bullish"), \
             patch("scanner.market_analyzer.detect_swing_points", side_effect=[([(10, 110.0)], [(10, 90.0)]), ([], [])]), \
             patch("scanner.market_analyzer.detect_bos", return_value={"type": "bullish_bos", "level": 110.0}), \
             patch("scanner.market_analyzer.detect_liquidity_sweep", return_value={"type": "bullish_sweep", "level": 90.0}), \
             patch("scanner.market_analyzer.detect_fvg", return_value=[{"type": "bullish_fvg", "bottom": 98.0, "top": 99.5, "index": 0, "filled": False}]), \
             patch("scanner.market_analyzer.detect_retest", return_value={"type": "fvg_retest", "level": 98.0}), \
             patch("scanner.market_analyzer.detect_rejection_candle", return_value={"type": "hammer"}):
            result = analyze_symbol(frame, frame, frame, "XAUUSD")

        self.assertNotIn("BOS", result["conditions"])
        self.assertIn("Liquidity Sweep", result["conditions"])
        self.assertIn("Aggressive Zone", result["conditions"])
        self.assertIn("FVG", result["conditions"])
        self.assertEqual(result["signal"]["type"], "MARKET/IMMEDIATE")

    def test_analyze_symbol_does_not_signal_without_liquidity_sweep(self):
        frame = market_bars()
        with patch("scanner.market_analyzer.get_htf_bias", return_value="bullish"), \
             patch("scanner.market_analyzer.detect_swing_points", return_value=([], [])), \
             patch("scanner.market_analyzer.detect_liquidity_sweep", return_value=None), \
             patch("scanner.market_analyzer.detect_rejection_candle", return_value={"type": "hammer"}):
            result = analyze_symbol(frame, frame, frame, "XAUUSD")

        self.assertIsNone(result["signal"])

    def test_analyze_symbol_does_not_signal_when_h1_disagrees_with_h4(self):
        frame = market_bars()
        with patch("scanner.market_analyzer.get_htf_bias", side_effect=["bullish", "bearish"]), \
             patch("scanner.market_analyzer.detect_swing_points", return_value=([(10, 110.0)], [(10, 90.0)])), \
             patch("scanner.market_analyzer.detect_liquidity_sweep", return_value={"type": "bullish_sweep", "level": 90.0}), \
             patch("scanner.market_analyzer.detect_rejection_candle", return_value={"type": "hammer"}):
            result = analyze_symbol(frame, frame, frame, "XAUUSD")

        self.assertIsNone(result["signal"])

    def test_score_thresholds_match_active_conditions(self):
        full = {
            "bias": "bullish",
            "fvgs": [{"filled": False}],
            "retest": {"type": "fvg_retest"},
            "rejection": {"type": "hammer"},
            "session": "london",
            "levels": {"rr": 2.0},
        }

        scoring = score_setup(full)
        self.assertEqual(scoring["score"], 10)
        self.assertEqual(scoring["grade"], "ELITE")
        self.assertGreaterEqual(config.SCORE_ELITE, 8)

    def test_recent_ema20_uptrend_is_bullish_even_if_ema50_is_still_above_price(self):
        frame = pd.DataFrame({
            "Close": [140] * 30 + [120] * 20 + [118, 119, 120, 121, 122, 123, 124, 125, 126, 127]
        })

        self.assertEqual(get_htf_bias(frame), "bullish")

    def test_duplicate_setup_is_rejected_when_entry_moves_only_slightly(self):
        previous = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.21,
            "sl": 4358.44,
            "tp1": 4342.10,
            "tp2": 4330.00,
        }
        current = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.25,
            "sl": 4358.39,
            "tp1": 4342.17,
            "tp2": 4330.10,
        }

        self.assertTrue(is_same_setup(previous, current))
        self.assertEqual(build_setup_id("XAUUSD", "SELL", "supply_zone_07"), "XAUUSD-SELL-supply_zone_07")

    def test_new_zone_is_not_treated_as_same_setup(self):
        previous = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.21,
        }
        current = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_08",
            "entry": 4348.90,
        }

        self.assertFalse(is_same_setup(previous, current))

    def test_active_setup_blocks_reentry_until_new_event(self):
        active = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.20,
            "state": "ACTIVE",
        }
        candidate = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.25,
        }

        self.assertFalse(should_start_new_setup(active, candidate))

    def test_stopped_out_setup_requires_new_market_event(self):
        active = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.20,
            "state": "STOPPED_OUT",
        }
        candidate = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.24,
        }

        self.assertFalse(should_start_new_setup(active, candidate))

    def test_new_zone_after_cooldown_allows_new_setup(self):
        active = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_07",
            "entry": 4350.20,
            "state": "COOLDOWN",
        }
        candidate = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "zone": "supply_zone_08",
            "entry": 4345.00,
        }

        self.assertTrue(should_start_new_setup(active, candidate))

    def test_lifecycle_transition_requires_state_update(self):
        self.assertEqual(transition_state("ACTIVE", "STOPPED_OUT"), "STOPPED_OUT")
        self.assertEqual(transition_state("STOPPED_OUT", "COOLDOWN"), "COOLDOWN")
        self.assertEqual(transition_state("COOLDOWN", "NEW_SETUP"), "SETUP_DETECTED")

    def test_setup_event_transition_updates_db_record(self):
        init_db()
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO setups (symbol, timeframe, signal_type, bias, grade, score, conditions, entry, sl, tp1, tp2, session, lifecycle_state, lifecycle_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("XAUUSD", "M15", "SELL LIMIT", "bearish", "A", 80, "[]", 4350.0, 4358.0, 4342.0, 4330.0, "london", "ACTIVE", "Signal fired and setup became active"),
            )
            setup_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

        updated = apply_setup_event(setup_id, "INVALIDATED", "Price invalidated by stop loss")

        self.assertTrue(updated)
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute("SELECT lifecycle_state, lifecycle_reason FROM setups WHERE id=?", (setup_id,)).fetchone()
            self.assertEqual(row[0], "INVALIDATED")
            self.assertIn("invalidated", row[1].lower())

    def test_setup_outcome_resolution_marks_completed_state(self):
        init_db()
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO setups (symbol, timeframe, signal_type, bias, grade, score, conditions, entry, sl, tp1, tp2, session, lifecycle_state, lifecycle_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("XAUUSD", "M15", "BUY LIMIT", "bullish", "A", 82, "[]", 2000.0, 1990.0, 2025.0, 2040.0, "london", "ACTIVE", "Signal fired and setup became active"),
            )
            setup_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

        updated = resolve_setup_outcome(setup_id, "TP1_HIT", "Price reached first target")

        self.assertTrue(updated)
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute("SELECT lifecycle_state, lifecycle_reason FROM setups WHERE id=?", (setup_id,)).fetchone()
            self.assertEqual(row[0], "TP1_HIT")
            self.assertIn("first target", row[1].lower())


class DetectFvgTests(unittest.TestCase):
    def test_bullish_fvg_is_filled_when_wick_reaches_far_edge(self):
        frame = pd.DataFrame({
            "Open": [9.0, 10.0, 12.2, 11.0],
            "High": [10.0, 11.0, 13.0, 12.5],
            "Low": [8.0, 9.0, 12.0, 9.8],
            "Close": [9.0, 10.5, 12.5, 11.5],
        })

        fvgs = detect_fvg(frame)

        bullish_fvg = next(fvg for fvg in fvgs if fvg["type"] == "bullish_fvg")
        self.assertTrue(bullish_fvg["filled"])

    def test_partial_fvg_mitigation_does_not_mark_gap_filled(self):
        frame = pd.DataFrame({
            "Open": [9.0, 10.0, 12.2, 11.0],
            "High": [10.0, 11.0, 13.0, 12.5],
            "Low": [8.0, 9.0, 12.0, 10.5],
            "Close": [9.0, 10.5, 12.5, 11.5],
        })

        fvgs = detect_fvg(frame)

        bullish_fvg = next(fvg for fvg in fvgs if fvg["type"] == "bullish_fvg")
        self.assertFalse(bullish_fvg["filled"])

    def test_bearish_fvg_is_filled_when_wick_reaches_far_edge(self):
        frame = pd.DataFrame({
            "Open": [13.0, 11.0, 9.8, 11.0],
            "High": [14.0, 12.0, 10.0, 12.2],
            "Low": [12.0, 10.5, 9.0, 9.5],
            "Close": [13.0, 11.0, 9.5, 10.5],
        })

        fvgs = detect_fvg(frame)

        bearish_fvg = next(fvg for fvg in fvgs if fvg["type"] == "bearish_fvg")
        self.assertTrue(bearish_fvg["filled"])


if __name__ == "__main__":
    unittest.main()
