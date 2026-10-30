import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import config
from database.db_manager import (
    get_connection,
    get_signal_ledger,
    init_db,
    log_trade,
    record_setup_decision,
    save_market_bars,
    save_setup,
)
from scanner.setup_outcome_tracker import refresh_setup_outcomes


class SetupOutcomeTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            config, "DB_PATH", os.path.join(self.temp_dir.name, "scanner.sqlite3")
        )
        self.db_patch.start()
        init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def make_setup(self, *, setup_time="2026-01-01T00:00:00+00:00", entry=100.0):
        analysis = {
            "bias": "bullish",
            "signal": {
                "type": "BUY LIMIT",
                "direction": "BUY",
            },
            "levels": {"entry": entry, "sl": 98.0, "tp1": 104.0, "tp2": 106.0},
        }
        setup_id = save_setup(
            "XAUUSD", "M15", analysis, {"grade": "A+", "score": 8}
        )
        connection = get_connection()
        connection.execute(
            "UPDATE setups SET detected_at=?, direction='BUY' WHERE id=?",
            (setup_time, setup_id),
        )
        connection.commit()
        connection.close()
        return setup_id

    def add_bars(self, times, rows, source="TEST-SOURCE"):
        frame = pd.DataFrame(
            rows,
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex(pd.to_datetime(times, utc=True)),
        )
        frame.index.name = "bar_time"
        save_market_bars(frame.assign(
            source=source,
            symbol="XAUUSD",
            timeframe="M15",
        )[["source", "symbol", "timeframe", "Open", "High", "Low", "Close", "Volume"]])

    def test_each_setup_has_review_status_and_actions_are_audited(self):
        setup_id = self.make_setup()
        first = get_signal_ledger(10)[0]
        self.assertEqual(first["tracking_action"], "UNREVIEWED")
        self.assertEqual(first["modeled_status"], "PENDING")
        self.assertEqual(first["direction"], "BUY")

        record_setup_decision(setup_id, "PAPER_TRACKED")
        record_setup_decision(setup_id, "SKIPPED", "No confirmation")
        latest = get_signal_ledger(10)[0]
        self.assertEqual(latest["tracking_action"], "SKIPPED")
        self.assertEqual(latest["tracking_reason"], "No confirmation")
        self.assertEqual(latest["lifecycle_state"], "REVIEWED")

        with self.assertRaisesRegex(ValueError, "reason is required"):
            record_setup_decision(setup_id, "SKIPPED")

        connection = get_connection()
        actions = connection.execute(
            "SELECT action FROM setup_action_log WHERE setup_id=? ORDER BY id",
            (setup_id,),
        ).fetchall()
        connection.close()
        self.assertEqual([row["action"] for row in actions], ["PAPER_TRACKED", "SKIPPED"])

    def test_linked_trade_is_marked_as_user_reported_not_broker_verified(self):
        setup_id = self.make_setup()
        trade_id = log_trade(
            "XAUUSD", "Buy", 100.0, 98.0, 104.0, setup_id=setup_id,
            simulation_plan={"risk_amount": 0.2},
        )
        row = get_signal_ledger(10)[0]
        self.assertEqual(row["tracking_action"], "TRADE_LOGGED")
        self.assertEqual(row["linked_trade_id"], trade_id)
        self.assertIn("not independently verified", row["tracking_reason"])

    def test_same_bar_stop_and_target_is_recorded_as_modeled_stop(self):
        setup_id = self.make_setup()
        self.add_bars(
            ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"],
            [
                [100.0, 101.0, 99.0, 100.0, 1.0],
                [100.0, 105.0, 97.0, 101.0, 1.0],
            ],
        )
        result = refresh_setup_outcomes(
            "TEST-SOURCE", now="2026-01-01T02:00:00Z", limit=10
        )
        row = get_signal_ledger(10)[0]
        self.assertEqual(result["terminal"], 1)
        self.assertEqual(row["modeled_status"], "STOP_LOSS")
        self.assertEqual(row["modeled_outcome"], "stop_loss")
        self.assertAlmostEqual(row["modeled_gross_r"], -1.0)
        self.assertIn("intrabar path is unknown", row["modeled_notes"])

    def test_outcome_remains_pending_until_entry_window_is_observed(self):
        self.make_setup(entry=95.0)
        self.add_bars(
            ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"],
            [
                [101.0, 102.0, 100.0, 101.0, 1.0],
                [101.0, 102.0, 100.0, 101.0, 1.0],
            ],
        )
        refresh_setup_outcomes("TEST-SOURCE", now="2026-01-01T01:00:00Z", limit=10)
        row = get_signal_ledger(10)[0]
        self.assertEqual(row["modeled_status"], "PENDING_ENTRY")
        self.assertEqual(row["modeled_outcome"], "unfilled")

    def test_unfilled_entry_becomes_terminal_after_four_closed_bars(self):
        self.make_setup(entry=95.0)
        self.add_bars(
            [f"2026-01-01T00:{minute:02d}:00Z" for minute in (0, 15, 30, 45)],
            [[101.0, 102.0, 100.0, 101.0, 1.0] for _ in range(4)],
        )
        refresh_setup_outcomes("TEST-SOURCE", now="2026-01-01T02:00:00Z", limit=10)
        row = get_signal_ledger(10)[0]
        self.assertEqual(row["modeled_status"], "UNFILLED")

    def test_existing_setup_trade_is_backfilled_into_action_ledger(self):
        setup_id = self.make_setup()
        connection = get_connection()
        connection.execute("DELETE FROM setup_action_log WHERE setup_id=?", (setup_id,))
        connection.execute(
            "INSERT INTO trades (symbol, setup_id) VALUES ('XAUUSD', ?)", (setup_id,)
        )
        connection.commit()
        connection.close()

        init_db()
        row = get_signal_ledger(10)[0]
        self.assertEqual(row["tracking_action"], "TRADE_LOGGED")
        self.assertIn("Existing linked journal trade", row["tracking_reason"])


if __name__ == "__main__":
    unittest.main()
