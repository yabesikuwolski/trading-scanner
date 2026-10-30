import pandas as pd
import requests

import config

TF_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
}


def connect():
    """Verify the data source is reachable without requiring a trading account."""
    endpoint = f"{config.BIQUOTE_BASE_URL.rstrip('/')}/{'XAUUSD'}/ohlc?interval=15m&limit=1"
    try:
        response = requests.get(endpoint, timeout=15)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        raise RuntimeError(f"BiQuote connectivity check failed: {exc}") from exc


def disconnect():
    return None


def _request_json(endpoint):
    try:
        response = requests.get(endpoint, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"BiQuote request failed: {exc}") from None
    except ValueError:
        raise RuntimeError("BiQuote returned invalid JSON") from None


def get_bars(symbol, timeframe, count=200):
    timeframe = timeframe.upper()
    if timeframe not in TF_MAP:
        raise ValueError(f"Unsupported BiQuote timeframe: {timeframe}")
    if not 1 <= count <= 1000:
        raise ValueError("BiQuote candle count must be between 1 and 1000")
    interval = TF_MAP[timeframe]
    endpoint = f"{config.BIQUOTE_BASE_URL.rstrip('/')}/{symbol}/ohlc?interval={interval}&limit={count}"
    payload = _request_json(endpoint)

    bars = payload.get("bars") or []
    if not bars:
        raise RuntimeError(f"BiQuote returned no {timeframe} candles for {symbol}")

    df = pd.DataFrame(bars)
    if df.empty:
        raise RuntimeError(f"BiQuote returned empty {timeframe} candles for {symbol}")

    required = {"openTime", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"BiQuote candle response is missing fields: {sorted(missing)}")

    df["time"] = pd.to_datetime(df["openTime"], errors="coerce", utc=True)
    if df["time"].isna().any():
        raise RuntimeError(f"BiQuote returned invalid timestamps for {symbol} {timeframe}")

    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise RuntimeError(f"BiQuote returned invalid prices for {symbol} {timeframe}")
    if ((df["high"] < df[["open", "close"]].max(axis=1)) |
            (df["low"] > df[["open", "close"]].min(axis=1)) |
            (df["high"] < df["low"])).any():
        raise RuntimeError(f"BiQuote returned inconsistent OHLC for {symbol} {timeframe}")

    df.set_index("time", inplace=True)
    df.sort_index(inplace=True)
    if count > 0 and len(df) > count:
        df = df.tail(count).copy()
    df["Volume"] = pd.to_numeric(df.get("tickVolume", 0), errors="coerce").fillna(0)
    df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
    }, inplace=True)
    closed_verified = "isOpen" in df.columns
    if closed_verified and df["isOpen"].fillna(True).astype(bool).any():
        df = df.loc[~df["isOpen"].fillna(True).astype(bool)].copy()
    if df.empty:
        raise RuntimeError(f"BiQuote returned no completed {timeframe} candles for {symbol}")
    result = df[["Open", "High", "Low", "Close", "Volume"]]
    result.attrs["closed_verified"] = closed_verified
    result.attrs["provider"] = "BIQUOTE"
    result.attrs["symbol"] = symbol
    result.attrs["timeframe"] = timeframe
    return result


def get_quote(symbol):
    endpoint = f"{config.BIQUOTE_BASE_URL.rstrip('/')}/{symbol}"
    payload = _request_json(endpoint)
    required = {"bid", "ask", "timestamp"}
    missing = required.difference(payload)
    if missing:
        raise RuntimeError(f"BiQuote quote response is missing fields: {sorted(missing)}")
    timestamp = pd.to_datetime(payload["timestamp"], errors="coerce", utc=True)
    bid = pd.to_numeric(payload.get("bid"), errors="coerce")
    ask = pd.to_numeric(payload.get("ask"), errors="coerce")
    if pd.isna(timestamp) or pd.isna(bid) or pd.isna(ask) or bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError(f"BiQuote returned an invalid quote for {symbol}")
    spread = payload.get("spread")
    spread = pd.to_numeric(spread, errors="coerce") if spread is not None else None
    if spread is None or pd.isna(spread):
        spread = float(ask - bid)
    if spread < 0:
        raise RuntimeError(f"BiQuote returned an invalid spread for {symbol}")
    return {
        "symbol": symbol,
        "bid": float(bid),
        "ask": float(ask),
        "mid": float(payload.get("mid") or (bid + ask) / 2),
        "spread": float(spread),
        "timestamp": timestamp.to_pydatetime(),
        "market_state": payload.get("marketState"),
        "stale": bool(payload.get("stale", False)),
        "quote_age_seconds": payload.get("quoteAgeSeconds"),
    }


def get_account_info():
    return {}


def get_symbol_info(symbol):
    return {}
