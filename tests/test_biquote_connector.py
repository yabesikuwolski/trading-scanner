import unittest
from unittest.mock import Mock, patch

import config
from scanner.mt5_connector import get_bars


class BiQuoteConnectorTests(unittest.TestCase):
    @patch("scanner.mt5_connector.requests.get")
    def test_bars_are_normalized_oldest_to_newest(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "bars": [
                {
                    "openTime": "2026-09-29T08:30:00Z",
                    "open": 3,
                    "high": 4,
                    "low": 2,
                    "close": 3.5,
                    "volume": 0,
                    "tickVolume": 30,
                },
                {
                    "openTime": "2026-09-29T08:15:00Z",
                    "open": 2,
                    "high": 3,
                    "low": 1,
                    "close": 2.5,
                    "volume": 0,
                    "tickVolume": 20,
                },
                {
                    "openTime": "2026-09-29T08:00:00Z",
                    "open": 1,
                    "high": 2,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 0,
                    "tickVolume": 10,
                },
            ]
        }
        mock_get.return_value = response

        with patch.object(config, "BIQUOTE_BASE_URL", "https://biquote.io/api"):
            bars = get_bars("XAUUSD", "M15", 2)

        self.assertTrue(bars.index.is_monotonic_increasing)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars.iloc[-1]["Close"], 3.5)
        self.assertEqual(bars.iloc[-1]["Volume"], 30)

    @patch("scanner.mt5_connector.requests.get")
    def test_short_provider_response_is_preserved(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "bars": [{
                "openTime": "2026-09-29T08:00:00Z",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 0,
                "tickVolume": 10,
            }]
        }
        mock_get.return_value = response

        with patch.object(config, "BIQUOTE_BASE_URL", "https://biquote.io/api"):
            bars = get_bars("XAUUSD", "M15", 5)

        self.assertEqual(len(bars), 1)

    @patch("scanner.mt5_connector.requests.get")
    def test_h4_uses_four_hour_utc_bars_and_drops_the_open_candle(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "bars": [
                {
                    "openTime": "2026-10-22T08:00:00Z",
                    "isOpen": True,
                    "open": 4088, "high": 4095, "low": 4080, "close": 4090,
                    "tickVolume": 100,
                },
                {
                    "openTime": "2026-10-22T04:00:00Z",
                    "isOpen": False,
                    "open": 4092, "high": 4103, "low": 4066, "close": 4088,
                    "tickVolume": 200,
                },
                {
                    "openTime": "2026-10-22T00:00:00Z",
                    "isOpen": False,
                    "open": 4125, "high": 4127, "low": 4089, "close": 4092,
                    "tickVolume": 300,
                },
            ]
        }
        mock_get.return_value = response

        bars = get_bars("XAUUSD", "H4", 3)

        self.assertIn("interval=4h", mock_get.call_args.args[0])
        self.assertEqual(str(bars.index[-1]), "2026-10-22 04:00:00+00:00")
        self.assertEqual(len(bars), 2)
        self.assertTrue(bars.attrs["closed_verified"])
        self.assertTrue(bars.index.is_monotonic_increasing)

    @patch("scanner.mt5_connector.requests.get")
    def test_m5_uses_five_minute_utc_bars_and_drops_the_open_candle(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "bars": [
                {
                    "openTime": "2026-10-22T10:10:00Z",
                    "isOpen": True,
                    "open": 4088, "high": 4095, "low": 4080, "close": 4090,
                    "tickVolume": 100,
                },
                {
                    "openTime": "2026-10-22T10:05:00Z",
                    "isOpen": False,
                    "open": 4092, "high": 4103, "low": 4066, "close": 4088,
                    "tickVolume": 200,
                },
            ]
        }
        mock_get.return_value = response

        bars = get_bars("XAUUSD", "M5", 2)

        self.assertIn("interval=5m", mock_get.call_args.args[0])
        self.assertEqual(str(bars.index[-1]), "2026-10-22 10:05:00+00:00")
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars.attrs["closed_verified"])


if __name__ == "__main__":
    unittest.main()
