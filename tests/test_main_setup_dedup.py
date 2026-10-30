import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd

import config
import main
from database.db_manager import (
    get_latest_symbol_setup,
    has_seen_setup_zone,
    init_db,
    save_setup,
    update_setup_lifecycle,
)
from scanner.setup_state import should_start_new_setup


class MainSetupDedupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_patch = patch.object(
            config, "DB_PATH", os.path.join(self.temp_dir.name, "scanner.sqlite3")
        )
        self.db_path_patch.start()
        init_db()
        main._alerted.clear()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()
        main._alerted.clear()

    def test_same_candidate_is_suppressed_across_scan_calls(self):
        analysis = {
            "bias": "bullish",
            "conditions": ["FVG"],
            "session": "london",
            "signal": {
                "type": "BUY LIMIT",
                "zone": "BUY LIMIT",
                "direction": "BUY",
                "entry": 4188.25,
                "sl": 4180.0,
                "tp1": 4204.75,
                "tp2": 4213.0,
                "rr": 2.0,
                "entry_condition": "Retrace into bullish FVG",
            },
            "levels": {
                "entry": 4188.25,
                "sl": 4180.0,
                "tp1": 4204.75,
                "tp2": 4213.0,
            },
        }
        scoring = {"grade": "A", "score": 4}
        save_setup(
            "XAUUSD",
            "M15",
            analysis,
            scoring,
            setup_identity="XAUUSD-BUY-BUY_LIMIT-4188.25",
            setup_zone="BUY LIMIT",
        )

        now = pd.Timestamp.now(tz="UTC")
        bars = {}
        for timeframe, duration in {"M5": 5, "H4": 240, "H1": 60, "M15": 15}.items():
            frame = pd.DataFrame(
                {"Open": [1.0], "High": [1.1], "Low": [0.9], "Close": [1.0], "Volume": [1.0]},
                index=pd.DatetimeIndex([
                    now - pd.Timedelta(minutes=duration + 5)
                ]),
            )
            frame.attrs.update(provider="BIQUOTE", closed_verified=True)
            bars[timeframe] = frame
        risk_manager = Mock()
        risk_manager.check_risk.return_value = {
            "allowed": True,
            "violations": [],
            "warnings": [],
        }

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch.object(config, "NEWS_FILTER_ENABLED", False),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: bars[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.get_quote", return_value=None),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={
                "current_balance": 10.0,
                "equity": 10.0,
                "daily_start_balance": 10.0,
                "weekly_start_balance": 10.0,
            }),
            patch("main.log_risk"),
            patch("main.evaluate_m5_trigger", return_value=({
                "direction": "BUY", "entry_reference": 4188.25, "sl": 4180.0,
                "tp1": 4204.75, "tp2": 4204.75, "rr": 2.0,
                "timeframe": "M5", "source_setup_type": "BUY LIMIT",
            }, None)),
            patch("main.analyze_symbol", return_value=analysis),
            patch("main.score_setup", return_value=scoring),
            patch("main.generate_chart") as generate_chart,
            patch("main.save_setup") as save_setup_mock,
            patch("main.send_alert") as send_alert,
        ):
            main.scan_once(risk_manager)
            main._alerted.clear()  # Simulate a process restart between scans.
            main.scan_once(risk_manager)

        generate_chart.assert_not_called()
        save_setup_mock.assert_not_called()
        send_alert.assert_not_called()

    def test_old_setup_is_outside_duplicate_window(self):
        now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(main._setup_is_within_dedup_window(
            {"detected_at": "2026-10-09T11:30:00+00:00"}, now=now
        ))
        self.assertFalse(main._setup_is_within_dedup_window(
            {"detected_at": "2026-10-09T10:00:00+00:00"}, now=now
        ))

    def test_minor_entry_stop_and_zone_decimal_changes_remain_same_setup(self):
        active = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "zone": "BULLISH_FVG:4188.25000:4189.20000",
            "entry": 4188.25,
            "sl": 4180.0,
            "state": "ACTIVE",
        }
        candidate = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "zone": "BULLISH_FVG:4188.30000:4189.24000",
            "entry": 4188.30,
            "sl": 4180.03,
        }
        self.assertFalse(should_start_new_setup(active, candidate))

    def test_same_aggressive_zone_blocks_market_entry_drift(self):
        active = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "zone": "BULLISH_AGGRESSIVE_ZONE_SWEEP:4188.05600",
            "entry": 4188.10,
            "state": "ACTIVE",
        }
        candidate = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "zone": "BULLISH_AGGRESSIVE_ZONE_SWEEP:4188.05600",
            "entry": 4189.25,
        }

        self.assertFalse(should_start_new_setup(active, candidate))

    def test_new_structure_zone_is_discoverable_after_invalidation(self):
        active = {
            "symbol": "XAUUSD", "direction": "BUY",
            "zone": "BULLISH_FVG:4188.25000:4189.20000",
            "entry": 4188.25, "state": "INVALIDATED",
        }
        candidate = {
            "symbol": "XAUUSD", "direction": "BUY",
            "zone": "H1_SWING_HIGH:4195.00000", "entry": 4195.0,
        }
        self.assertTrue(should_start_new_setup(active, candidate))

    def test_entry_touch_timestamp_survives_database_reload(self):
        analysis = {
            "bias": "bearish", "signal": {"type": "SELL LIMIT"},
            "levels": {"entry": 4180.0, "sl": 4208.0, "tp1": 4124.0},
        }
        setup_id = save_setup("XAUUSD", "M15", analysis, {"grade": "A", "score": 8})
        touched_at = "2026-10-09T12:15:00+00:00"
        update_setup_lifecycle(setup_id, "ENTRY TOUCHED", "Entry touched; fill unknown", touched_at)

        loaded = get_latest_symbol_setup("XAUUSD")
        self.assertEqual(loaded["lifecycle_state"], "ENTRY TOUCHED")
        self.assertEqual(loaded["entry_touched_at"], touched_at)


if __name__ == "__main__":
    unittest.main()
