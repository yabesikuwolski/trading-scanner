"""Closed-candle M5 trigger used to qualify H4/H1/M15 setup candidates."""

from datetime import datetime, timedelta, timezone

import pandas as pd

import config
from scanner.market_analyzer import calculate_atr

STRATEGY_VERSION = "M5_CONFIRMATION_V1"
M5_DURATION = timedelta(minutes=5)


def evaluate_m5_trigger(baseline_analysis, m5_bars, *, now=None):
    """Return (confirmation, reason); only validated, completed M5 candles can confirm."""
    signal = (baseline_analysis or {}).get("signal")
    if not signal:
        return None, "no H4/H1/M15 setup candidate"
    if m5_bars is None or m5_bars.empty:
        return None, "M5 candles missing"
    if not m5_bars.attrs.get("closed_verified", False):
        return None, "M5 candle closure was not verified by the provider"
    if not isinstance(m5_bars.index, pd.DatetimeIndex) or m5_bars.index.tz is None:
        return None, "M5 timestamps must be timezone-aware"
    if not m5_bars.index.is_monotonic_increasing:
        return None, "M5 timestamps are not chronological"
    if m5_bars.index.has_duplicates:
        return None, "M5 timestamps contain duplicates"
    if len(m5_bars) < 14:
        return None, "insufficient M5 candles for the 14-bar ATR"

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return None, "current time has no timezone"
    latest_open = m5_bars.index[-1].to_pydatetime().astimezone(timezone.utc)
    latest_close = latest_open + M5_DURATION
    age_minutes = (current.astimezone(timezone.utc) - latest_close).total_seconds() / 60
    if age_minutes < 0:
        return None, "latest M5 candle is still open"
    if age_minutes > 5 + config.MAX_MARKET_BAR_AGE_MINUTES:
        return None, f"latest completed M5 candle is stale ({age_minutes:.1f} minutes past close)"

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(m5_bars.columns):
        return None, "M5 candles are missing OHLC fields"
    prices = m5_bars[["Open", "High", "Low", "Close"]]
    if prices.isna().any().any() or (prices <= 0).any().any():
        return None, "M5 candles contain invalid prices"
    if ((prices["High"] < prices[["Open", "Close"]].max(axis=1))
            | (prices["Low"] > prices[["Open", "Close"]].min(axis=1))
            | (prices["High"] < prices["Low"])).any():
        return None, "M5 candles contain inconsistent OHLC"

    atr = calculate_atr(m5_bars)
    if pd.isna(atr) or float(atr) <= 0:
        return None, "M5 ATR is unavailable"
    latest = m5_bars.iloc[-1]
    previous = m5_bars.iloc[-2]
    direction = str(signal.get("direction", "")).upper()
    close = float(latest["Close"])
    body = abs(float(latest["Close"]) - float(latest["Open"]))
    if body < float(atr) * 0.15:
        return None, "latest M5 candle body is below the ATR confirmation threshold"

    if direction == "BUY":
        if close <= float(previous["High"]):
            return None, "latest M5 close did not break the previous candle high"
        stop = min(float(latest["Low"]), float(signal["sl"])) - float(atr) * 0.25
        risk = close - stop
        target = close + risk * 2.0
    elif direction == "SELL":
        if close >= float(previous["Low"]):
            return None, "latest M5 close did not break the previous candle low"
        stop = max(float(latest["High"]), float(signal["sl"])) + float(atr) * 0.25
        risk = stop - close
        target = close - risk * 2.0
    else:
        return None, "setup direction is invalid"
    if risk <= 0:
        return None, "M5 trigger produced invalid stop geometry"
    if risk > float(atr) * 3.0:
        return None, "M5 trigger stop distance exceeds three ATR"

    confirmation = {
        "strategy_version": STRATEGY_VERSION,
        "direction": direction,
        "closed_verified": True,
        "candle_open_time": latest_open.isoformat(),
        "candle_close_time": latest_close.isoformat(),
        "entry_reference": close,
        "sl": stop,
        "tp1": target,
        "tp2": target,
        "rr": 2.0,
        "timeframe": "M5",
        "source_setup_type": signal.get("type"),
        "entry_condition": (
            "M5 closed candle broke the previous candle high"
            if direction == "BUY"
            else "M5 closed candle broke the previous candle low"
        ),
        "conditions": ["H4 bias", "H1 confirmation", "M15 setup", "M5 closed-candle trigger"],
    }
    return confirmation, None


def confirm_m5(baseline_analysis, m5_bars, *, now=None):
    """Backward-compatible convenience wrapper; unconfirmed triggers return None."""
    confirmation, _reason = evaluate_m5_trigger(baseline_analysis, m5_bars, now=now)
    return confirmation
