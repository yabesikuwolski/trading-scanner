import argparse

from database.db_manager import init_db
from scanner.csv_market_data import import_ohlc_csv


def main():
    parser = argparse.ArgumentParser(description="Import broker OHLC candles from CSV")
    parser.add_argument("csv_path", help="Path to the exported CSV file")
    parser.add_argument("--symbol", required=True, help="Instrument symbol, e.g. XAUUSD")
    parser.add_argument("--timeframe", required=True, help="Candle timeframe, e.g. H1 or M15")
    parser.add_argument("--source", required=True, help="Broker/feed label for provenance")
    parser.add_argument(
        "--timezone",
        help="Required for timestamps without an explicit UTC offset, e.g. Europe/Athens",
    )
    args = parser.parse_args()

    init_db()
    bars, saved_count = import_ohlc_csv(
        args.csv_path,
        args.symbol,
        args.timeframe,
        args.source,
        args.timezone,
    )
    print(
        f"Imported {saved_count} {args.source} {args.symbol.upper()} "
        f"{args.timeframe.upper()} bars ({bars.index.min()} to {bars.index.max()})"
    )


if __name__ == "__main__":
    main()