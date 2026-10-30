import html
import logging

import requests

import config

log = logging.getLogger(__name__)

STAGE_HEADERS = {
    "setup_approaching": "🟡 SETUP APPROACHING",
    "entry_confirmed": "✅ ENTRY SIGNAL CONFIRMED",
    "setup_developing": "🔍 SETUP DEVELOPING",
    "entry_zone": "⚡ ENTRY ZONE APPROACHING",
    "m5_confirmation": "✅ 5-MIN CONFIRMATION",
    "m15_confirmation": "✅ 15-MIN CONFIRMATION",
    "high_confidence": "🎯 HIGH-CONFIDENCE SETUP",
    "risk_violation": "🚨 RISK ALERT",
}

BIAS_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
_last_delivery = {"status": "not_attempted", "error": None}


def credentials_configured():
    token = str(config.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = str(config.TELEGRAM_CHAT_ID or "").strip()
    return bool(
        token and chat_id
        and token != "your_bot_token_here"
        and chat_id != "your_chat_id_here"
    )


def get_last_delivery_status():
    return dict(_last_delivery)


def _set_delivery(status, error=None):
    _last_delivery.update(status=status, error=error)


def _redact(value):
    text = str(value or "")
    for secret in (config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:500]


def _post(method, **kwargs):
    if not credentials_configured():
        _set_delivery("not_configured")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, timeout=config.TELEGRAM_TIMEOUT_SECONDS, **kwargs)
    except requests.Timeout as exc:
        detail = _redact(exc)
        _set_delivery("timeout", detail)
        log.warning("Telegram %s timed out: %s", method, detail)
        return False
    except requests.RequestException as exc:
        detail = _redact(exc)
        _set_delivery("network_error", detail)
        log.warning("Telegram %s network error: %s", method, detail)
        return False
    except Exception as exc:
        detail = _redact(exc)
        _set_delivery("network_error", detail)
        log.warning("Telegram %s failed: %s", method, detail)
        return False

    if response.status_code >= 400:
        detail = _redact(response.text)
        _set_delivery("http_error", f"HTTP {response.status_code}: {detail}")
        log.warning("Telegram %s returned HTTP %s: %s", method, response.status_code, detail)
        return False

    try:
        body = response.json()
    except (ValueError, AttributeError):
        _set_delivery("invalid_response", "Telegram returned a non-JSON response")
        log.warning("Telegram %s returned a non-JSON success response", method)
        return False
    if not isinstance(body, dict) or body.get("ok") is not True:
        detail = _redact(body.get("description") if isinstance(body, dict) else "invalid response")
        _set_delivery("api_error", detail or "Telegram API rejected the request")
        log.warning("Telegram %s API error: %s", method, detail or "unspecified")
        return False

    _set_delivery("success")
    return True


def send_message(text):
    return _post("sendMessage", json={
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })


def send_photo(photo_path, caption=""):
    try:
        with open(photo_path, "rb") as photo:
            return _post("sendPhoto", data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "caption": caption[:1024],
                "parse_mode": "HTML",
            }, files={"photo": photo})
    except FileNotFoundError:
        _set_delivery("file_not_found", "Chart image was not found")
        log.warning("Telegram chart image was not found")
        return False


def _display(value):
    return html.escape(str(value if value is not None else "—"), quote=False)


def _account_feasibility(simulation_plan):
    status = str((simulation_plan or {}).get("sizing_status", "UNKNOWN"))
    account_state = (simulation_plan or {}).get("account_feasibility")
    if account_state in {"FEASIBLE", "INFEASIBLE", "UNKNOWN"}:
        return account_state, status
    if status == "OK":
        return "UNKNOWN", status
    if status in {
        "MISSING_CONTRACT_SPECS", "MISSING_BROKER_VOLUME_RULES",
        "ACCOUNT_CURRENCY_CONVERSION_UNAVAILABLE",
    }:
        return "UNKNOWN", status
    return "INFEASIBLE", status


