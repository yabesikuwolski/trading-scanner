import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

import config

log = logging.getLogger(__name__)

REVIEW_STATUSES = {"disabled", "available", "unavailable", "invalid_response"}
DECISIONS = {"TRADE", "WATCH", "NO_TRADE"}
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}

PROMPT_TEMPLATE = (
    "You are an XAUUSD market analyst. Review the supplied setup evidence carefully.\n"
    "Return valid JSON only with keys: quality_score, decision, confidence, summary, reasons, invalidations, risk_note.\n"
    "decision must be one of: TRADE, WATCH, NO_TRADE.\n"
    "quality_score must be an integer from 0 to 100. confidence must be LOW, MEDIUM, or HIGH.\n"
    "summary and risk_note must be strings; reasons and invalidations must be arrays of strings.\n"
    "- This is advisory only; never place an order or change the deterministic entry, stop, target, or position size.\n"
    "- Account feasibility and risk budget are computed by the application; do not override or recalculate them.\n"
    "- Favor NO_TRADE when the setup is weak, duplicated, poorly structured, or missing confirmation.\n"
    "- Treat unknown or missing data as unknown. Do not infer market freshness, broker rules, spread, margin, or account currency.\n"
    "- Do not invent facts not present in the data.\n"
    "Data: {summary_json}"
)


class AIReviewValidationError(ValueError):
    """Raised when model output does not match the required advisory schema."""


def _validate_review(value):
    if not isinstance(value, dict):
        raise AIReviewValidationError("response must be a JSON object")

    required = {
        "quality_score", "decision", "confidence", "summary", "reasons",
        "invalidations", "risk_note",
    }
    missing = required - value.keys()
    if missing:
        raise AIReviewValidationError(f"missing required fields: {', '.join(sorted(missing))}")
    extra = value.keys() - required
    if extra:
        raise AIReviewValidationError(f"unexpected fields: {', '.join(sorted(extra))}")

    score = value["quality_score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise AIReviewValidationError("quality_score must be an integer from 0 to 100")
    if not isinstance(value["decision"], str) or value["decision"] not in DECISIONS:
        raise AIReviewValidationError("decision must be TRADE, WATCH, or NO_TRADE")
    if not isinstance(value["confidence"], str) or value["confidence"] not in CONFIDENCE_LEVELS:
        raise AIReviewValidationError("confidence must be LOW, MEDIUM, or HIGH")

    for field in ("summary", "risk_note"):
        item = value[field]
        if not isinstance(item, str) or not item.strip() or len(item) > 2000:
            raise AIReviewValidationError(f"{field} must be a nonempty string of at most 2000 characters")
    for field in ("reasons", "invalidations"):
        items = value[field]
        if (not isinstance(items, list) or len(items) > 12
                or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in items)):
            raise AIReviewValidationError(f"{field} must be an array of at most 12 nonempty strings")

    return {
        "quality_score": score,
        "decision": value["decision"],
        "confidence": value["confidence"],
        "summary": value["summary"].strip(),
        "reasons": [item.strip() for item in value["reasons"]],
        "invalidations": [item.strip() for item in value["invalidations"]],
        "risk_note": value["risk_note"].strip(),
    }


def log_ai_review(symbol, review, *, summary=None, audit_path=None):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "status": review.get("status", "available"),
        "summary": summary or review.get("summary"),
        "decision": review.get("decision"),
        "quality_score": review.get("quality_score"),
        "confidence": review.get("confidence"),
        "reasons": review.get("reasons", []),
        "invalidations": review.get("invalidations", []),
        "risk_note": review.get("risk_note"),
        "error": review.get("error"),
    }
    log.info("AI advisory %s | status=%s | decision=%s | quality=%s | confidence=%s",
             symbol, record["status"], record["decision"], record["quality_score"], record["confidence"])

    try:
        log_path = Path(audit_path or "ai_reviews.jsonl")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        log.warning("AI review audit log could not be written.")

    return record


def build_setup_summary(symbol, analysis, scoring, review_context=None):
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
        "technical_evidence": {
            "bos": analysis.get("bos"),
            "liquidity_sweep": analysis.get("liquidity_sweep"),
            "retest": analysis.get("retest"),
            "rejection": analysis.get("rejection"),
            "active_fvgs": [fvg for fvg in analysis.get("fvgs", []) if not fvg.get("filled")][-6:],
        },
        "review_context": review_context or {"status": "unknown"},
    }


def build_ai_prompt(summary):
    return PROMPT_TEMPLATE.format(summary_json=json.dumps(summary, default=str))


