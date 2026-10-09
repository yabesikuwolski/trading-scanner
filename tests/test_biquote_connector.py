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


if __name__ == "__main__":
    unittest.main()