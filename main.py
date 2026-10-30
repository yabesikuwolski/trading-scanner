import time
import logging
from datetime import datetime, timedelta, timezone

import config
from scanner.data_provider import connect, disconnect, get_bars, get_quote, get_account_info
from scanner.market_analyzer import analyze_symbol
from scanner.scoring_engine import score_setup
from scanner.chart_generator import generate_chart
from scanner.news_filter import is_news_blackout, fetch_calendar
from alerts.notifier import send_alert
from scanner.m5_strategy import evaluate_m5_trigger, STRATEGY_VERSION
from risk.risk_manager import RiskManager
from database.db_manager import (
    init_db, save_setup, log_risk, get_simulation_performance,
    save_broker_account_snapshot, get_latest_symbol_setup, record_setup_notification,
    update_setup_lifecycle,
)
from scanner.ai_advisor import review_setup
from alerts.notifier import get_last_delivery_status
from scanner.setup_state import should_start_new_setup
from scanner.csv_market_data import store_market_bars
from dashboard.signal_lifecycle import evaluate_setup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scanner.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

_alerted: dict[str, datetime] = {}
_process_setup_keys: set[tuple[str, str, str, str, float]] = set()


def _setup_is_within_dedup_window(setup, now=None):
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.now().astimezone().tzinfo)
    detected = setup.get("detected_at")
    if not detected:
        return False
    detected_at = datetime.fromisoformat(str(detected).replace("Z", "+00:00"))
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)
    detected_at = detected_at.astimezone(now.tzinfo)
    return (now - detected_at).total_seconds() < config.MAX_SETUP_AGE_MINUTES * 60


def _valid_frame(frame, symbol, timeframe, now=None):
    if frame is None or frame.empty:
        return False, "missing candles"
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(frame.columns):
        return False, "missing OHLC fields"
    if frame.index.tz is None or not frame.index.is_monotonic_increasing:
        return False, "timestamps are not UTC and chronological"
    if frame.index.has_duplicates:
        return False, "duplicate candle timestamps"
    prices = frame[["Open", "High", "Low", "Close"]]
    if prices.isna().any().any() or (prices <= 0).any().any():
        return False, "invalid candle prices"
    if ((prices["High"] < prices[["Open", "Close"]].max(axis=1)) |
            (prices["Low"] > prices[["Open", "Close"]].min(axis=1)) |
            (prices["High"] < prices["Low"])).any():
        return False, "inconsistent OHLC"
    if frame.attrs.get("provider") == "BIQUOTE" and not frame.attrs.get("closed_verified", False):
        return False, "provider did not verify candle closure"
    latest = frame.index[-1].to_pydatetime()
    durations = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
    duration = durations.get(timeframe.upper(), 60)
    current = now or datetime.now(latest.tzinfo)
    if current.tzinfo is None:
        return False, "current time has no timezone"
    candle_close = latest + timedelta(minutes=duration)
    age_minutes = (current.astimezone(timezone.utc) - candle_close.astimezone(timezone.utc)).total_seconds() / 60
    if age_minutes < 0:
        return False, f"incomplete {timeframe} candle"
    if age_minutes > duration + config.MAX_MARKET_BAR_AGE_MINUTES:
        return False, f"stale {timeframe} candles"
    return True, None


def _quote_warning(quote):
    if not quote:
        return "quote unavailable"
    if quote.get("stale"):
        return "quote marked stale"
    age = quote.get("quote_age_seconds")
    if age is not None and float(age) > config.MAX_MARKET_BAR_AGE_MINUTES * 60:
        return "quote is stale"
    if quote.get("bid") is None or quote.get("ask") is None:
        return "bid/ask unavailable"
    if quote.get("spread") is None:
        return "spread unavailable"
    return None


def _cooldown_ok(key: str) -> bool:
    now = datetime.now()
    last = _alerted.get(key)
    if last and (now - last).total_seconds() < config.ALERT_COOLDOWN_MINUTES * 60:
        return False
    return True


