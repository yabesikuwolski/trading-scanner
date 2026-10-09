from datetime import datetime, timezone

from scanner.scoring_engine import classify_setup

"""Dashboard setup viability checks.

Price invalidation uses the latest BIQUOTE M15 candle: a wick through the
strategy's swing-derived stop is the structure-break proxy because setup rows
do not persist a separate swing level; reaching TP1 before action marks the
setup missed. A stale or missing candle is suppressed as PRICE UNKNOWN.
"""


LIFECYCLE_STATES = {
    "READY",
    "NEWS BLOCKED",
    "STALE",
    "INVALIDATED",
    "REVIEWED",
    "TRADE LOGGED",
    "PRICE UNKNOWN",
}


def parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def setup_age_minutes(setup, now=None):
    detected = parse_timestamp(setup.get("detected_at"))
    if detected is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0, int((current.astimezone(timezone.utc) - detected).total_seconds() // 60))


def planned_reward_risk(setup):
    entry = setup.get("entry")
    stop = setup.get("sl")
    target = setup.get("tp1")
    if entry is None or stop is None or target is None:
        return None
    risk = abs(float(entry) - float(stop))
    reward = abs(float(target) - float(entry))
    if risk <= 0:
        return None
    return reward / risk


def remaining_reward_risk(setup, price):
    stop = setup.get("sl")
    target = setup.get("tp1")
    if stop is None or target is None:
        return None
    direction = 1 if str(setup.get("bias", "")).lower() == "bullish" else -1
    risk = direction * (float(price) - float(stop))
    reward = direction * (float(target) - float(price))
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def evaluate_setup(
    setup,
    latest_bar,
    *,
    now=None,
    max_age_minutes=60,
    max_market_age_minutes=30,
    news_blocked=False,
    news_reason=None,
    reviewed=False,
    trade_logged=False,
):
    age_minutes = setup_age_minutes(setup, now=now)
    planned_rr = planned_reward_risk(setup)
    result = {
        "state": "READY",
        "reason": "Fresh setup; price, score, reward/risk, and news checks passed.",
        "age_minutes": age_minutes,
        "planned_rr": planned_rr,
        "remaining_rr": None,
    }

    if trade_logged:
        result.update(state="TRADE LOGGED", reason="A journal trade is linked to this setup.")
        return result
    if reviewed:
        result.update(state="REVIEWED", reason="Dismissed by the user; retained in history.")
        return result
    if age_minutes is None:
        result.update(state="STALE", reason="Signal timestamp is missing or invalid.")
        return result
    if age_minutes >= max_age_minutes:
        result.update(state="STALE", reason=f"Signal age is {age_minutes}m; limit is {max_age_minutes}m.")
        return result
    if latest_bar is None:
        result.update(state="PRICE UNKNOWN", reason="No current BIQUOTE M15 price; viability cannot be confirmed.")
        return result
    bar_time = parse_timestamp(latest_bar.get("bar_time"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if bar_time is not None:
        market_age = (current.astimezone(timezone.utc) - bar_time).total_seconds() / 60
        if market_age < 0 or market_age > max_market_age_minutes:
            result.update(
                state="PRICE UNKNOWN",
                reason=f"Latest BIQUOTE M15 candle is {max(0, int(market_age))}m old; live-price limit is {max_market_age_minutes}m.",
            )
            return result

    score = setup.get("score")
    expected_grade = classify_setup(int(score)) if score is not None else None
    if expected_grade is None or setup.get("grade") != expected_grade:
        reason = (
            "Setup score is below the configured minimum grade."
            if expected_grade is None
            else f"Stored grade {setup.get('grade')} does not match score classification {expected_grade}."
        )
        result.update(state="INVALIDATED", reason=reason)
        return result

    entry = setup.get("entry")
    stop = setup.get("sl")
    target = setup.get("tp1")
    if entry is None or stop is None or target is None:
        result.update(state="INVALIDATED", reason="Entry, stop, or TP1 is missing.")
        return result

    bullish = str(setup.get("bias", "")).lower() == "bullish"
    high = float(latest_bar.get("high", latest_bar.get("High", latest_bar.get("close", latest_bar.get("Close")))))
    low = float(latest_bar.get("low", latest_bar.get("Low", latest_bar.get("close", latest_bar.get("Close")))))
    close = float(latest_bar.get("close", latest_bar.get("Close")))
    stop_breached = low <= float(stop) if bullish else high >= float(stop)
    target_reached = high >= float(target) if bullish else low <= float(target)
    if stop_breached:
        result.update(state="INVALIDATED", reason=f"Price breached stop-loss invalidation level {stop}.")
        return result
    if target_reached:
        result.update(state="INVALIDATED", reason=f"TP1 {target} was reached before the setup could be acted on.")
        return result

    remaining_rr = remaining_reward_risk(setup, close)
    result["remaining_rr"] = remaining_rr
    if remaining_rr is None or remaining_rr < 1.0:
        result.update(state="INVALIDATED", reason="Remaining reward/risk from current price is below 1:1.")
        return result
    if planned_rr is None or planned_rr < 1.0:
        result.update(state="INVALIDATED", reason="Planned reward/risk from entry is below 1:1.")
        return result
    if news_blocked:
        result.update(state="NEWS BLOCKED", reason=news_reason or "High-impact news blackout is active.")
        return result

    return result