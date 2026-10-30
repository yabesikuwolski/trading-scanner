"""Alert-only notification transport for ntfy or Discord."""

import logging
import math

import requests

from alerts.telegram_bot import format_alert

import config

log = logging.getLogger(__name__)
_last_delivery = {"status": "not_attempted", "error": None}


def _configured():
    provider = config.NOTIFICATION_PROVIDER
    if provider == "NTFY":
        return bool(config.NTFY_TOPIC)
    if provider == "DISCORD":
        return bool(config.DISCORD_WEBHOOK_URL)
    return False


def get_last_delivery_status():
    return dict(_last_delivery)


def _set(status, error=None):
    _last_delivery.update(status=status, error=error)


def _post(url, *, headers=None, json=None, data=None):
    try:
        response = requests.post(
            url,
            headers=headers,
            json=json,
            data=data,
            timeout=config.NOTIFICATION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        _set("failed", str(exc)[:300])
        log.warning("Notification delivery failed: %s", exc)
        return False
    _set("sent")
    return True


def _send_message(text):
    if not _configured():
        _set("not_configured", "Set NOTIFICATION_PROVIDER and its provider setting")
        return False
    if config.NOTIFICATION_PROVIDER == "NTFY":
        return _post(
            config.NTFY_URL.rstrip("/") + "/" + config.NTFY_TOPIC,
            headers={"Title": "XAUUSD ENTRY SIGNAL CONFIRMED", "Priority": "high", "Tags": "chart_with_upwards_trend"},
            data=text,
        )
    return _post(config.DISCORD_WEBHOOK_URL, json={"content": text[:1900]})


def send_alert(symbol, analysis, scoring, chart_path=None, alert_stage="setup_developing", **kwargs):
    signal = (analysis or {}).get("signal") or {}
    confirmation = (analysis or {}).get("m5_confirmation") or {}
    conditions = signal.get("conditions") or []
    if alert_stage != "entry_confirmed":
        _set("rejected", "Only confirmed entry alerts may use the phone notification channel")
        return False
    if str(signal.get("direction", "")).upper() not in {"BUY", "SELL"}:
        _set("rejected", "Signal direction must be BUY or SELL")
        return False
    direction = str(signal["direction"]).upper()
    expected_bias = "bullish" if direction == "BUY" else "bearish"
    if ((analysis or {}).get("bias") != expected_bias
            or (analysis or {}).get("confirmed_bias") != expected_bias):
        _set("rejected", "H4 bias and H1 confirmation must agree with signal direction")
        return False
    if (confirmation.get("timeframe") != "M5"
            or confirmation.get("closed_verified") is not True
            or "M5 closed-candle trigger confirmed" not in conditions):
        _set("rejected", "A verified completed M5 trigger is required")
        return False
    required_stages = {"H4 bias", "H1 confirmation", "M15 setup", "M5 closed-candle trigger"}
    if not required_stages.issubset(set(confirmation.get("conditions") or [])):
        _set("rejected", "M5 confirmation is missing a required strategy stage")
        return False
    for field in ("entry", "sl", "tp1", "tp2", "rr"):
        try:
            value = float(signal[field])
        except (KeyError, TypeError, ValueError):
            _set("rejected", f"Signal is missing a valid {field}")
            return False
        if not math.isfinite(value):
            _set("rejected", f"Signal has a non-finite {field}")
            return False
    if float(signal["rr"]) <= 0:
        _set("rejected", "Risk-to-reward must be positive")
        return False
    entry, stop, tp1, tp2 = (float(signal[key]) for key in ("entry", "sl", "tp1", "tp2"))
    geometry_valid = (
        stop < entry < tp1 <= tp2 if direction == "BUY"
        else tp2 <= tp1 < entry < stop
    )
    if not geometry_valid:
        _set("rejected", "Signal entry, stop, and targets have invalid directional geometry")
        return False
    message = format_alert(
        symbol, analysis, scoring, alert_stage,
        simulation_plan=kwargs.get("simulation_plan"),
        ai_review=kwargs.get("ai_review"),
        setup_id=kwargs.get("setup_id"),
        setup_age_minutes=kwargs.get("setup_age_minutes", 0),
        max_setup_age_minutes=kwargs.get("max_setup_age_minutes"),
    )
    strategy_version = kwargs.get("strategy_version")
    warnings = kwargs.get("data_quality_warnings") or []
    if strategy_version:
        message = f"Strategy: {strategy_version}\n" + message
    if warnings:
        message += "\nData warnings: " + "; ".join(str(item) for item in warnings)
    return _send_message(message)
