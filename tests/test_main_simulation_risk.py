import unittest
from unittest.mock import Mock, patch

import config
from main import scan_once


class MainSimulationRiskTests(unittest.TestCase):
    @patch("main.log_risk")
    @patch("main.get_simulation_performance")
    @patch("main.save_broker_account_snapshot")
    @patch("main.get_account_info")
    def test_active_risk_gate_uses_simulation_equity_not_broker_balance(
        self, get_account_info, save_broker_snapshot, get_simulation, _log_risk
    ):
        get_account_info.return_value = {
            "balance": 10000.0,
            "equity": 10000.0,
            "account_type": "demo",
            "currency": "USD",
        }
        get_simulation.return_value = {
            "starting_balance": 10.0,
            "current_balance": 9.8,
            "equity": 9.8,
            "realized_pnl": -0.2,
            "daily_start_balance": 10.0,
            "weekly_start_balance": 10.0,
        }
        risk_manager = Mock()
        risk_manager.check_risk.return_value = {
            "allowed": True,
            "violations": [],
            "warnings": [],
            "daily_drawdown": 2.0,
            "weekly_drawdown": 2.0,
        }

        with patch.object(config, "SYMBOLS", []):
            scan_once(risk_manager)

        risk_manager.check_risk.assert_called_once_with(
            9.8, 9.8, daily_start=10.0, weekly_start=10.0
        )
        save_broker_snapshot.assert_called_once_with(get_account_info.return_value)


if __name__ == "__main__":
    unittest.main()
