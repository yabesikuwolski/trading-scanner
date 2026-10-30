import unittest
from datetime import datetime, timezone

import pandas as pd

from main import _valid_frame


class MainMarketFreshnessTests(unittest.TestCase):
    def _biquote_bar(self, open_time):
        frame = pd.DataFrame(
            {"Open": [4000.0], "High": [4010.0], "Low": [3990.0], "Close": [4005.0]},
            index=pd.DatetimeIndex([open_time]),
        )
        frame.attrs.update(provider="BIQUOTE", closed_verified=True)
        return frame

    def test_recently_closed_h4_is_measured_from_close_not_open(self):
        now = datetime(2026, 10, 22, 9, 49, tzinfo=timezone.utc)
        last_closed = self._biquote_bar(datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc))

        valid, reason = _valid_frame(last_closed, "XAUUSD", "H4", now=now)

        self.assertTrue(valid, reason)
        self.assertIsNone(reason)

    def test_h4_becomes_stale_after_close_age_exceeds_timeframe_plus_tolerance(self):
        now = datetime(2026, 10, 22, 12, 31, tzinfo=timezone.utc)
        last_closed = self._biquote_bar(datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc))

        valid, reason = _valid_frame(last_closed, "XAUUSD", "H4", now=now)

        self.assertFalse(valid)
        self.assertEqual(reason, "stale H4 candles")

    def test_h4_current_open_candle_is_not_accepted_as_completed(self):
        now = datetime(2026, 10, 22, 9, 49, tzinfo=timezone.utc)
        currently_open = self._biquote_bar(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc))

        valid, reason = _valid_frame(currently_open, "XAUUSD", "H4", now=now)

        self.assertFalse(valid)
        self.assertEqual(reason, "incomplete H4 candle")

    def test_missing_h4_data_is_rejected(self):
        valid, reason = _valid_frame(None, "XAUUSD", "H4")

        self.assertFalse(valid)
        self.assertEqual(reason, "missing candles")


if __name__ == "__main__":
    unittest.main()
