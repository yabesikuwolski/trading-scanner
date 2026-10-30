import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import config
from alerts import telegram_bot
from database.db_manager import get_connection, init_db, record_setup_notification, save_setup


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            "bias": "bearish",
            "session": "london_ny_overlap",
            "bos": {"type": "bearish_bos"},
            "liquidity_sweep": {"type": "bearish_sweep"},
            "conditions": ["FVG", "Retest", "Rejection Candle"],
            "signal": {
                "type": "SELL LIMIT", "direction": "SELL", "entry": 4350.0,
                "sl": 4358.0, "tp1": 4334.0, "tp2": 4326.0, "rr": 2.0,
                "entry_condition": "M15 retest into the active bearish FVG",
                "conditions": ["FVG", "Retest", "Rejection Candle"],
            },
        }
        self.scoring = {"grade": "A", "score": 8, "max_score": 14}
        telegram_bot._set_delivery("not_attempted")

    def test_alert_formats_setup_risk_feasibility_ai_and_manual_only_notice(self):
        message = telegram_bot.format_alert(
            "XAUUSD", self.analysis, self.scoring,
            simulation_plan={
                "currency": "USD", "risk_amount": 0.2,
                "sizing_status": "BELOW_BROKER_MINIMUM", "position_size": None,
            },
            ai_review={
                "status": "available", "decision": "WATCH", "quality_score": 64,
                "confidence": "MEDIUM", "summary": "The market retest is not confirmed.",
            },
            setup_id="XAUUSD-SELL-BEARISH_FVG-4350.00",
            max_setup_age_minutes=60,
        )

        self.assertIn("XAUUSD — SELL LIMIT", message)
        self.assertIn("Setup ID:", message)
        self.assertIn("Simulation suitability: INFEASIBLE", message)
        self.assertIn("USD 0.2", message)
        self.assertIn("AI advisory:</b> WATCH", message)
        self.assertIn("do not treat this as approval", message)
        self.assertIn("No order or broker fill is confirmed", message)
        self.assertNotIn("Validated scenario volume", message)
        self.assertLessEqual(len(message), 1000)

    def test_unknown_sizing_does_not_claim_a_volume(self):
        message = telegram_bot.format_alert(
            "XAUUSD", self.analysis, self.scoring,
            simulation_plan={
                "currency": "USD", "risk_amount": 0.2,
                "sizing_status": "MISSING_CONTRACT_SPECS", "position_size": None,
            },
            ai_review={"status": "unavailable"},
        )
        self.assertIn("Simulation suitability: UNKNOWN", message)
        self.assertIn("no executable volume shown", message)
        self.assertIn("AI advisory: unavailable", message)

    def test_m5_qualified_entry_is_identified_in_the_alert(self):
        analysis = {
            **self.analysis,
            "signal": {
                **self.analysis["signal"],
                "type": "MARKET/IMMEDIATE",
                "source_setup_type": "SELL LIMIT",
                "entry": 4349.0,
                "entry_condition": "M5 trigger for SELL LIMIT: M5 closed candle broke the previous candle low",
                "conditions": ["FVG", "Retest", "M5 closed-candle trigger confirmed"],
            },
            "m5_confirmation": {"timeframe": "M5"},
        }

        message = telegram_bot.format_alert("XAUUSD", analysis, self.scoring)

        self.assertIn("XAUUSD — SELL MARKET/IMMEDIATE", message)
        self.assertIn("M15 setup: SELL LIMIT", message)
        self.assertIn("M5 trigger for SELL LIMIT", message)
        self.assertIn("M5 closed-candle trigger confirmed", message)
        self.assertNotIn("M15 M5", message)

    def test_calculated_size_is_not_called_account_feasible_without_margin_data(self):
        message = telegram_bot.format_alert(
            "XAUUSD", self.analysis, self.scoring,
            simulation_plan={
                "currency": "USD", "risk_amount": 2.0,
                "sizing_status": "OK", "account_feasibility": "UNKNOWN",
                "position_size": 0.04, "sized_expected_profit": 4.0,
            },
            ai_review={"status": "disabled"},
        )
        self.assertIn("Simulation suitability: UNKNOWN", message)
        self.assertIn("Calculated volume under unverified rules", message)
        self.assertIn("margin and broker settings are not verified", message)
        self.assertNotIn("FEASIBLE</b>", message)

    def test_lifecycle_notification_is_suppressed_from_phone(self):
        setup = {
            "symbol": "XAUUSD", "signal_type": "SELL LIMIT", "bias": "bearish",
            "entry": 4350, "sl": 4360, "tp1": 4330, "setup_identity": "setup-1",
        }
        with patch("alerts.telegram_bot.send_message") as send_message:
            sent = telegram_bot.send_lifecycle_update(setup, {
                "state": "ENTRY TOUCHED",
                "reason": "M15 price reached planned entry.",
            })
            self.assertFalse(telegram_bot.send_lifecycle_update(setup, {"state": "READY"}))
        self.assertFalse(sent)
        send_message.assert_not_called()

    def test_startup_and_risk_status_are_suppressed_from_phone(self):
        with patch("alerts.telegram_bot.send_message") as send_message:
            self.assertFalse(telegram_bot.send_startup_message(["XAUUSD"]))
            self.assertFalse(telegram_bot.send_risk_alert(["drawdown limit reached"]))
        send_message.assert_not_called()

    def test_legacy_signal_dispatch_cannot_bypass_validated_notifier(self):
        with patch("alerts.telegram_bot.send_message") as send_message:
            sent = telegram_bot.send_alert(
                "XAUUSD", {"signal": {"direction": "BUY"}}, {"score": 99},
                alert_stage="entry_confirmed",
            )
        self.assertFalse(sent)
        send_message.assert_not_called()

    def test_dynamic_text_is_html_escaped(self):
        unsafe = {**self.analysis, "signal": {**self.analysis["signal"], "entry_condition": "<bad>&"}}
        message = telegram_bot.format_alert("XAU<USD", unsafe, self.scoring)
        self.assertIn("XAU&lt;USD", message)
        self.assertIn("&lt;bad&gt;&amp;", message)

    def test_missing_credentials_is_noop_and_reported(self):
        with patch.object(config, "TELEGRAM_BOT_TOKEN", ""), \
             patch.object(config, "TELEGRAM_CHAT_ID", ""), \
             patch("alerts.telegram_bot.requests.post") as post:
            sent = telegram_bot.send_message("hello")
        self.assertFalse(sent)
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "not_configured")
        post.assert_not_called()

    def test_success_requires_telegram_api_ok_true(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 42}}
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "token-test"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "chat-test"), \
             patch("alerts.telegram_bot.requests.post", return_value=response) as post:
            sent = telegram_bot.send_message("hello")
        self.assertTrue(sent)
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "success")
        self.assertEqual(post.call_args.kwargs["timeout"], config.TELEGRAM_TIMEOUT_SECONDS)

    def test_api_failure_and_exception_are_redacted(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": False, "description": "token-test rejected"}
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "token-test"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "chat-test"), \
             patch("alerts.telegram_bot.requests.post", return_value=response):
            self.assertFalse(telegram_bot.send_message("hello"))
        error = telegram_bot.get_last_delivery_status()["error"]
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "api_error")
        self.assertNotIn("token-test", error)
        self.assertIn("[REDACTED]", error)

        with patch.object(config, "TELEGRAM_BOT_TOKEN", "token-test"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "chat-test"), \
             patch("alerts.telegram_bot.requests.post", side_effect=telegram_bot.requests.Timeout("https://x/bottoken-test")):
            self.assertFalse(telegram_bot.send_message("hello"))
        error = telegram_bot.get_last_delivery_status()["error"]
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "timeout")
        self.assertNotIn("token-test", error)

    def test_http_failure_and_invalid_success_body_are_rejected(self):
        response = Mock(status_code=403, text="token-test forbidden")
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "token-test"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "chat-test"), \
             patch("alerts.telegram_bot.requests.post", return_value=response):
            self.assertFalse(telegram_bot.send_message("hello"))
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "http_error")
        self.assertNotIn("token-test", telegram_bot.get_last_delivery_status()["error"])

        response = Mock(status_code=200)
        response.json.side_effect = ValueError("invalid JSON")
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "token-test"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "chat-test"), \
             patch("alerts.telegram_bot.requests.post", return_value=response):
            self.assertFalse(telegram_bot.send_message("hello"))
        self.assertEqual(telegram_bot.get_last_delivery_status()["status"], "invalid_response")

    def test_delivery_status_is_persisted_on_setup(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "DB_PATH", os.path.join(directory, "scanner.sqlite3")):
            init_db()
            setup_id = save_setup("XAUUSD", "M15", {"signal": {}, "levels": {}}, {})
            record_setup_notification(setup_id, "failed", "Telegram timeout")
            conn = get_connection()
            row = conn.execute(
                "SELECT telegram_status, telegram_error, telegram_attempted_at FROM setups WHERE id=?",
                (setup_id,),
            ).fetchone()
            conn.close()
        self.assertEqual(row["telegram_status"], "failed")
        self.assertEqual(row["telegram_error"], "Telegram timeout")
        self.assertIsNotNone(row["telegram_attempted_at"])


if __name__ == "__main__":
    unittest.main()
