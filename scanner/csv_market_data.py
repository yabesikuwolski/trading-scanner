import re

import pandas as pd

from database.db_manager import get_connection, save_market_bars


COLUMN_ALIASES = {
    "timestamp": {"datetime", "timestamp", "opentime", "timeutc"},
    "date": {"date", "day"},
    "time": {"time", "hour"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c"},
    "tick_volume": {"tickvolume", "tickvol", "volumetick"},
    "volume": {"volume", "vol"},
}


def _normalize_column_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name).strip().lower())


def _column_map(columns):
    normalized = {_normalize_column_name(column): column for column in columns}
    result = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[canonical] = normalized[alias]
                break
    return result


def _parse_timestamps(values, timezone):
    parsed = []
    for value in values:
        timestamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(timestamp):
            parsed.append(pd.NaT)
        elif timestamp.tzinfo is None:
            if timezone is None:
                raise ValueError(
                    "CSV timestamps have no timezone; specify the broker timezone"
                )
            parsed.append(timestamp.tz_localize(timezone).tz_convert("UTC"))
        else:
            parsed.append(timestamp.tz_convert("UTC"))
    return pd.DatetimeIndex(parsed)


def normalize_ohlc_csv(path, symbol, timeframe, source, timezone=None):
    raw = pd.read_csv(path, sep=None, engine="python", decimal=",")
    columns = _column_map(raw.columns)

    if "timestamp" in columns:
        timestamps = raw[columns["timestamp"]]
    elif "date" in columns and "time" in columns:
        timestamps = raw[columns["date"]].astype(str).str.strip() + " " + raw[
            columns["time"]
        ].astype(str).str.strip()
    elif "time" in columns:
        timestamps = raw[columns["time"]]
    else:
        raise ValueError("CSV must have a timestamp column or separate date and time columns")

    missing = [name for name in ("open", "high", "low", "close") if name not in columns]
    if missing:
        raise ValueError(f"CSV is missing required OHLC columns: {', '.join(missing)}")

    bars = pd.DataFrame(index=_parse_timestamps(timestamps, timezone))
    bars.index.name = "bar_time"
    if bars.index.isna().any():
        raise ValueError("CSV contains one or more invalid timestamps")

    for name in ("open", "high", "low", "close"):
        bars[name.title()] = pd.to_numeric(
            raw[columns[name]], errors="coerce"
        ).to_numpy()
    if bars[["Open", "High", "Low", "Close"]].isna().any().any():
        raise ValueError("CSV contains missing or non-numeric OHLC values")

    volume_column = columns.get("tick_volume", columns.get("volume"))
    bars["Volume"] = (
        pd.to_numeric(raw[volume_column], errors="coerce").fillna(0).to_numpy()
        if volume_column
        else [0.0] * len(bars)
    )

    valid_candles = (
        (bars["High"] >= bars[["Open", "Close"]].max(axis=1))
        & (bars["Low"] <= bars[["Open", "Close"]].min(axis=1))
        & (bars["High"] >= bars["Low"])
    )
    if not valid_candles.all():
        raise ValueError("CSV contains OHLC rows with inconsistent high/low values")

    bars = bars.sort_index()
    bars = bars.loc[~bars.index.duplicated(keep="last")]
    bars.insert(0, "source", source.strip().upper())
    bars.insert(1, "symbol", symbol.upper())
    bars.insert(2, "timeframe", timeframe.upper())
    return bars


def import_ohlc_csv(path, symbol, timeframe, source, timezone=None):
    bars = normalize_ohlc_csv(path, symbol, timeframe, source, timezone)
    saved_count = save_market_bars(bars)
    return bars, saved_count


def store_market_bars(bars, symbol, timeframe, source):
    if bars.empty:
        return 0
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("Market bars must have a DatetimeIndex")
    if bars.index.tz is None:
        raise ValueError("Market bar timestamps must be timezone-aware")

    columns = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in columns if column not in bars.columns]
    if missing:
        raise ValueError(f"Market bars are missing columns: {', '.join(missing)}")

    stored = bars[columns].copy()
    stored.index = stored.index.tz_convert("UTC")
    stored.index.name = "bar_time"
    stored.insert(0, "source", source.strip().upper())
    stored.insert(1, "symbol", symbol.upper())
    stored.insert(2, "timeframe", timeframe.upper())
    return save_market_bars(stored)


def load_market_bars(source, symbol, timeframe):
    connection = get_connection()
    rows = connection.execute("""
        SELECT bar_time, open, high, low, close, volume
        FROM market_bars
        WHERE source = ? AND symbol = ? AND timeframe = ?
        ORDER BY bar_time
    """, (source.strip().upper(), symbol.upper(), timeframe.upper())).fetchall()
    connection.close()

    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    bars = pd.DataFrame([dict(row) for row in rows])
    bars["bar_time"] = pd.to_datetime(bars["bar_time"], utc=True)
    bars.set_index("bar_time", inplace=True)
    bars.index.name = "time"
    bars.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }, inplace=True)
    return bars