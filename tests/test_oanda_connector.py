import unittest
from unittest.mock import Mock

import requests

from scanner.oanda_connector import archive_history, get_bars


def candle(time, complete, opening, high, low, close, volume):
    return {
        "time": time,
        "complete": complete,
        "volume": volume,
        "mid": {
            "o": str(opening),
            "h": str(high),
            "l": str(low),
            "c": str(close),
        },
    }


class OandaConnectorTests(unittest.TestCase):
    def test_fetches_midpoint_candles_and_omits_open_candle(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"candles": [
            candle("2026-09-29T08:15:00Z", False, 2, 3, 1, 2.5, 20),
            candle("2026-09-29T08:00:00Z", True, 1, 2, 0.5, 1.5, 10),
        ]}
        session.get.return_value = response

        bars = get_bars("M15", 2, token="local-test-token", session=session)

        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars.index.is_monotonic_increasing)
        self.assertEqual(bars.iloc[0]["Close"], 1.5)
        self.assertEqual(bars.iloc[0]["Volume"], 10)
        args, kwargs = session.get.call_args
        self.assertTrue(args[0].startswith("https://api-fxpractice.oanda.com/v3/"))
        self.assertEqual(kwargs["params"], {"granularity": "M15", "count": 2, "price": "M"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer local-test-token")

    def test_get_bars_adds_to_timestamp_when_paging(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"candles": [
            candle("2026-09-29T08:00:00Z", True, 1, 2, 0.5, 1.5, 10),
        ]}
        session.get.return_value = response

        get_bars(
            "M15",
            count=10,
            token="local-test-token",
            session=session,
            to_time="2026-09-29T08:00:00Z",
        )

        self.assertEqual(
            session.get.call_args.kwargs["params"]["to"],
            "2026-09-29T08:00:00Z",
        )

    def test_archive_history_pages_backward_and_deduplicates(self):
        session = Mock()
        first_page = Mock()
        first_page.json.return_value = {"candles": [
            candle("2026-01-01T00:30:00Z", True, 3, 4, 2, 3.5, 30),
            candle("2026-01-01T00:15:00Z", True, 2, 3, 1, 2.5, 20),
        ]}
        second_page = Mock()
        second_page.json.return_value = {"candles": [
            candle("2026-01-01T00:15:00Z", True, 2, 3, 1, 2.5, 20),
            candle("2026-01-01T00:00:00Z", True, 1, 2, 0.5, 1.5, 10),
        ]}
        session.get.side_effect = [first_page, second_page]

        bars, saved_count = archive_history(
            "M15",
            start_time="2026-01-01T00:00:00Z",
            page_size=2,
            token="local-test-token",
            session=session,
        )

        self.assertEqual(len(bars), 3)
        self.assertEqual(saved_count, 3)
        self.assertTrue(bars.index.is_monotonic_increasing)
        self.assertEqual(bars.iloc[0]["Close"], 1.5)
        self.assertEqual(bars.iloc[-1]["Close"], 3.5)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"]["to"],
            "2026-01-01T00:15:00Z",
        )

    def test_rejects_unsupported_timeframe_and_count(self):
        session = Mock()
        with self.assertRaises(ValueError):
            get_bars("M1", token="local-test-token", session=session)
        with self.assertRaises(ValueError):
            get_bars("H1", count=5001, token="local-test-token", session=session)
        session.get.assert_not_called()

    def test_missing_token_fails_without_request(self):
        session = Mock()
        with unittest.mock.patch("scanner.oanda_connector.config.OANDA_API_TOKEN", ""):
            with self.assertRaisesRegex(RuntimeError, "OANDA_API_TOKEN"):
                get_bars("H1", session=session)
        session.get.assert_not_called()

    def test_http_error_does_not_echo_request_headers(self):
        session = Mock()
        response = Mock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        session.get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as context:
            get_bars("H1", token="do-not-print-this", session=session)

        self.assertNotIn("do-not-print-this", str(context.exception))


if __name__ == "__main__":
    unittest.main()