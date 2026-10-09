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


def get_bars(symbol, timeframe, count=200):
    interval = TF_MAP.get(timeframe, "15m")
    endpoint = f"{config.BIQUOTE_BASE_URL.rstrip('/')}/{symbol}/ohlc?interval={interval}&limit={count}"
    try:
        response = requests.get(endpoint, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return None
    except ValueError:
        return None

    bars = payload.get("bars") or []
    if not bars:
        return None

    df = pd.DataFrame(bars)
    if df.empty:
        return None

    df["time"] = pd.to_datetime(df["openTime"], errors="coerce", utc=True)
    df = df.dropna(subset=["time"]).copy()
    if df.empty:
        return None

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
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_account_info():
    return {}


def get_symbol_info(symbol):
    return {}