def format_signal_summary(symbol, analysis, scoring):
    bias = analysis.get("bias", "neutral").upper()
    conditions = analysis.get("conditions", [])
    signal = analysis.get("signal")
    grade = scoring.get("grade", "Standard")
    score = scoring.get("score", 0)

    if not signal:
        return f"No actionable setup {symbol} | Bias={bias} | Score={score} | Grade={grade}"

    parts = [
        f"Potential signal {signal['type']} {symbol}",
        f"Bias={bias}",
        f"Grade={grade}",
        f"Score={score}",
        f"Entry={signal['entry']}",
        f"SL={signal['sl']}",
        f"TP1={signal['tp1']}",
        f"TP2={signal['tp2']}",
        f"RR={signal['rr']}R",
        f"Trigger={signal['entry_condition']}",
    ]

    signal_conditions = signal.get("conditions", conditions)
    if signal_conditions:
        parts.append(f"Reasons={'; '.join(signal_conditions)}")
    return " | ".join(parts)


def determine_stage(scoring, analysis) -> str:
    grade = scoring.get("grade")
    conditions = analysis.get("conditions", [])
    if grade == "ELITE":
        return "high_confidence"
    if grade == "A+" and "Rejection Candle" in conditions:
        return "m15_confirmation"
    if grade == "A":
        return "entry_zone"
    return "setup_developing"


def _signal_gap_reason(analysis):
    bias = analysis.get("bias", "neutral")
    if bias == "neutral":
        return "waiting for a directional H4 bias"
    if analysis.get("confirmed_bias") != bias:
        return "waiting for H1 confirmation to align with H4"
    if analysis.get("retest") and not analysis.get("rejection"):
        return "retest detected; waiting for a directional rejection candle"
    active_fvgs = [fvg for fvg in analysis.get("fvgs", []) if not fvg.get("filled")]
    if active_fvgs:
        return "waiting for an unretested directional entry zone or breakout trigger"
    return "waiting for an unretested FVG or unbroken H1 trigger level"


def _candidate_diagnostics(analysis, scoring):
    """Explain each observed strategy gate without treating score as a new gate."""
    bias = analysis.get("bias", "neutral")
    confirmed = analysis.get("confirmed_bias", "neutral")
    if bias == "neutral":
        h4 = "pending: no directional H4 EMA bias"
    else:
        h4 = f"pass: {bias} H4 EMA bias"
    if bias != "neutral" and confirmed == bias:
        h1 = f"pass: H1 confirms {bias}"
    else:
        h1 = f"pending: H1 bias {confirmed} does not confirm H4 {bias}"
    signal = analysis.get("signal")
    if signal:
        m15 = f"pass: {signal.get('type')} candidate ({signal.get('entry_condition', 'valid strategy trigger')})"
    elif analysis.get("retest") and not analysis.get("rejection"):
        m15 = "pending: M15 retest exists; directional rejection candle is missing"
    elif analysis.get("rejection") and not analysis.get("retest"):
        m15 = "pending: M15 rejection exists; no qualifying retest/entry trigger"
    else:
        m15 = f"pending: {_signal_gap_reason(analysis)}"
    grade = scoring.get("grade") or "below Standard grade"
    return f"gates H4[{h4}] H1[{h1}] M15[{m15}] | score={scoring.get('score', 0)} grade={grade}"


def _candidate_is_duplicate(symbol, analysis, now=None):
    signal = analysis.get("signal") or {}
    if not signal:
        return False
    latest = get_latest_symbol_setup(symbol)
    if not latest or not _setup_is_within_dedup_window(latest, now=now):
        return False
    candidate = {
        "symbol": symbol,
        "direction": signal.get("direction"),
        "zone": signal.get("zone") or signal.get("type"),
        "entry": signal.get("entry"),
        "sl": signal.get("sl"),
    }
    active = {
        "symbol": latest.get("symbol"),
        "direction": latest.get("direction"),
        "zone": latest.get("setup_zone") or latest.get("signal_type"),
        "entry": latest.get("entry"),
        "sl": latest.get("sl"),
        "state": latest.get("lifecycle_state", "ACTIVE"),
    }
    return not should_start_new_setup(active, candidate)