def build_review_context(frames, simulation_plan, account_balance, *, news_filter_enabled):
    now = datetime.now(timezone.utc)
    timeframes = {}
    interval_minutes = {"M15": 15, "H1": 60, "H4": 240}
    for timeframe, frame in frames.items():
        item = {"freshness": "unknown", "latest_bar_time": None, "age_minutes": None, "ohlc": None}
        if frame is not None and not frame.empty:
            try:
                timestamp = frame.index[-1]
                timestamp = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    timestamp = timestamp.astimezone(timezone.utc)
                age = (now - timestamp).total_seconds() / 60
                item.update({
                    "latest_bar_time": timestamp.isoformat(),
                    "age_minutes": round(age, 1),
                    "freshness": "fresh" if 0 <= age <= interval_minutes.get(timeframe, 60) + config.MAX_MARKET_BAR_AGE_MINUTES else "stale",
                    "ohlc": {
                        key.lower(): float(frame.iloc[-1][key])
                        for key in ("Open", "High", "Low", "Close")
                        if key in frame.columns
                    },
                })
            except (TypeError, ValueError, OverflowError, KeyError):
                pass
        timeframes[timeframe] = item

    sizing_status = str((simulation_plan or {}).get("sizing_status", "UNKNOWN"))
    if (simulation_plan or {}).get("account_feasibility"):
        feasibility = (simulation_plan or {}).get("account_feasibility")
    elif sizing_status == "OK":
        feasibility = "UNKNOWN"
    elif sizing_status in {"MISSING_CONTRACT_SPECS", "MISSING_BROKER_VOLUME_RULES"}:
        feasibility = "UNKNOWN"
    else:
        feasibility = "INFEASIBLE"

    return {
        "observed_at": now.isoformat(),
        "market_data": {
            "source": config.MARKET_DATA_SOURCE_LABEL,
            "timestamp_semantics": "provider-supplied candle timestamp; open/close convention is not independently verified",
            "timeframes": timeframes,
        },
        "lifecycle": {
            "state_at_detection": "ACTIVE",
            "age_minutes": 0,
            "maximum_age_minutes": config.MAX_SETUP_AGE_MINUTES,
        },
        "news": {
            "filter_enabled": bool(news_filter_enabled),
            "status": "clear" if news_filter_enabled else "disabled",
        },
        "simulation_account": {
            "balance": float(account_balance),
            "currency": config.SIMULATION_ACCOUNT_CURRENCY,
            "risk_pct": float((simulation_plan or {}).get("risk_pct", config.MAX_RISK_PER_TRADE)),
            "risk_budget": (simulation_plan or {}).get("risk_amount"),
            "account_feasibility": feasibility,
            "risk_sizing_feasibility": (simulation_plan or {}).get("risk_sizing_feasibility", "UNKNOWN"),
            "margin_status": (simulation_plan or {}).get("margin_status", "unavailable"),
            "sizing_status": sizing_status,
            "trade_plan": simulation_plan or {},
        },
        "broker_contract_specs": {
            "contract_size": (simulation_plan or {}).get("contract_size"),
            "minimum_volume": (simulation_plan or {}).get("broker_min_volume"),
            "volume_step": (simulation_plan or {}).get("broker_volume_step"),
            "maximum_volume": (simulation_plan or {}).get("broker_max_volume"),
            "status": "configured_assumption" if all((simulation_plan or {}).get(field) is not None for field in (
                "contract_size", "broker_min_volume", "broker_volume_step"
            )) else "incomplete",
            "verification": (simulation_plan or {}).get("symbol_specs_verification", "unavailable"),
        },
        "execution_costs": {
            "spread": {"value": None, "status": "unavailable"},
            "margin": {"value": None, "status": "unavailable"},
        },
        "historical_evidence": {
            "status": "not_attached",
            "note": "The replay report is not included in this per-setup review payload.",
        },
    }


def parse_ai_response(raw_text):
    text = (raw_text or "").strip()
    if not text:
        raise AIReviewValidationError("empty model response")

    cleaned = text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        cleaned = match.group(0)

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIReviewValidationError("model response is not valid JSON") from exc
    return _validate_review(value)


def review_setup(symbol, analysis, scoring, review_context=None):
    if not config.AI_ADVISOR_ENABLED:
        return {"status": "disabled", "decision": None}

    summary = build_setup_summary(symbol, analysis, scoring, review_context)
    prompt = build_ai_prompt(summary)
    payload = json.dumps({
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }).encode("utf-8")
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:
        log.warning("AI review unavailable for %s: %s", symbol, exc)
        unavailable = {"status": "unavailable", "decision": None, "error": str(exc)[:500]}
        log_ai_review(symbol, unavailable, summary=summary)
        return unavailable

    try:
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get("response"), str):
            raise AIReviewValidationError("Ollama response did not contain model text")
        parsed = parse_ai_response(data["response"])
    except (json.JSONDecodeError, AIReviewValidationError) as exc:
        log.warning("AI response invalid for %s: %s", symbol, exc)
        invalid = {"status": "invalid_response", "decision": None, "error": str(exc)[:500]}
        log_ai_review(symbol, invalid, summary=summary)
        return invalid

    parsed["status"] = "available"
    log_ai_review(symbol, parsed, summary=summary)
    return parsed
