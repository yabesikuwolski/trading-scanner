import os
import tempfile
import unittest
from unittest.mock import patch

import config
import main
from alerts import notifier
from database.db_manager import (
    get_connection,
    get_latest_symbol_setup,
    init_db,
    record_setup_notification,
    save_setup,
)


class SignalOnlyNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", os.path.join(self.temp_dir.name, "scanner.sqlite3"))
        self.db_patch.start()
        init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _confirmed_signal(self):
        return {
            "bias": "bullish", "confirmed_bias": "bullish",
            "conditions": ["H4 Trend", "H1 Trend", "FVG", "Retest"],
            "m5_confirmation": {
                "timeframe": "M5", "closed_verified": True,
                "candle_open_time": "2026-10-22T10:00:00+00:00",
                "candle_close_time": "2026-10-22T10:05:00+00:00",
                "conditions": ["H4 bias", "H1 confirmation", "M15 setup", "M5 closed-candle trigger"],
            },
            "signal": {
                "type": "MARKET/IMMEDIATE", "source_setup_type": "BUY LIMIT",
                "direction": "BUY", "entry": 4350.0, "sl": 4342.0,
                "tp1": 4366.0, "tp2": 4374.0, "rr": 2.0,
                "entry_condition": "M5 closed candle broke the previous candle high",
                "conditions": ["H4 Trend", "H1 Trend", "M15 FVG retest",
                               "M5 closed-candle trigger confirmed"],
            },
        }

    def test_only_confirmed_m5_entry_reaches_ntfy_with_trade_levels(self):
        with patch.object(config, "NOTIFICATION_PROVIDER", "NTFY"), \
             patch.object(config, "NTFY_TOPIC", "test-topic"), \
             patch("alerts.notifier.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            sent = notifier.send_alert(
                "XAUUSD", self._confirmed_signal(), {"grade": "A", "score": 8},
                alert_stage="entry_confirmed",
            )

        self.assertTrue(sent)
        self.assertEqual(post.call_args.kwargs["headers"]["Title"], "XAUUSD ENTRY SIGNAL CONFIRMED")
        self.assertEqual(post.call_args.kwargs["headers"]["Priority"], "high")
        body = post.call_args.kwargs["data"]
        for detail in ("BUY", "4350.0", "4342.0", "4366.0", "4374.0", "2.0R", "M5 closed candle"):
            self.assertIn(detail, body)

    def test_approach_or_unverified_m5_alert_is_rejected_without_phone_dispatch(self):
        confirmed = self._confirmed_signal()
        invalid_stage = notifier.send_alert(
            "XAUUSD", confirmed, {"grade": "A"}, alert_stage="setup_approaching"
        )
        missing_m5 = self._confirmed_signal()
        missing_m5.pop("m5_confirmation")
        invalid_m5 = notifier.send_alert(
            "XAUUSD", missing_m5, {"grade": "A"}, alert_stage="entry_confirmed"
        )
        self.assertFalse(invalid_stage)
        self.assertFalse(invalid_m5)
        self.assertEqual(notifier.get_last_delivery_status()["status"], "rejected")

    def test_diagnostics_expose_h1_and_m15_blockers_locally(self):
        diagnostics = main._candidate_diagnostics(
            {"bias": "bullish", "confirmed_bias": "bearish", "signal": None,
             "retest": {"type": "fvg_retest"}, "rejection": None},
            {"score": 5, "grade": "A"},
        )
        self.assertIn("H1 bias bearish does not confirm H4 bullish", diagnostics)
        self.assertIn("M15 retest exists", diagnostics)

    def test_cooldown_check_does_not_consume_candidate_before_delivery(self):
        key = "XAUUSD_test_candidate_not_yet_sent"
        main._alerted.pop(key, None)
        self.assertTrue(main._cooldown_ok(key))
        self.assertNotIn(key, main._alerted)

    def test_failed_qualified_entry_retries_after_dedup_backoff(self):
        analysis = self._confirmed_signal()
        setup_id = save_setup(
            "XAUUSD", "M15", analysis, {"grade": "A", "score": 8},
            setup_identity="same-entry", setup_zone="same-zone",
        )
        record_setup_notification(setup_id, "failed", "temporary timeout")
        conn = get_connection()
        conn.execute(
            "UPDATE setups SET telegram_attempted_at='2026-10-22T00:00:00+00:00' WHERE id=?",
            (setup_id,),
        )
        conn.commit()
        conn.close()
        with patch("main.send_alert", return_value=True) as send_alert, \
             patch("main.get_last_delivery_status", return_value={"status": "sent", "error": None}):
            self.assertTrue(main._retry_undelivered_entry("XAUUSD", analysis, {"grade": "A"}))
            self.assertFalse(main._retry_undelivered_entry("XAUUSD", analysis, {"grade": "A"}))

        send_alert.assert_called_once()
        self.assertEqual(send_alert.call_args.args[4], "entry_confirmed")
        self.assertEqual(get_latest_symbol_setup("XAUUSD")["telegram_status"], "sent")


if __name__ == "__main__":
    unittest.main()