def _retry_undelivered_entry(symbol, analysis, scoring, quote_warnings=None, now=None):
    latest = get_latest_symbol_setup(symbol)
    if not latest or not _setup_is_within_dedup_window(latest, now=now):
        return False
    delivery_state = str(latest.get("telegram_status") or "").lower()
    terminal = str(latest.get("lifecycle_state") or "").upper() in {
        "INVALIDATED", "STALE", "NEWS BLOCKED"
    }
    if delivery_state in {"sent", "success"} or terminal:
        return False
    attempted = latest.get("telegram_attempted_at")
    if attempted:
        try:
            attempted_at = datetime.fromisoformat(str(attempted).replace("Z", "+00:00"))
            if attempted_at.tzinfo is None:
                attempted_at = attempted_at.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            elapsed = current.astimezone(timezone.utc) - attempted_at.astimezone(timezone.utc)
            if elapsed.total_seconds() < 300:
                return False
        except ValueError:
            pass
    log.warning("%s: retrying undelivered qualified setup %s", symbol, latest.get("id"))
    sent = send_alert(
        symbol, analysis, scoring, None, "entry_confirmed",
        setup_id=latest.get("id"),
        max_setup_age_minutes=config.MAX_SETUP_AGE_MINUTES,
        strategy_version=f"BASELINE_H4_H1_M15_V1+{STRATEGY_VERSION}",
        data_quality_warnings=quote_warnings or [],
    )
    delivery = get_last_delivery_status()
    record_setup_notification(
        latest["id"],
        "sent" if sent else "failed" if delivery.get("status") == "failed" else "not_configured",
        delivery.get("error"),
    )
    return True


def _process_candidate_key(symbol, analysis):
    signal = analysis.get("signal") or {}
    return (
        str(config.DB_PATH),
        str(symbol).upper(),
        str(signal.get("direction") or "").upper(),
        str(signal.get("zone") or signal.get("type") or ""),
        round(float(signal.get("entry")), 5),
    )


