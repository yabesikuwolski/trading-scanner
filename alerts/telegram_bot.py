import requests
import config

STAGE_HEADERS = {
    "setup_developing": "🔍 SETUP DEVELOPING",
    "entry_zone": "⚡ ENTRY ZONE APPROACHING",
    "m5_confirmation": "✅ 5-MIN CONFIRMATION",
    "m15_confirmation": "✅ 15-MIN CONFIRMATION",
    "high_confidence": "🎯 HIGH-CONFIDENCE SETUP",
    "risk_violation": "🚨 RISK ALERT",
}

BIAS_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}


def _post(method, **kwargs):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, timeout=15, **kwargs)
        if r.status_code >= 400:
            print(f"[Telegram] {method} HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[Telegram] {method} error: {e}")
        return False


def send_message(text):
    return _post("sendMessage", json={
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })


def send_photo(photo_path, caption=""):
    try:
        with open(photo_path, "rb") as f:
            return _post("sendPhoto", data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "caption": caption[:1024],
                "parse_mode": "HTML",
            }, files={"photo": f})
    except FileNotFoundError:
        print(f"[Telegram] photo not found: {photo_path}")
        return False


def format_alert(symbol, analysis, scoring, alert_stage="setup_developing"):
    from scanner.scoring_engine import GRADE_EMOJI
    bias = analysis.get("bias", "neutral")
    signal = analysis.get("signal")
    levels = signal or {}
    conditions = analysis.get("conditions", [])
    session = analysis.get("session", "unknown").replace("_", " ").title()
    grade = scoring.get("grade", "Standard")
    score = scoring.get("score", 0)
    max_score = scoring.get("max_score", 14)
    breakdown = scoring.get("breakdown", [])

    header = STAGE_HEADERS.get(alert_stage, "📊 SIGNAL ALERT")
    grade_emoji = GRADE_EMOJI.get(grade, "📊")
    bias_emoji = BIAS_EMOJI.get(bias, "⚪")

    progress_filled = int((score / max_score) * 10)
    progress_bar = "█" * progress_filled + "░" * (10 - progress_filled)

    msg = f"{header}\n\n"
    msg += f"{grade_emoji} <b>{symbol}</b> — <b>{grade} Setup</b>\n"
    msg += f"Score: [{progress_bar}] {score}/{max_score}\n"
    msg += f"Bias: {bias_emoji} <b>{bias.upper()}</b> | Session: {session}\n\n"

    if signal:
        msg += f"<b>Potential Signal:</b> {signal['type']} ({signal['direction']})\n"
        msg += f"<b>Entry condition:</b> {signal['entry_condition']}\n\n"

    signal_conditions = signal.get("conditions", conditions) if signal else conditions
    if signal_conditions:
        msg += "<b>Conditions Met:</b>\n"
        for c in signal_conditions:
            msg += f"  ✓ {c}\n"
        msg += "\n"

    if levels:
        msg += "<b>Trade Levels:</b>\n"
        msg += f"  📍 Entry:  <code>{levels.get('entry', '—')}</code>\n"
        msg += f"  🛑 Stop:   <code>{levels.get('sl', '—')}</code>\n"
        msg += f"  🎯 TP1:    <code>{levels.get('tp1', '—')}</code>  (2R)\n"
        msg += f"  🎯 TP2:    <code>{levels.get('tp2', '—')}</code>  (3R)\n\n"

    simulation_plan = levels.get("simulation_plan") or {}
    if simulation_plan:
        volume = simulation_plan.get("position_size")
        volume_text = f"{volume:g}" if volume is not None else "not executable"
        msg += "<b>Simulation account:</b>\n"
        msg += (
            f"  Risk: <code>${simulation_plan['risk_amount']:.2f}</code> | "
            f"2R reward: <code>${simulation_plan['expected_profit']:.2f}</code>\n"
        )
        msg += (
            f"  Volume: <code>{volume_text}</code> | "
            f"Sizing: <code>{simulation_plan['sizing_status']}</code>\n\n"
        )

    msg += "<i>Conditional strategy scenario only. No order is placed; manual decision required.</i>"
    return msg


def send_alert(symbol, analysis, scoring, chart_path=None, alert_stage="setup_developing"):
    msg = format_alert(symbol, analysis, scoring, alert_stage)
    if chart_path:
        return send_photo(chart_path, caption=msg)
    return send_message(msg)


def send_risk_alert(violations, warnings=None):
    msg = "🚨 <b>RISK CONSTITUTION ALERT</b>\n\n"
    for v in violations:
        msg += f"❌ {v}\n"
    if warnings:
        msg += "\n⚠️ <b>Warnings:</b>\n"
        for w in warnings:
            msg += f"  {w}\n"
    msg += "\n<b>Trading suspended per your constitution rules.</b>"
    return send_message(msg)


def send_startup_message(symbols):
    msg = (
        "🚀 <b>Trading Scanner Online</b>\n\n"
        f"Monitoring: <code>{', '.join(symbols)}</code>\n"
        "Timeframes: H4 bias → H1 structure → M15 entry\n\n"
        "Strategy: HTF Bias · BOS · Liquidity Sweeps · FVG · Retest · Rejection\n"
        "Alerts: Standard / A / A+ / 💎 Elite"
    )
    return send_message(msg)
