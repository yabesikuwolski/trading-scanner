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
        now = pd.Timestamp.now(tz="UTC")
        frames = {}
        for timeframe, duration in {"M5": 5, "H4": 240, "H1": 60, "M15": 15}.items():
            frame = pd.DataFrame(
                {
                    "Open": [100.0],
                    "High": [101.0],
                    "Low": [99.0],
                    "Close": [100.5],
                    "Volume": [1.0],
                },
                index=pd.DatetimeIndex([
                    now - pd.Timedelta(minutes=duration + 5)
                ]),
            )
            frame.attrs.update(provider="BIQUOTE", closed_verified=True)
            frames[timeframe] = frame
        mock_get_bars.side_effect = lambda _symbol, timeframe, _count: frames[timeframe]
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

        self.assertEqual(mock_get_bars.call_count, 4)
        self.assertEqual(mock_store.call_count, 4)
        self.assertEqual(
            [call.args[2] for call in mock_store.call_args_list],
            ["M5", "H4", "H1", "M15"],
        )
        self.assertTrue(all(
            call.args[3] == config.MARKET_DATA_SOURCE_LABEL
            for call in mock_store.call_args_list
        ))
        risk_manager.check_risk.assert_called_once()


if __name__ == "__main__":
    unittest.main()