def scan_once(risk_manager: RiskManager):
    market_data = {}
    for symbol in config.SYMBOLS:
        try:
            frames = {}
            rejected = {}
            for timeframe, count in (
                ("M5", 200),
                (config.HTF, 200),
                (config.MTF, 200),
                (config.LTF, 100),
            ):
                try:
                    frame = get_bars(symbol, timeframe, count)
                except Exception as exc:
                    log.warning(f"{symbol} {timeframe}: provider failure: {exc}")
                    rejected[timeframe] = f"provider failure: {exc}"
                    continue
                valid, reason = _valid_frame(frame, symbol, timeframe)
                if not valid:
                    log.warning(f"{symbol} {timeframe}: rejected data: {reason}")
                    rejected[timeframe] = reason
                    continue
                frames[timeframe] = frame
                try:
                    stored_count = store_market_bars(
                        frame, symbol, timeframe, config.MARKET_DATA_SOURCE_LABEL
                    )
                    log.debug(
                        f"Archived {stored_count} {symbol} {timeframe} BiQuote bars"
                    )
                except Exception:
                    log.exception(
                        f"{symbol} {timeframe}: failed to archive BiQuote bars"
                    )
            if all(timeframe in frames for timeframe in (
                config.HTF, config.MTF, config.LTF
            )):
                market_data[symbol] = frames
            if not all(timeframe in frames for timeframe in (
                "M5", config.HTF, config.MTF, config.LTF
            )):
                log.warning(f"{symbol}: skipping analysis because required timeframe data is incomplete")
                if rejected:
                    details = ", ".join(f"{timeframe}={reason}" for timeframe, reason in rejected.items())
                else:
                    details = "required timeframe data unavailable"
                log.warning("%s: alerting paused because market data is not safe: %s", symbol, details)
        except Exception:
            log.exception(f"Error fetching market data for {symbol}")

    account = get_account_info() or {}
    save_broker_account_snapshot(account)
    simulation = get_simulation_performance() or {}
    balance = simulation.get("equity", config.SIMULATION_ACCOUNT_BALANCE)
    equity = simulation.get("equity", balance)
    if not account:
        log.info("No broker account connected; scanner using the persistent simulation risk baseline.")

    risk_status = risk_manager.check_risk(
        balance,
        equity,
        daily_start=simulation.get("daily_start_balance"),
        weekly_start=simulation.get("weekly_start_balance"),
    )
    log_risk(balance, equity, risk_status)

    if not risk_status["allowed"]:
        log.warning("Risk gate blocked entries: %s", "; ".join(risk_status["violations"]))
        return

    for sym in risk_status.get("warnings", []):
        log.info(f"Risk warning: {sym}")

    for symbol in config.SYMBOLS:
        try:
            frames = market_data.get(symbol)
            if frames is None:
                continue
            htf_df = frames[config.HTF]
            mtf_df = frames[config.MTF]
            ltf_df = frames[config.LTF]
            quote = None
            quote_warnings = []
            try:
                quote = get_quote(symbol)
                warning = _quote_warning(quote)
                if warning:
                    quote_warnings.append(warning)
            except Exception as exc:
                quote_warnings.append("quote request failed")
                log.warning(f"{symbol}: quote unavailable: {exc}")

            analysis = analyze_symbol(htf_df, mtf_df, ltf_df, symbol)
            scoring = score_setup(analysis)
            grade = scoring.get("grade")
            score = scoring.get("score", 0)

            log.info(
                f"{symbol}: bias={analysis['bias']} score={score} grade={grade} "
                f"conditions={analysis['conditions']}"
            )
            log.info("%s candidate diagnostics: %s", symbol, _candidate_diagnostics(analysis, scoring))
            if grade is None or analysis.get("signal") is None:
                log.info(format_signal_summary(symbol, analysis, scoring))
                continue

            log.info("%s: H4/H1/M15 setup candidate; awaiting closed M5 trigger", symbol)
            m5_confirmation, m5_reason = evaluate_m5_trigger(analysis, frames.get("M5"))
            if m5_confirmation is None:
                log.info("%s: actionable entry withheld; M5 trigger not confirmed: %s", symbol, m5_reason)
                log.info("%s entry withheld; M5 trigger not confirmed: %s", symbol, m5_reason)
                continue

            source_signal = analysis["signal"]
            source_signal_type = source_signal.get("type")
            qualified_signal = dict(source_signal)
            qualified_signal.update({
                "type": "MARKET/IMMEDIATE",
                "entry": m5_confirmation["entry_reference"],
                "sl": m5_confirmation["sl"],
                "tp1": m5_confirmation["tp1"],
                "tp2": m5_confirmation["tp2"],
                "rr": m5_confirmation["rr"],
                "entry_condition": (
                    f"M5 trigger for {source_signal_type}: "
                    f"{m5_confirmation['entry_condition']}"
                ),
                "conditions": list(source_signal.get("conditions", [])) + [
                    "M5 closed-candle trigger confirmed"
                ],
                "source_setup_type": source_signal_type,
            })
            analysis["signal"] = qualified_signal
            analysis["m5_confirmation"] = m5_confirmation
            analysis["levels"] = {
                "entry": qualified_signal["entry"],
                "sl": qualified_signal["sl"],
                "tp1": qualified_signal["tp1"],
                "tp2": qualified_signal["tp2"],
                "rr": qualified_signal["rr"],
            }
            log.info(format_signal_summary(symbol, analysis, scoring))

            if _candidate_is_duplicate(symbol, analysis):
                if not _retry_undelivered_entry(symbol, analysis, scoring, quote_warnings):
                    log.info(f"{symbol}: repeated setup suppressed by persistent identity")
                continue
            process_key = _process_candidate_key(symbol, analysis)
            if process_key in _process_setup_keys:
                log.info(f"{symbol}: repeated setup suppressed in current process")
                continue
            # News blackout check
            if config.NEWS_FILTER_ENABLED:
                blackout, reason = is_news_blackout(symbol)
                if blackout:
                    log.info(f"{symbol}: skipped — news blackout ({reason})")
                    continue

            cooldown_key = f"{symbol}_{grade}"
            if not _cooldown_ok(cooldown_key):
                log.info(f"{symbol}: {grade} alert in cooldown, skipping")
                continue
            chart_path = generate_chart(symbol, ltf_df, analysis, scoring, config.LTF)
            signal = analysis["signal"]
            simulation_plan = risk_manager.calculate_trade_plan(
                balance, signal["entry"], signal["sl"]
            )
            ai_review = review_setup(
                symbol,
                analysis,
                scoring,
                review_context={
                    "quote": quote,
                    "data_quality_warnings": quote_warnings,
                    "strategy_version": f"BASELINE_H4_H1_M15_V1+{STRATEGY_VERSION}",
                },
            ) if config.AI_ADVISOR_ENABLED else {"status": "disabled"}
            setup_id = save_setup(
                symbol,
                config.LTF,
                analysis,
                scoring,
                chart_path,
                simulation_plan=simulation_plan,
                ai_review=ai_review,
                setup_identity=(
                    f"{symbol}-{signal.get('direction')}-{signal.get('type')}-"
                    f"{float(signal.get('entry')):.5f}"
                ),
                setup_zone=signal.get("zone") or signal.get("type"),
            )
            _process_setup_keys.add(process_key)
            stage = "entry_confirmed"
            alert_sent = send_alert(
                symbol, analysis, scoring, chart_path, stage,
                setup_id=setup_id,
                max_setup_age_minutes=config.MAX_SETUP_AGE_MINUTES,
                simulation_plan=simulation_plan,
                ai_review=ai_review,
                strategy_version=f"BASELINE_H4_H1_M15_V1+{STRATEGY_VERSION}",
                data_quality_warnings=quote_warnings,
            )
            delivery = get_last_delivery_status()
            record_setup_notification(
                setup_id,
                "sent" if alert_sent else "failed" if delivery.get("status") == "failed" else "not_configured",
                delivery.get("error"),
            )
            _alerted[cooldown_key] = datetime.now()
            stored_setup = get_latest_symbol_setup(symbol)
            lifecycle_bar = ltf_df.iloc[-1].to_dict()
            lifecycle_bar["bar_time"] = ltf_df.index[-1].isoformat()
            lifecycle = evaluate_setup(
                stored_setup,
                lifecycle_bar,
                max_age_minutes=config.MAX_SETUP_AGE_MINUTES,
                max_market_age_minutes=config.MAX_MARKET_BAR_AGE_MINUTES,
                news_blocked=False,
                market_source=config.MARKET_DATA_SOURCE_LABEL,
            )
            if lifecycle["state"] != stored_setup.get("lifecycle_state", "ACTIVE"):
                update_setup_lifecycle(
                    setup_id,
                    lifecycle["state"],
                    lifecycle["reason"],
                    lifecycle.get("entry_touched_at"),
                )
                log.info("%s setup lifecycle %s: %s", symbol, lifecycle["state"], lifecycle["reason"])
            if alert_sent:
                log.info(f"Entry notification delivered — {symbol} {grade} (score {score}) stage={stage}")
            else:
                log.info(f"Signal logged locally; notification unavailable — {symbol} {grade}")

        except Exception:
            log.exception(f"Error scanning {symbol}")


def main():
    log.info("Trading Scanner initialising...")
    init_db()

    try:
        while True:
            try:
                connect()
                log.info("Connected to %s data source", config.MARKET_DATA_SOURCE_LABEL)
                break
            except Exception:
                log.exception(
                    "Market-data connection failed; retrying in %ss",
                    config.SCAN_INTERVAL,
                )
                time.sleep(config.SCAN_INTERVAL)

        # Pre-warm the calendar cache on startup; the scanner can still run if it is unavailable.
        if config.NEWS_FILTER_ENABLED:
            try:
                fetch_calendar()
                log.info("Economic calendar loaded")
            except Exception:
                log.exception("Economic calendar pre-warm failed; continuing with scan loop")

        risk_manager = RiskManager()

        while True:
            try:
                scan_once(risk_manager)
            except Exception:
                log.exception("Unexpected scan failure; retrying after the normal scan interval")
            log.info(f"Scan complete — next in {config.SCAN_INTERVAL}s")
            time.sleep(config.SCAN_INTERVAL)
    except KeyboardInterrupt:
        log.info("Scanner stopped")
    finally:
        disconnect()


if __name__ == "__main__":
    main()
