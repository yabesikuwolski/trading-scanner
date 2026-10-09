import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import config
from database.db_manager import (
    close_trade,
    get_simulation_performance,
    init_db,
    log_trade,
)


class SimulationAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "simulation.sqlite3")
        self.db_path_patch = patch.object(config, "DB_PATH", self.db_path)
        self.starting_balance_patch = patch.object(config, "SIMULATION_ACCOUNT_BALANCE", 10.0)
        self.db_path_patch.start()
        self.starting_balance_patch.start()
        init_db()

    def tearDown(self):
        self.starting_balance_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_losing_trade_updates_only_simulation_equity_by_planned_risk(self):
        plan = {"risk_amount": 0.20, "position_size": None, "sizing_status": "BELOW_BROKER_MINIMUM"}
        trade_id = log_trade("XAUUSD", "Buy", 4200, 4195, 4210, simulation_plan=plan)
        close_trade(trade_id, 4195, "loss", rr_achieved=-1.0)

        account = get_simulation_performance()
        self.assertEqual(account["starting_balance"], 10.0)
        self.assertAlmostEqual(account["current_balance"], 9.80)
        self.assertAlmostEqual(account["realized_pnl"], -0.20)
        self.assertEqual(account["wins"], 0)
        self.assertEqual(account["losses"], 1)
        self.assertAlmostEqual(account["max_drawdown"], 2.0)

    def test_two_r_win_updates_simulation_equity_by_two_times_risk(self):
        plan = {"risk_amount": 0.20, "position_size": None, "sizing_status": "BELOW_BROKER_MINIMUM"}
        trade_id = log_trade("XAUUSD", "Sell", 4200, 4205, 4190, simulation_plan=plan)
        close_trade(trade_id, 4190, "win", rr_achieved=0.0)

        account = get_simulation_performance()
        self.assertAlmostEqual(account["current_balance"], 10.40)
        self.assertAlmostEqual(account["realized_pnl"], 0.40)
        self.assertEqual(account["wins"], 1)
        self.assertEqual(account["losses"], 0)

    def test_reclosing_trade_does_not_apply_simulated_pnl_twice(self):
        plan = {"risk_amount": 0.20, "position_size": None, "sizing_status": "BELOW_BROKER_MINIMUM"}
        trade_id = log_trade("XAUUSD", "Buy", 4200, 4195, 4210, simulation_plan=plan)
        close_trade(trade_id, 4195, "loss", rr_achieved=-1.0)
        close_trade(trade_id, 4195, "loss", rr_achieved=-1.0)

        account = get_simulation_performance()
        self.assertAlmostEqual(account["current_balance"], 9.80)
        self.assertEqual(account["losses"], 1)

    def test_configured_starting_balance_rebases_equity_preserving_realized_pnl(self):
        plan = {"risk_amount": 0.20, "position_size": None, "sizing_status": "BELOW_BROKER_MINIMUM"}
        trade_id = log_trade("XAUUSD", "Buy", 4200, 4195, 4210, simulation_plan=plan)
        close_trade(trade_id, 4195, "loss", rr_achieved=-1.0)

        with patch.object(config, "SIMULATION_ACCOUNT_BALANCE", 20.0):
            account = get_simulation_performance()

        self.assertEqual(account["starting_balance"], 20.0)
        self.assertAlmostEqual(account["current_balance"], 19.80)
        self.assertAlmostEqual(account["realized_pnl"], -0.20)

    def test_existing_database_schema_migrates_without_losing_trade_tables(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        with patch.object(config, "DB_PATH", legacy_path):
            connection = sqlite3.connect(legacy_path)
            connection.executescript("""
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT,
                    setup_id INTEGER,
                    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    session TEXT,
                    grade TEXT,
                    score INTEGER,
                    entry REAL,
                    sl REAL,
                    tp REAL,
                    exit_price REAL,
                    outcome TEXT,
                    rr_achieved REAL,
                    notes TEXT,
                    chart_path TEXT
                );
                CREATE TABLE risk_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    balance REAL,
                    equity REAL,
                    daily_dd REAL,
                    weekly_dd REAL,
                    consecutive_losses INTEGER,
                    trading_allowed INTEGER
                );
            """)
            connection.commit()
            connection.close()

            init_db()
            account = get_simulation_performance()

        self.assertEqual(account["starting_balance"], 10.0)
        self.assertEqual(account["current_balance"], 10.0)


if __name__ == "__main__":
    unittest.main()
