import argparse

import pandas as pd
import requests

import config
from database.db_manager import init_db, save_market_bars


GRANULARITY_MAP = {"M15": "M15", "H1": "H1", "H4": "H4"}
OANDA_INSTRUMENT = "XAU_USD"
OANDA_SOURCE = "OANDA-PRACTICE"


def _format_api_time(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _bars_from_candles(candles):
    complete_candles = [candle for candle in candles if candle.get("complete") is True]
    if not complete_candles:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    bars = pd.DataFrame({
        "time": [candle["time"] for candle in complete_candles],
        "Open": [float(candle["mid"]["o"]) for candle in complete_candles],
        "High": [float(candle["mid"]["h"]) for candle in complete_candles],
        "Low": [float(candle["mid"]["l"]) for candle in complete_candles],
        "Close": [float(candle["mid"]["c"]) for candle in complete_candles],
        "Volume": [int(candle["volume"]) for candle in complete_candles],
    })
    bars["time"] = pd.to_datetime(bars["time"], errors="coerce", utc=True)
    bars = bars.dropna(subset=["time"]).set_index("time").sort_index()
    bars = bars.loc[~bars.index.duplicated(keep="last")]
    return bars[["Open", "High", "Low", "Close", "Volume"]]


def get_bars(timeframe, count=200, token=None, session=requests, to_time=None):
    timeframe = timeframe.upper()
    if timeframe not in GRANULARITY_MAP:
        raise ValueError("Supported OANDA timeframes are M15, H1, and H4")
    if not 1 <= count <= 5000:
        raise ValueError("Candle count must be between 1 and 5000")

    api_token = token or config.OANDA_API_TOKEN
    if not api_token:
        raise RuntimeError(
            "OANDA_API_TOKEN is not configured; add a replacement practice token to local .env"
        )

    url = (
        f"{config.OANDA_PRACTICE_BASE_URL}/instruments/"
        f"{OANDA_INSTRUMENT}/candles"
    )
    params = {
        "granularity": GRANULARITY_MAP[timeframe],
        "count": count,
        "price": "M",
    }
    if to_time is not None:
        params["to"] = _format_api_time(to_time)

    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {api_token}"},
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        candles = response.json().get("candles", [])
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code:
            raise RuntimeError(f"OANDA practice candle request failed (HTTP {status_code})") from None
        raise RuntimeError("OANDA practice candle request failed due to a network error") from None
    except ValueError as exc:
        raise RuntimeError("OANDA returned an invalid candle response") from exc

    return _bars_from_candles(candles)


def archive_bars(timeframe, count=200, token=None, session=requests):
    bars = get_bars(timeframe, count=count, token=token, session=session)
    if bars.empty:
        return bars, 0

    stored = bars.copy()
    stored.insert(0, "source", OANDA_SOURCE)
    stored.insert(1, "symbol", OANDA_INSTRUMENT)
    stored.insert(2, "timeframe", timeframe.upper())
    return bars, save_market_bars(stored)


def archive_history(timeframe, start_time, end_time=None, page_size=5000,
                    token=None, session=requests):
    start = pd.Timestamp(start_time)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")

    cursor = end_time
    if cursor is not None:
        cursor = pd.Timestamp(cursor)
        if cursor.tzinfo is None:
            cursor = cursor.tz_localize("UTC")
        else:
            cursor = cursor.tz_convert("UTC")
        if cursor <= start:
            raise ValueError("End time must be later than start time")

    pages = []
    while True:
        page = get_bars(
            timeframe,
            count=page_size,
            token=token,
            session=session,
            to_time=cursor,
        )
        if page.empty:
            break

        pages.append(page)
        page_start = page.index.min()
        if page_start <= start:
            break
        if cursor is not None and page_start >= cursor:
            break
        cursor = page_start

    if not pages:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]), 0

    bars = pd.concat(pages).sort_index()
    bars = bars.loc[~bars.index.duplicated(keep="last")]
    if end_time is not None:
        end = pd.Timestamp(end_time)
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        bars = bars.loc[bars.index <= end]
    bars = bars.loc[bars.index >= start]

    stored = bars.copy()
    stored.insert(0, "source", OANDA_SOURCE)
    stored.insert(1, "symbol", OANDA_INSTRUMENT)
    stored.insert(2, "timeframe", timeframe.upper())
    return bars, save_market_bars(stored)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and archive OANDA practice XAU/USD candles (read-only)"
    )
    parser.add_argument("--timeframes", nargs="+", choices=GRANULARITY_MAP, default=["H4", "H1", "M15"])
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--from", dest="from_time", help="Backfill from this ISO-8601 timestamp")
    parser.add_argument("--to", dest="to_time", help="Optional ISO-8601 backfill end timestamp")
    args = parser.parse_args()

    if args.to_time and not args.from_time:
        parser.error("--to requires --from")

    init_db()
    for timeframe in args.timeframes:
        if args.from_time:
            bars, saved_count = archive_history(
                timeframe,
                start_time=args.from_time,
                end_time=args.to_time,
                page_size=args.count,
            )
        else:
            bars, saved_count = archive_bars(timeframe, count=args.count)
        if bars.empty:
            print(f"{timeframe}: no complete candles returned")
            continue
        print(
            f"{timeframe}: received {len(bars)} complete candles; "
            f"archived {saved_count}, {bars.index.min()} to {bars.index.max()} UTC"
        )


if __name__ == "__main__":
    main()