def format_alert(
    symbol,
    analysis,
    scoring,
    alert_stage="setup_developing",
    *,
    simulation_plan=None,
    ai_review=None,
    setup_id=None,
    setup_age_minutes=0,
    max_setup_age_minutes=None,
):
    from scanner.scoring_engine import GRADE_EMOJI

    bias = str(analysis.get("bias", "neutral")).lower()
    signal = analysis.get("signal") or {}
    grade = scoring.get("grade", "Standard")
    score = scoring.get("score", 0)
    max_score = scoring.get("max_score", 14) or 14
    score = max(0, min(int(score or 0), int(max_score)))
    progress_bar = "█" * int((score / int(max_score)) * 10) + "░" * (10 - int((score / int(max_score)) * 10))
    header = STAGE_HEADERS.get(alert_stage, "📊 SIGNAL ALERT")

    msg = f"{header}\n\n"
    msg += f"{GRADE_EMOJI.get(grade, '📊')} <b>{_display(symbol)} — {_display(grade)} Setup</b>\n"
    msg += f"Score: [{progress_bar}] {score}/{_display(max_score)}\n"
    msg += f"Bias: {BIAS_EMOJI.get(bias, '⚪')} <b>{_display(bias.upper())}</b>"
    if analysis.get("session"):
        msg += f" | Session: {_display(str(analysis['session']).replace('_', ' ').title())}"
    msg += "\n"

    if signal:
        direction = signal.get("direction") or ("BUY" if bias == "bullish" else "SELL")
        signal_type = str(signal.get("type") or "SETUP")
        signal_label = signal_type if str(direction).upper() in signal_type.upper() else f"{direction} {signal_type}"
        msg += f"\n<b>{_display(symbol)} — {_display(signal_label)}</b>\n"
        if signal.get("source_setup_type"):
            msg += f"M15 setup: {_display(signal['source_setup_type'])}\n"
        if setup_id:
            msg += f"Setup ID: <code>{_display(setup_id)}</code>\n"
        msg += f"Entry: <code>{_display(signal.get('entry'))}</code> | SL: <code>{_display(signal.get('sl'))}</code>\n"
        msg += f"TP1: <code>{_display(signal.get('tp1'))}</code> | TP2: <code>{_display(signal.get('tp2'))}</code>\n"
        msg += f"Planned RR: <b>{_display(signal.get('rr'))}R</b>\n"
        msg += f"Age: {_display(setup_age_minutes)}m"
        if max_setup_age_minutes is not None:
            msg += f" / {_display(max_setup_age_minutes)}m expiry"
        msg += "\n"
        if signal.get("entry_condition"):
            msg += f"Trigger: {_display(signal.get('entry_condition'))}\n"

    bos = analysis.get("bos") or {}
    sweep = analysis.get("liquidity_sweep") or {}
    technical_bits = []
    if bos.get("type"):
        technical_bits.append(f"H1 {bos['type']}")
    if sweep.get("type"):
        technical_bits.append(f"H1 {sweep['type']}")
    all_conditions = signal.get("conditions") or analysis.get("conditions") or []
    m5_conditions = [condition for condition in all_conditions if str(condition).startswith("M5")]
    other_conditions = [condition for condition in all_conditions if not str(condition).startswith("M5")]
    conditions = other_conditions[:2] + m5_conditions[:1]
    if conditions:
        technical_bits.extend(
            condition if str(condition).startswith("M5") else f"M15 {condition}"
            for condition in conditions
        )
    if technical_bits:
        msg += "\n<b>Technical basis:</b> " + _display("; ".join(technical_bits)) + "\n"

    plan = simulation_plan or {}
    if plan:
        feasibility, sizing_status = _account_feasibility(plan)
        currency = _display(plan.get("currency", config.SIMULATION_ACCOUNT_CURRENCY))
        msg += f"\n<b>Simulation suitability: {feasibility}</b> ({_display(sizing_status)})\n"
        msg += f"Risk budget: <code>{currency} {_display(plan.get('risk_amount'))}</code>\n"
        size = plan.get("position_size") if feasibility == "UNKNOWN" and sizing_status == "OK" else None
        if feasibility == "FEASIBLE" and plan.get("position_size") is not None:
            msg += f"Configured scenario volume: <code>{_display(plan['position_size'])}</code>\n"
            msg += f"Sized 2R reward: <code>{currency} {_display(plan.get('sized_expected_profit'))}</code>\n"
            msg += "Uses configured contract rules; confirm them against the intended broker.\n"
        elif size is not None:
            msg += f"Calculated volume under unverified rules: <code>{_display(size)}</code>\n"
            msg += "Account feasibility is unknown; margin and broker settings are not verified.\n"
        elif feasibility == "UNKNOWN":
            msg += "Broker size cannot be verified; no executable volume shown.\n"
        else:
            msg += "Proposed size is not suitable at this risk budget; do not treat this as approval.\n"

    review = ai_review or {"status": "disabled"}
    ai_status = review.get("status", "disabled")
    if ai_status == "available":
        msg += (
            f"\n<b>AI advisory:</b> {_display(review.get('decision'))} · "
            f"{_display(review.get('quality_score'))}/100 · {_display(review.get('confidence'))}\n"
        )
        if review.get("summary"):
            msg += f"{_display(str(review['summary'])[:180])}\n"
    else:
        status_labels = {
            "disabled": "disabled",
            "unavailable": "unavailable",
            "invalid_response": "invalid response",
        }
        msg += f"\nAI advisory: {_display(status_labels.get(ai_status, 'not reviewed'))}\n"

    msg += "\n<i>Manual decision support only. No order or broker fill is confirmed.</i>"
    if len(msg) <= 1000:
        return msg
    footer = "<i>Manual decision support only. No order or broker fill is confirmed.</i>"
    body = msg.rsplit("\n<i>", 1)[0]
    return body[:900].rstrip() + "…\n\n" + footer


def send_alert(
    symbol,
    analysis,
    scoring,
    chart_path=None,
    alert_stage="setup_developing",
    *,
    simulation_plan=None,
    ai_review=None,
    setup_id=None,
    setup_age_minutes=0,
    max_setup_age_minutes=None,
):
    # Telegram is a retired notification route. The scanner uses
    # alerts.notifier.send_alert, which validates a completed M5 trigger,
    # aligned H4/H1 bias, signal levels, and the configured provider before
    # dispatch. Keep this legacy API local-only so it cannot bypass that gate.
    log.info("Legacy Telegram signal dispatch suppressed; use the validated notifier")
    return False


def send_lifecycle_update(setup, lifecycle):
    state = str(lifecycle.get("state") or "").upper()
    if state not in {"ENTRY TOUCHED", "STALE", "INVALIDATED", "NEWS BLOCKED", "PRICE UNKNOWN"}:
        return False
    log.info("Lifecycle state retained locally; phone dispatch suppressed: %s", state)
    return False


def send_risk_alert(violations, warnings=None):
    log.warning("Risk status retained in local logs; phone dispatch suppressed: %s", violations)
    return False


def send_startup_message(symbols):
    log.info("Scanner startup retained in local logs; phone dispatch suppressed: %s", symbols)
    return False
