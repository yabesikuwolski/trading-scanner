import time
import logging
from datetime import datetime

import config
from scanner.mt5_connector import connect, disconnect, get_bars, get_account_info
from scanner.market_analyzer import analyze_symbol
from scanner.scoring_engine import score_setup
from scanner.chart_generator import generate_chart
from scanner.news_filter import is_news_blackout, fetch_calendar
from alerts.telegram_bot import send_alert, send_message, send_risk_alert, send_startup_message
from risk.risk_manager import RiskManager
from database.db_manager import init_db, save_setup, log_risk
from scanner.csv_market_data import store_market_bars

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


def _cooldown_ok(key: str) -> bool:
    now = datetime.now()
    last = _alerted.get(key)
    if last and (now - last).total_seconds() < config.ALERT_COOLDOWN_MINUTES * 60:
        return False
    _alerted[key] = now
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


def scan_once(risk_manager: RiskManager):
    market_data = {}
    for symbol in config.SYMBOLS:
        try:
            frames = {}
            for timeframe, count in (
                (config.HTF, 200),
                (config.MTF, 200),
                (config.LTF, 100),
            ):
                frame = get_bars(symbol, timeframe, count)
                if frame is None:
                    log.warning(f"{symbol} {timeframe}: failed to fetch bars")
                    continue
                frames[timeframe] = frame
                try:
                    stored_count = store_market_bars(
                        frame, symbol, timeframe, "BIQUOTE"
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
            else:
                log.warning(f"{symbol}: skipping analysis because timeframe data is incomplete")
        except Exception:
            log.exception(f"Error fetching market data for {symbol}")

    account = get_account_info() or {}
    if not account:
        balance = 10000.0
        equity = 10000.0
        log.info("No broker account connected; scanner running in data-only mode with fallback risk baseline.")
    else:
        balance = account.get("balance", 0)
        equity = account.get("equity", balance)

    risk_status = risk_manager.check_risk(balance, equity)
    log_risk(balance, equity, risk_status)

    if not risk_status["allowed"]:
        for v in risk_status["violations"]:
            log.warning(f"Risk violation: {v}")
        if _cooldown_ok("RISK_VIOLATION"):
            send_risk_alert(risk_status["violations"], risk_status["warnings"])
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

            analysis = analyze_symbol(htf_df, mtf_df, ltf_df, symbol)
            scoring = score_setup(analysis)
            grade = scoring.get("grade")
            score = scoring.get("score", 0)

            log.info(
                f"{symbol}: bias={analysis['bias']} score={score} grade={grade} "
                f"conditions={analysis['conditions']}"
            )
            log.info(format_signal_summary(symbol, analysis, scoring))

            if grade is None or analysis.get("signal") is None:
                continue

            # News blackout check
            if config.NEWS_FILTER_ENABLED:
                blackout, reason = is_news_blackout(symbol)
                if blackout:
                    log.info(f"{symbol}: skipped — news blackout ({reason})")
                    if _cooldown_ok(f"NEWS_{symbol}"):
                        send_message(
                            f"🚫 <b>{symbol}</b> alert suppressed\n<i>{reason}</i>\n"
                            f"Window: -{config.NEWS_BLOCK_MINUTES_BEFORE}m / +{config.NEWS_BLOCK_MINUTES_AFTER}m"
                        )
                    continue

            cooldown_key = f"{symbol}_{grade}"
            if not _cooldown_ok(cooldown_key):
                log.info(f"{symbol}: {grade} alert in cooldown, skipping")
                continue

            chart_path = generate_chart(symbol, ltf_df, analysis, scoring, config.LTF)
            save_setup(symbol, config.LTF, analysis, scoring, chart_path)
            stage = determine_stage(scoring, analysis)
            alert_sent = send_alert(symbol, analysis, scoring, chart_path, stage)
            if alert_sent:
                log.info(f"Telegram alert sent — {symbol} {grade} (score {score}) stage={stage}")
            else:
                log.info(f"Signal logged locally; Telegram unavailable — {symbol} {grade}")

        except Exception:
            log.exception(f"Error scanning {symbol}")


def main():
    log.info("Trading Scanner initialising...")
    init_db()

    try:
        connect()
        log.info("Connected to BiQuote data source")
    except RuntimeError as e:
        log.error(str(e))
        return

    # Pre-warm the calendar cache on startup
    if config.NEWS_FILTER_ENABLED:
        fetch_calendar()
        log.info("Economic calendar loaded")

    send_startup_message(config.SYMBOLS)
    risk_manager = RiskManager()

    try:
        while True:
            scan_once(risk_manager)
            log.info(f"Scan complete — next in {config.SCAN_INTERVAL}s")
            time.sleep(config.SCAN_INTERVAL)
    except KeyboardInterrupt:
        log.info("Scanner stopped")
        send_message("⏹ <b>Trading Scanner stopped.</b>")
    finally:
        disconnect()


if __name__ == "__main__":
    main()
