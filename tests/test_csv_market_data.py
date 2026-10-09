import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import pandas as pd
from database.db_manager import init_db
from scanner.csv_market_data import (
    import_ohlc_csv,
    load_market_bars,
    normalize_ohlc_csv,
    store_market_bars,
)


class CsvMarketDataTests(unittest.TestCase):
    def test_imports_tradingview_time_column_export(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "tradingview_oanda_xauusd_h1.csv"
            csv_path.write_text(
                "time,open,high,low,close,volume\n"
                "2026-09-29T08:00:00Z,4145.665,4150.755,4143.100,4149.600,120\n"
                "2026-09-29T07:00:00Z,4150.000,4152.000,4140.000,4145.665,98\n",
                encoding="utf-8",
            )

            bars = normalize_ohlc_csv(
                csv_path, "OANDA:XAUUSD", "H1", "TradingView OANDA"
            )

        self.assertEqual(len(bars), 2)
        self.assertTrue(bars.index.is_monotonic_increasing)
        self.assertEqual(bars.index[-1].isoformat(), "2026-09-29T08:00:00+00:00")
        self.assertEqual(bars.iloc[-1]["Close"], 4149.6)
        self.assertEqual(bars.iloc[-1]["symbol"], "OANDA:XAUUSD")

    def test_imports_semicolon_mt5_export_and_converts_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "broker_export.csv"
            csv_path.write_text(
                "<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<TICKVOL>;<VOL>\n"
                "2026.09.28;10:00:00;4000,0;4010,0;3990,0;4005,0;25;0\n"
                "2026.09.28;11:00:00;4005,0;4020,0;4000,0;4015,0;30;0\n",
                encoding="utf-8",
            )

            bars = normalize_ohlc_csv(
                csv_path, "xauusd", "h1", "HFM", "Europe/Athens"
            )

        self.assertEqual(list(bars.columns), [
            "source", "symbol", "timeframe", "Open", "High", "Low", "Close", "Volume"
        ])
        self.assertEqual(bars.index[0].isoformat(), "2026-09-28T07:00:00+00:00")
        self.assertEqual(bars.iloc[0]["Volume"], 25)
        self.assertEqual(bars.iloc[0]["symbol"], "XAUUSD")

    def test_naive_timestamps_require_explicit_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "broker_export.csv"
            csv_path.write_text(
                "datetime,open,high,low,close\n"
                "2026-09-28 10:00:00,4000,4010,3990,4005\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "specify the broker timezone"):
                normalize_ohlc_csv(csv_path, "XAUUSD", "H1", "broker")

    def test_rejects_inconsistent_ohlc_data(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "bad.csv"
            csv_path.write_text(
                "timestamp,open,high,low,close\n"
                "2026-09-28T10:00:00Z,4000,3990,3980,4005\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "inconsistent high/low"):
                normalize_ohlc_csv(csv_path, "XAUUSD", "H1", "broker")

    def test_import_is_idempotent_and_keeps_sources_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            database_path = directory / "market.db"
            csv_path = directory / "bars.csv"
            csv_path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2026-09-28T10:00:00Z,4000,4010,3990,4005,12\n",
                encoding="utf-8",
            )

            with patch.object(config, "DB_PATH", str(database_path)):
                init_db()
                import_ohlc_csv(csv_path, "XAUUSD", "H1", "HFM")
                import_ohlc_csv(csv_path, "XAUUSD", "H1", "HFM")
                import_ohlc_csv(csv_path, "XAUUSD", "H1", "Deriv")
                hfm_bars = load_market_bars("hfm", "XAUUSD", "H1")
                deriv_bars = load_market_bars("Deriv", "XAUUSD", "H1")

            self.assertEqual(len(hfm_bars), 1)
            self.assertEqual(len(deriv_bars), 1)
            self.assertEqual(hfm_bars.iloc[0]["Close"], 4005)
            self.assertTrue(hfm_bars.index.is_monotonic_increasing)

    def test_live_bar_storage_normalizes_timezone_and_updates_existing_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "market.db"
            local_index = pd.date_range(
                "2026-09-28T10:00:00+02:00", periods=1, freq="1h"
            )
            live_bars = pd.DataFrame({
                "Open": [4000.0],
                "High": [4010.0],
                "Low": [3990.0],
                "Close": [4005.0],
                "Volume": [12.0],
            }, index=local_index)

            with patch.object(config, "DB_PATH", str(database_path)):
                init_db()
                store_market_bars(live_bars, "xauusd", "h1", "biquote")
                live_bars.loc[:, "Close"] = 4007.0
                store_market_bars(live_bars, "XAUUSD", "H1", "BIQUOTE")
                archived = load_market_bars("BIQUOTE", "XAUUSD", "H1")

            self.assertEqual(len(archived), 1)
            self.assertEqual(
                archived.index[0].isoformat(), "2026-09-28T08:00:00+00:00"
            )
            self.assertEqual(archived.iloc[0]["Close"], 4007.0)


if __name__ == "__main__":
    unittest.main()