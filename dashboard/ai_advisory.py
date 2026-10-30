import json


STATUS_TEXT = {
    "available": "AI review completed.",
    "disabled": "AI review was disabled when this setup was recorded.",
    "unavailable": "AI review was attempted but the local model service was unavailable.",
    "invalid_response": "AI review was attempted, but its response failed schema validation.",
    "not_reviewed": "No AI review is recorded for this setup.",
}


def _as_string_list(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if not isinstance(value, str) or not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []


def build_ai_advisory_view(setup):
    status = setup.get("ai_status") or (
        "available" if setup.get("ai_decision") else "not_reviewed"
    )
    if status not in STATUS_TEXT:
        status = "not_reviewed"
    return {
        "status": status,
        "status_text": STATUS_TEXT[status],
        "available": status == "available",
        "decision": setup.get("ai_decision"),
        "quality_score": setup.get("ai_quality_score"),
        "confidence": setup.get("ai_confidence"),
        "summary": setup.get("ai_summary"),
        "reasons": _as_string_list(setup.get("ai_reasons")),
        "invalidations": _as_string_list(setup.get("ai_invalidations")),
        "risk_note": setup.get("ai_risk_note"),
        "reviewed_at": setup.get("ai_reviewed_at"),
    }
