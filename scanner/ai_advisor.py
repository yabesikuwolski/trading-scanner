import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

import config

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = (
    "You are an XAUUSD market analyst. Review the setup below as a strict trader, not a gambler.\n"
    "Return valid JSON only with keys: quality_score, decision, confidence, summary, reasons, invalidations, risk_note.\n"
    "decision must be one of: TRADE, WATCH, NO_TRADE.\n"
    "quality_score must be an integer from 0 to 100.\n"
    "- This is advisory only; do not place any order.\n"
    "- Favor NO_TRADE when the setup is weak, duplicated, poorly structured, or missing confirmation.\n"
    "- If risk/reward is poor or invalidation risk is high, lower the score.\n"
    "- Only reward setups with a serious structural and confirmation base.\n"
    "- Do not invent facts not present in the data.\n"
    "Data: {summary_json}"
)


def log_ai_review(symbol, review, *, summary=None):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "summary": summary or review.get("summary"),
        "decision": review.get("decision"),
        "quality_score": review.get("quality_score"),
        "confidence": review.get("confidence"),
        "reasons": review.get("reasons", []),
        "invalidations": review.get("invalidations", []),
        "risk_note": review.get("risk_note"),
    }
    log.info("AI advisory %s | decision=%s | quality=%s | confidence=%s | summary=%s",
             symbol,
             record["decision"],
             record["quality_score"],
             record["confidence"],
             record["summary"])

    try:
        log_path = Path("ai_reviews.jsonl")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        log.warning("AI review audit log could not be written.")

    return record


def build_setup_summary(symbol, analysis, scoring):
    signal = analysis.get("signal") or {}
    return {
        "symbol": symbol,
        "bias": analysis.get("bias"),
        "grade": scoring.get("grade"),
        "score": scoring.get("score"),
        "signal_type": signal.get("type"),
        "direction": signal.get("direction"),
        "entry": signal.get("entry"),
        "sl": signal.get("sl"),
        "tp1": signal.get("tp1"),
        "tp2": signal.get("tp2"),
        "rr": signal.get("rr"),
        "conditions": analysis.get("conditions", []),
        "entry_condition": signal.get("entry_condition"),
        "setup_id": analysis.get("setup_id"),
    }


def build_ai_prompt(summary):
    return PROMPT_TEMPLATE.format(summary_json=json.dumps(summary, default=str))


def parse_ai_response(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return {}

    cleaned = text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        cleaned = match.group(0)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "quality_score": 0,
            "decision": "NO_TRADE",
            "confidence": "LOW",
            "summary": "AI review could not parse the model response.",
            "reasons": ["Model output was not valid JSON."],
            "invalidations": ["Model response parse failed."],
            "risk_note": "Fallback to conservative review.",
        }


def review_setup(symbol, analysis, scoring):
    if not config.AI_ADVISOR_ENABLED:
        return {"enabled": False, "decision": "WATCH", "summary": "AI advisor disabled."}

    summary = build_setup_summary(symbol, analysis, scoring)
    prompt = build_ai_prompt(summary)
    payload = json.dumps({
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }).encode("utf-8")

    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    try:
        req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            text = (data.get("response") if isinstance(data, dict) else "") or ""
            parsed = parse_ai_response(text)
            parsed["enabled"] = True
            log_ai_review(symbol, parsed, summary=summary)
            return parsed
    except Exception as exc:
        log.warning("AI review unavailable for %s: %s", symbol, exc)
        fallback = {
            "enabled": True,
            "quality_score": 0,
            "decision": "NO_TRADE",
            "confidence": "LOW",
            "summary": "AI review unavailable; conservative fallback used.",
            "reasons": ["Ollama not reachable or model unavailable."],
            "invalidations": ["AI review failed."],
            "risk_note": "Fallback to manual review only.",
        }
        log_ai_review(symbol, fallback, summary=summary)
        return fallback
