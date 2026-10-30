import os
import json
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import config
import main
from database.db_manager import get_latest_symbol_setup, init_db
from risk.risk_manager import RiskManager


class ScannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", os.path.join(self.temp_dir.name, "scanner.sqlite3"))
        self.db_patch.start()
        init_db()
        main._alerted.clear()
        main._process_setup_keys.clear()

    def tearDown(self):
        main._alerted.clear()
        main._process_setup_keys.clear()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _bar(self, timeframe, now, age_after_close_minutes=5):
        duration = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}[timeframe]
        frame = pd.DataFrame(
            {"Open": [4350.0], "High": [4352.0], "Low": [4348.0], "Close": [4351.0], "Volume": [1.0]},
            index=pd.DatetimeIndex([
                now - pd.Timedelta(minutes=duration + age_after_close_minutes)
            ]),
        )
        frame.attrs.update(provider="BIQUOTE", closed_verified=True)
        return frame

    def _confirmed_m5_bars(self, now):
        rows = [(4353.0, 4355.0, 4351.0, 4353.0)] * 13
        rows.append((4355.0, 4356.0, 4348.0, 4350.0))
        frame = pd.DataFrame(
            rows,
            columns=["Open", "High", "Low", "Close"],
            index=pd.date_range(
                end=now - pd.Timedelta(minutes=10), periods=14, freq="5min"
            ),
        )
        frame["Volume"] = 1.0
        frame.attrs.update(provider="BIQUOTE", closed_verified=True)
        return frame

    def test_setup_flows_through_advisory_sizing_persistence_and_single_alert(self):
        now = pd.Timestamp.now(tz="UTC")
        bars = {tf: self._bar(tf, now) for tf in ("H4", "H1", "M15")}
        bars["M5"] = self._confirmed_m5_bars(now)
        analysis = {
            "bias": "bearish",
            "conditions": ["FVG", "Retest"],
            "session": "london",
            "bos": {"type": "bearish_bos", "level": 4355.0},
            "liquidity_sweep": None,
            "fvgs": [{"type": "bearish_fvg", "top": 4352.0, "bottom": 4350.0, "filled": False}],
            "retest": {"type": "fvg_retest", "level": 4352.0},
            "rejection": None,
            "signal": {
                "type": "SELL LIMIT", "zone": "BEARISH_FVG:4350.00000:4352.00000",
                "direction": "SELL", "entry": 4352.0, "sl": 4360.0,
                "tp1": 4336.0, "tp2": 4328.0, "rr": 2.0,
                "entry_condition": "M15 retrace into active bearish FVG",
                "conditions": ["FVG", "Retest"],
            },
            "levels": {"entry": 4352.0, "sl": 4360.0, "tp1": 4336.0, "tp2": 4328.0},
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch.object(config, "NEWS_FILTER_ENABLED", True),
            patch("main.is_news_blackout", side_effect=[(True, "scheduled event"), (False, None)]),
            patch.object(config, "AI_ADVISOR_ENABLED", True),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: bars[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.get_quote", return_value=None),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={
                "current_balance": 10.0, "equity": 10.0,
                "daily_start_balance": 10.0, "weekly_start_balance": 10.0,
            }),
            patch("main.log_risk"),
            patch("main.analyze_symbol", side_effect=lambda *_: deepcopy(analysis)),
            patch("main.score_setup", return_value={"grade": "A", "score": 8, "max_score": 14}),
            patch("main.generate_chart", return_value=None),
            patch("main.review_setup", return_value={
                "status": "available", "decision": "NO_TRADE", "quality_score": 20,
                "confidence": "LOW", "summary": "AI concerns; technical rules remain deterministic.",
                "reasons": ["Mixed context"], "invalidations": ["Break of structure fails"],
                "risk_note": "Account feasibility remains unknown.",
            }),
            patch("main.get_last_delivery_status", return_value={"status": "success", "error": None}),
            patch("main.send_alert", return_value=True) as send_alert,
        ):
            main.scan_once(risk_manager)
            self.assertIsNone(get_latest_symbol_setup("XAUUSD"))
            main.scan_once(risk_manager)
            saved = get_latest_symbol_setup("XAUUSD")
            main._alerted.clear()  # Scanner restart: persistent identity still suppresses a duplicate.
            main.scan_once(risk_manager)
            updated = get_latest_symbol_setup("XAUUSD")

        send_alert.assert_called_once()
        self.assertEqual(saved["ai_status"], "available")
        self.assertEqual(saved["ai_decision"], "NO_TRADE")
        self.assertEqual(saved["telegram_status"], "sent")
        self.assertEqual(saved["setup_zone"], analysis["signal"]["zone"])
        self.assertEqual(json.loads(saved["simulation_plan"])["sizing_status"], "MISSING_CONTRACT_SPECS")
        alert_kwargs = send_alert.call_args.kwargs
        self.assertEqual(alert_kwargs["simulation_plan"]["risk_amount"], 0.2)
        self.assertEqual(alert_kwargs["ai_review"]["decision"], "NO_TRADE")
        self.assertEqual(alert_kwargs["max_setup_age_minutes"], config.MAX_SETUP_AGE_MINUTES)
        qualified_analysis = send_alert.call_args.args[1]
        self.assertEqual(qualified_analysis["signal"]["type"], "MARKET/IMMEDIATE")
        self.assertIn("M5 closed-candle trigger confirmed", qualified_analysis["signal"]["conditions"])
        self.assertEqual(qualified_analysis["m5_confirmation"]["timeframe"], "M5")
        self.assertAlmostEqual(qualified_analysis["signal"]["entry"], 4350.0)
        self.assertEqual(updated["lifecycle_state"], "ENTRY TOUCHED")
        self.assertIsNotNone(updated["entry_touched_at"])
        self.assertIsNone(updated["lifecycle_telegram_status"])

    def test_stale_m15_data_pauses_analysis_and_logs_locally(self):
        now = pd.Timestamp.now(tz="UTC")
        frames = {
            "H4": self._bar("H4", now),
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now, age_after_close_minutes=75),
            "M5": self._bar("M5", now),
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch.object(config, "NEWS_FILTER_ENABLED", False),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.get_quote", return_value=None),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={
                "current_balance": 10.0, "equity": 10.0,
                "daily_start_balance": 10.0, "weekly_start_balance": 10.0,
            }),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.analyze_symbol") as analyze_symbol,
            patch("main.send_alert") as send_alert,
        ):
            with self.assertLogs("main", level="WARNING") as captured:
                main.scan_once(risk_manager)

        analyze_symbol.assert_not_called()
        send_alert.assert_not_called()
        self.assertIn("M15=stale M15 candles", "\n".join(captured.output))

    def test_stale_h4_data_pauses_analysis(self):
        now = pd.Timestamp.now(tz="UTC")
        frames = {
            "H4": self._bar("H4", now, age_after_close_minutes=271),
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now),
            "M5": self._bar("M5", now),
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.get_quote", return_value=None),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={
                "equity": 10.0, "daily_start_balance": 10.0, "weekly_start_balance": 10.0,
            }),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.analyze_symbol") as analyze_symbol,
            patch("main.send_alert") as send_alert,
        ):
            with self.assertLogs("main", level="WARNING") as captured:
                main.scan_once(risk_manager)

        analyze_symbol.assert_not_called()
        send_alert.assert_not_called()
        self.assertIn("H4=stale H4 candles", "\n".join(captured.output))

    def test_missing_h4_data_pauses_analysis(self):
        now = pd.Timestamp.now(tz="UTC")
        frames = {
            "H4": None,
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now),
            "M5": self._bar("M5", now),
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={
                "equity": 10.0, "daily_start_balance": 10.0, "weekly_start_balance": 10.0,
            }),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.analyze_symbol") as analyze_symbol,
            patch("main.send_alert") as send_alert,
        ):
            with self.assertLogs("main", level="WARNING") as captured:
                main.scan_once(risk_manager)

        analyze_symbol.assert_not_called()
        send_alert.assert_not_called()
        self.assertIn("H4=missing candles", "\n".join(captured.output))

    def test_missing_m5_allows_preliminary_analysis_but_not_entry(self):
        now = pd.Timestamp.now(tz="UTC")
        frames = {
            "M5": None,
            "H4": self._bar("H4", now),
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now),
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={"equity": 10.0}),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.analyze_symbol", return_value={
                "symbol": "XAUUSD", "bias": "neutral", "confirmed_bias": "neutral",
                "conditions": [], "signal": None, "fvgs": [], "levels": None,
            }) as analyze_symbol,
            patch("main.send_alert") as send_alert,
        ):
            with self.assertLogs("main", level="WARNING") as captured:
                main.scan_once(risk_manager)

        analyze_symbol.assert_called_once()
        send_alert.assert_not_called()
        self.assertIn("M5=missing candles", "\n".join(captured.output))

    def test_stale_m5_allows_preliminary_analysis_but_not_entry(self):
        now = pd.Timestamp.now(tz="UTC")
        frames = {
            "M5": self._bar("M5", now, age_after_close_minutes=36),
            "H4": self._bar("H4", now),
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now),
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={"equity": 10.0}),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.analyze_symbol", return_value={
                "symbol": "XAUUSD", "bias": "neutral", "confirmed_bias": "neutral",
                "conditions": [], "signal": None, "fvgs": [], "levels": None,
            }) as analyze_symbol,
            patch("main.send_alert") as send_alert,
        ):
            with self.assertLogs("main", level="WARNING") as captured:
                main.scan_once(risk_manager)

        analyze_symbol.assert_called_once()
        send_alert.assert_not_called()
        self.assertIn("M5=stale M5 candles", "\n".join(captured.output))

    def test_unconfirmed_m5_trigger_withholds_actionable_alert(self):
        now = pd.Timestamp.now(tz="UTC")
        m5 = self._confirmed_m5_bars(now)
        m5.iloc[-1, m5.columns.get_loc("Close")] = 4354.0
        frames = {
            "M5": m5,
            "H4": self._bar("H4", now),
            "H1": self._bar("H1", now),
            "M15": self._bar("M15", now),
        }
        analysis = {
            "bias": "bearish",
            "conditions": ["FVG", "Retest"],
            "signal": {
                "type": "SELL LIMIT", "zone": "BEARISH_FVG:4350:4352",
                "direction": "SELL", "entry": 4352.0, "sl": 4360.0,
                "tp1": 4336.0, "tp2": 4328.0, "rr": 2.0,
                "entry_condition": "M15 setup",
            },
            "levels": {"entry": 4352.0, "sl": 4360.0, "tp1": 4336.0, "tp2": 4328.0},
        }
        risk_manager = RiskManager()

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch.object(config, "NEWS_FILTER_ENABLED", False),
            patch("main.get_bars", side_effect=lambda _symbol, timeframe, _count: frames[timeframe]),
            patch("main.store_market_bars"),
            patch("main.get_account_info", return_value={}),
            patch("main.save_broker_account_snapshot"),
            patch("main.get_simulation_performance", return_value={"equity": 10.0}),
            patch("main.log_risk"),
            patch.object(risk_manager, "check_risk", return_value={"allowed": True, "violations": [], "warnings": []}),
            patch("main.get_quote", return_value=None),
            patch("main.analyze_symbol", return_value=analysis),
            patch("main.score_setup", return_value={"grade": "A", "score": 8}),
            patch("main.send_alert") as send_alert,
            patch("main.save_setup") as save_setup,
        ):
            with self.assertLogs("main", level="INFO") as captured:
                main.scan_once(risk_manager)

        send_alert.assert_not_called()
        save_setup.assert_not_called()
        self.assertIn("M5 trigger not confirmed", "\n".join(captured.output))
        self.assertIn("did not break the previous candle low", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
