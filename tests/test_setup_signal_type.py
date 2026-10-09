import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from database.db_manager import (
    get_active_setups, get_trade_for_setup, init_db, log_trade,
    mark_setup_reviewed, save_setup,
)


OLD_SETUPS_SCHEMA = """
CREATE TABLE setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    bias TEXT,
    grade TEXT,
    score INTEGER,
    conditions TEXT,
    entry REAL,
    sl REAL,
    tp1 REAL,
    tp2 REAL,
    session TEXT,
    chart_path TEXT
)
"""


class SetupSignalTypeTests(unittest.TestCase):
    def save_signal_setup(self, database_path):
        with patch.object(config, "DB_PATH", str(database_path)):
            init_db()
            save_setup(
                "XAUUSD",
                "M15",
                {
                    "bias": "bullish",
                    "signal": {"type": "BUY LIMIT"},
                    "conditions": ["FVG"],
                    "levels": {
                        "entry": 2000.0,
                        "sl": 1990.0,
                        "tp1": 2020.0,
                        "tp2": 2030.0,
                    },
                },
                {"grade": "A", "score": 7},
            )
            return get_active_setups()

    def test_fresh_database_persists_signal_type(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = self.save_signal_setup(Path(directory) / "fresh.db")

        self.assertEqual(rows[0]["signal_type"], "BUY LIMIT")

    def test_existing_database_is_migrated_and_persists_signal_type(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "existing.db"
            connection = sqlite3.connect(database_path)
            connection.execute(OLD_SETUPS_SCHEMA)
            connection.commit()
            connection.close()

            rows = self.save_signal_setup(database_path)

        self.assertEqual(rows[0]["signal_type"], "BUY LIMIT")

    def test_reviewed_state_is_persisted_in_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviewed.db"
            with patch.object(config, "DB_PATH", str(database_path)):
                init_db()
                save_setup(
                    "XAUUSD",
                    "M15",
                    {
                        "bias": "bullish",
                        "signal": {"type": "BUY LIMIT"},
                        "conditions": ["FVG"],
                        "levels": {"entry": 2000.0, "sl": 1990.0, "tp1": 2020.0, "tp2": 2030.0},
                    },
                    {"grade": "A", "score": 7},
                )
                rows = get_active_setups()
                mark_setup_reviewed(rows[0]["id"])
                persisted = get_active_setups()[0]

        self.assertIsNotNone(persisted["reviewed_at"])
        self.assertEqual(persisted["lifecycle_state"], "REVIEWED")

    def test_ai_review_is_persisted_in_setup_record(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "ai_review.db"
            with patch.object(config, "DB_PATH", str(database_path)):
                init_db()
                save_setup(
                    "XAUUSD",
                    "M15",
                    {
                        "bias": "bullish",
                        "signal": {"type": "BUY LIMIT"},
                        "conditions": ["FVG"],
                        "levels": {"entry": 2000.0, "sl": 1990.0, "tp1": 2020.0, "tp2": 2030.0},
                    },
                    {"grade": "A", "score": 7},
                    ai_review={
                        "decision": "WATCH",
                        "quality_score": 72,
                        "confidence": "MEDIUM",
                        "summary": "Solid but needs more confirmation.",
                        "reasons": ["Structure holds"],
                        "invalidations": ["Needs confirmation"],
                        "risk_note": "Moderate risk",
                    },
                )
                persisted = get_active_setups()[0]

        self.assertEqual(persisted["ai_decision"], "WATCH")
        self.assertEqual(persisted["ai_quality_score"], 72)
        self.assertEqual(persisted["ai_confidence"], "MEDIUM")
        self.assertIn("Solid", persisted["ai_summary"])

    def test_trade_from_setup_is_linked_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "linked_trade.db"
            with patch.object(config, "DB_PATH", str(database_path)):
                init_db()
                save_setup(
                    "XAUUSD",
                    "M15",
                    {
                        "bias": "bullish",
                        "signal": {"type": "BUY LIMIT"},
                        "conditions": ["FVG"],
                        "levels": {"entry": 2000.0, "sl": 1990.0, "tp1": 2020.0, "tp2": 2030.0},
                    },
                    {"grade": "A", "score": 7},
                )
                setup = get_active_setups()[0]
                trade_id = log_trade(
                    "XAUUSD", "Buy", 2000.0, 1990.0, 2020.0,
                    grade="A", score=7, setup_id=setup["id"], notes="manual fill",
                )
                trade = get_trade_for_setup(setup["id"])

        self.assertEqual(trade["id"], trade_id)
        self.assertEqual(trade["notes"], "manual fill")


if __name__ == "__main__":
    unittest.main()