import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import config
from database.db_manager import (
    close_trade,
    get_connection,
    get_recent_losses,
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

    def test_close_trade_derives_gross_r_and_mfe_mae_from_archived_bars(self):
        plan = {"risk_amount": 0.20, "position_size": 0.01, "sizing_status": "OK"}
        trade_id = log_trade(
            "XAUUSD", "Buy", 100, 98, 110, tp2=112, simulation_plan=plan
        )
        start = "2024-01-01T00:00:00+00:00"
        connection = get_connection()
        connection.execute(
            "UPDATE trades SET opened_at=?, entry_triggered_at=? WHERE id=?",
            (start, start, trade_id),
        )
        connection.executemany("""
            INSERT INTO market_bars (
                source, symbol, timeframe, bar_time, open, high, low, close, volume
            ) VALUES (?, ?, 'M15', ?, 100, ?, ?, ?, 1)
        """, [
            (config.MARKET_DATA_SOURCE_LABEL, "XAUUSD", "2024-01-01T00:00:00+00:00", 103, 99, 102),
            (config.MARKET_DATA_SOURCE_LABEL, "XAUUSD", "2024-01-01T00:15:00+00:00", 111, 100, 109),
            (config.MARKET_DATA_SOURCE_LABEL, "XAUUSD", "2024-01-01T00:30:00+00:00", 113, 108, 112),
        ])
        connection.commit()
        connection.close()

        close_trade(
            trade_id, 110, "win", notes="test", exit_reason="TP1",
            closed_at="2024-01-01T00:45:00+00:00",
        )
        connection = get_connection()
        trade = connection.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        connection.close()

        self.assertAlmostEqual(trade["gross_r_multiple"], 5.0)
        self.assertIsNone(trade["net_r_multiple"])
        self.assertAlmostEqual(trade["mfe_price"], 13.0)
        self.assertAlmostEqual(trade["mae_price"], 1.0)
        self.assertAlmostEqual(trade["mfe_r"], 6.5)
        self.assertAlmostEqual(trade["mae_r"], 0.5)
        self.assertEqual(trade["tp1_reached"], 1)
        self.assertEqual(trade["tp2_reached"], 1)
        self.assertEqual(trade["stop_reached"], 0)
        self.assertEqual(trade["favorable_close_minutes"], 45)
        self.assertIn("intrabar path", trade["excursion_source"])
        self.assertEqual(trade["exit_reason"], "TP1")

    def test_reported_trade_costs_calculate_net_r_and_do_not_change_simulation_account(self):
        plan = {"risk_amount": 0.20, "position_size": 0.01, "sizing_status": "OK"}
        trade_id = log_trade(
            "XAUUSD", "Buy", 100, 98, 110, simulation_plan=plan,
            execution_mode="MANUAL_REPORTED", entry_triggered_at="2024-01-01T03:00:00+03:00",
            position_size=0.5, actual_risk_amount=100, risk_currency="usd",
            transaction_cost_amount=5, cost_currency="USD",
        )
        close_trade(trade_id, 104, "win")

        connection = get_connection()
        trade = connection.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        connection.close()
        account = get_simulation_performance()

        self.assertEqual(trade["execution_mode"], "MANUAL_REPORTED")
        self.assertEqual(trade["entry_triggered_at"], "2024-01-01T00:00:00+00:00")
        self.assertAlmostEqual(trade["gross_r_multiple"], 2.0)
        self.assertAlmostEqual(trade["net_r_multiple"], 1.95)
        self.assertEqual(trade["position_size"], 0.5)
        self.assertEqual(trade["risk_currency"], "USD")
        self.assertEqual(trade["transaction_cost_amount"], 5)
        self.assertAlmostEqual(account["current_balance"], 10.0)
        self.assertEqual(account["wins"], 0)
        self.assertEqual(account["losses"], 0)
        self.assertEqual(get_recent_losses(), [])

    def test_same_currency_costs_reduce_paper_simulation_pnl(self):
        plan = {"risk_amount": 0.20, "position_size": None, "sizing_status": "BELOW_BROKER_MINIMUM"}
        trade_id = log_trade(
            "XAUUSD", "Buy", 100, 98, 104, simulation_plan=plan,
            transaction_cost_amount=0.05, cost_currency="USD",
        )
        close_trade(trade_id, 98, "loss")

        account = get_simulation_performance()
        connection = get_connection()
        trade = connection.execute(
            "SELECT simulation_pnl FROM trades WHERE id=?", (trade_id,),
        ).fetchone()
        connection.close()
        self.assertAlmostEqual(trade["simulation_pnl"], -0.25)
        self.assertAlmostEqual(account["current_balance"], 9.75)

    def test_net_r_stays_unknown_when_risk_and_cost_currencies_differ(self):
        trade_id = log_trade(
            "XAUUSD", "Buy", 100, 98, 104,
            execution_mode="MANUAL_REPORTED", actual_risk_amount=100,
            risk_currency="USD", transaction_cost_amount=5, cost_currency="EUR",
        )
        close_trade(trade_id, 104, "win")
        connection = get_connection()
        trade = connection.execute(
            "SELECT gross_r_multiple, net_r_multiple, transaction_cost_amount, cost_currency "
            "FROM trades WHERE id=?", (trade_id,),
        ).fetchone()
        connection.close()

        self.assertAlmostEqual(trade["gross_r_multiple"], 2.0)
        self.assertIsNone(trade["net_r_multiple"])
        self.assertEqual(trade["transaction_cost_amount"], 5)
        self.assertEqual(trade["cost_currency"], "EUR")

    def test_reported_trade_metadata_requires_amount_and_currency_pairs(self):
        with self.assertRaisesRegex(ValueError, "both actual risk amount and its currency"):
            log_trade(
                "XAUUSD", "Buy", 100, 98, 104,
                execution_mode="MANUAL_REPORTED", actual_risk_amount=50,
            )

    def test_close_trade_rejects_outcome_label_that_conflicts_with_exit_price(self):
        trade_id = log_trade("XAUUSD", "Buy", 100, 98, 104)
        with self.assertRaisesRegex(ValueError, "losing trade"):
            close_trade(trade_id, 103, "loss")

    def test_close_trade_leaves_excursions_unknown_without_archived_bars(self):
        trade_id = log_trade("XAUUSD", "Buy", 100, 98, 104)
        close_trade(trade_id, 104, "win")
        connection = get_connection()
        trade = connection.execute("SELECT mfe_r, mae_r, excursion_source FROM trades WHERE id=?", (trade_id,)).fetchone()
        connection.close()
        self.assertIsNone(trade["mfe_r"])
        self.assertIsNone(trade["mae_r"])
        self.assertIsNone(trade["excursion_source"])

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
        with patch.object(config, "DB_PATH", legacy_path):
            connection = get_connection()
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(trades)")}
            connection.close()
        self.assertIn("execution_mode", columns)
        self.assertIn("transaction_cost_amount", columns)


if __name__ == "__main__":
    unittest.main()
