import unittest
from unittest.mock import Mock, patch

import pandas as pd

import config
from main import scan_once


class LiveMarketArchiveTests(unittest.TestCase):
    @patch("main.log_risk")
    @patch("main.store_market_bars")
    @patch("main.get_bars")
    @patch("main.get_account_info", return_value={})
    def test_archives_fetched_timeframes_even_when_risk_blocks_scan(
        self, _account, mock_get_bars, mock_store, _log_risk
    ):
        frame = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1.0],
            },
            index=pd.date_range("2026-09-29T10:00:00Z", periods=1, freq="15min"),
        )
        mock_get_bars.return_value = frame
        risk_manager = Mock()
        risk_manager.check_risk.return_value = {
            "allowed": False,
            "violations": ["test block"],
            "warnings": [],
        }

        with (
            patch.object(config, "SYMBOLS", ["XAUUSD"]),
            patch.object(config, "HTF", "H4"),
            patch.object(config, "MTF", "H1"),
            patch.object(config, "LTF", "M15"),
        ):
            scan_once(risk_manager)

        self.assertEqual(mock_get_bars.call_count, 3)
        self.assertEqual(mock_store.call_count, 3)
        self.assertEqual(
            [call.args[2] for call in mock_store.call_args_list],
            ["H4", "H1", "M15"],
        )
        self.assertTrue(all(call.args[3] == "BIQUOTE" for call in mock_store.call_args_list))
        risk_manager.check_risk.assert_called_once()


if __name__ == "__main__":
    unittest.main()