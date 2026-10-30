from datetime import datetime, timedelta, timezone


TIMEFRAME_MINUTES = {"M15": 15, "H1": 60, "H4": 240}


def evaluate_market_data_freshness(frames, *, now=None, max_extra_age_minutes=30):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    result = {}
    for timeframe, duration in TIMEFRAME_MINUTES.items():
        frame = (frames or {}).get(timeframe)
        item = {
            "status": "missing", "age_minutes": None,
            "latest_bar_time": None, "latest_candle_close": None,
        }
        if frame is None or frame.empty:
            result[timeframe] = item
            continue
        try:
            raw_time = frame.index[-1]
            timestamp = raw_time.to_pydatetime() if hasattr(raw_time, "to_pydatetime") else datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                item["status"] = "unknown_timezone"
                result[timeframe] = item
                continue
            timestamp = timestamp.astimezone(timezone.utc)
            candle_close = timestamp + timedelta(minutes=duration)
            age = (current - candle_close).total_seconds() / 60
            item.update({
                "latest_bar_time": timestamp.isoformat(),
                "latest_candle_close": candle_close.isoformat(),
                "age_minutes": round(age, 1),
            })
            if age < 0:
                item["status"] = "incomplete_candle"
            elif age > duration + max_extra_age_minutes:
                item["status"] = "stale"
            else:
                item["status"] = "fresh"
        except (TypeError, ValueError, OverflowError):
            item["status"] = "invalid_timestamp"
        result[timeframe] = item
    return result


def market_data_is_fresh(freshness):
    return all(freshness.get(tf, {}).get("status") == "fresh" for tf in TIMEFRAME_MINUTES)
