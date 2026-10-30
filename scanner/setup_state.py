import re

SETUP_STATES = {
    "NO_SETUP",
    "SETUP_DETECTED",
    "WAITING_CONFIRMATION",
    "SIGNAL_FIRED",
    "ACTIVE",
    "TP1_HIT",
    "BREAKEVEN",
    "TP2_HIT",
    "STOPPED_OUT",
    "INVALIDATED",
    "COOLDOWN",
}

STATE_TRANSITIONS = {
    "NO_SETUP": {"SETUP_DETECTED": "SETUP_DETECTED", "NEW_SETUP": "SETUP_DETECTED"},
    "SETUP_DETECTED": {"CONFIRMED": "SIGNAL_FIRED", "REJECTED": "NO_SETUP"},
    "WAITING_CONFIRMATION": {"CONFIRMED": "SIGNAL_FIRED", "INVALIDATED": "INVALIDATED", "REJECTED": "NO_SETUP"},
    "SIGNAL_FIRED": {"ACTIVE": "ACTIVE", "INVALIDATED": "INVALIDATED", "STOPPED_OUT": "STOPPED_OUT"},
    "ACTIVE": {"TP1_HIT": "TP1_HIT", "BREAKEVEN": "BREAKEVEN", "TP2_HIT": "TP2_HIT", "STOPPED_OUT": "STOPPED_OUT", "INVALIDATED": "INVALIDATED"},
    "TP1_HIT": {"BREAKEVEN": "BREAKEVEN", "TP2_HIT": "TP2_HIT", "INVALIDATED": "INVALIDATED", "STOPPED_OUT": "STOPPED_OUT"},
    "BREAKEVEN": {"TP2_HIT": "TP2_HIT", "INVALIDATED": "INVALIDATED", "STOPPED_OUT": "STOPPED_OUT"},
    "TP2_HIT": {"CLOSED": "NO_SETUP", "INVALIDATED": "INVALIDATED", "STOPPED_OUT": "STOPPED_OUT"},
    "STOPPED_OUT": {"COOLDOWN": "COOLDOWN", "RESET": "NO_SETUP"},
    "INVALIDATED": {"COOLDOWN": "COOLDOWN", "NEW_SETUP": "SETUP_DETECTED"},
    "COOLDOWN": {"NEW_SETUP": "SETUP_DETECTED", "RESET": "NO_SETUP"},
}


def build_setup_id(symbol, direction, zone, suffix=None):
    symbol = str(symbol or "").upper().strip()
    direction = str(direction or "").upper().strip()
    zone = str(zone or "UNKNOWN").strip().replace(" ", "_")
    base = f"{symbol}-{direction}-{zone}"
    if suffix:
        return f"{base}-{suffix}"
    return base


def infer_direction_from_signal_type(signal_type):
    if signal_type is None:
        return None
    text = str(signal_type).upper()
    if "BUY" in text or "LONG" in text:
        return "BUY"
    if "SELL" in text or "SHORT" in text:
        return "SELL"
    return None


def transition_state(current_state, event):
    current_state = str(current_state or "NO_SETUP").upper()
    event = str(event or "").upper()
    next_state = STATE_TRANSITIONS.get(current_state, {}).get(event)
    if next_state is not None:
        return next_state
    if current_state == "NO_SETUP" and event in {"CONFIRMED", "SETUP_DETECTED"}:
        return "SETUP_DETECTED"
    if event in {"NEW_SETUP", "SETUP_DETECTED"}:
        return "SETUP_DETECTED"
    return current_state


def _entry_gap(previous, current):
    previous_entry = previous.get("entry")
    current_entry = current.get("entry")
    if previous_entry is None or current_entry is None:
        return None
    try:
        return abs(float(previous_entry) - float(current_entry))
    except (TypeError, ValueError):
        return None


def _zones_are_close(previous_zone, current_zone, tolerance):
    previous_zone = str(previous_zone or "").strip()
    current_zone = str(current_zone or "").strip()
    if previous_zone == current_zone:
        return True
    number_pattern = r"[-+]?(?:\d+\.?\d*|\.\d+)"
    previous_numbers = [float(value) for value in re.findall(number_pattern, previous_zone)]
    current_numbers = [float(value) for value in re.findall(number_pattern, current_zone)]
    previous_shape = re.sub(number_pattern, "#", previous_zone).lower()
    current_shape = re.sub(number_pattern, "#", current_zone).lower()
    if previous_shape != current_shape or len(previous_numbers) != len(current_numbers):
        return False
    return all(abs(left - right) <= tolerance for left, right in zip(previous_numbers, current_numbers))


def is_same_setup(previous, current, tolerance=0.15):
    if previous is None or current is None:
        return False

    if str(previous.get("symbol") or "").upper() != str(current.get("symbol") or "").upper():
        return False

    previous_dir = str(previous.get("direction") or "").upper()
    current_dir = str(current.get("direction") or "").upper()
    if previous_dir and current_dir and previous_dir != current_dir:
        return False

    previous_zone = str(previous.get("zone") or "").strip()
    current_zone = str(current.get("zone") or "").strip()
    if previous_zone and current_zone and not _zones_are_close(previous_zone, current_zone, tolerance):
        return False

    gap = _entry_gap(previous, current)
    if gap is None:
        return False
    return gap <= tolerance


def should_start_new_setup(active_setup, candidate, *, same_zone_tolerance=0.15, min_price_move=0.4):
    if not active_setup:
        return True
    if not candidate:
        return False

    state = str(active_setup.get("state") or "NO_SETUP").upper()
    candidate_symbol = str(candidate.get("symbol") or "").upper()
    active_symbol = str(active_setup.get("symbol") or "").upper()
    if candidate_symbol and active_symbol and candidate_symbol != active_symbol:
        return True

    candidate_direction = str(candidate.get("direction") or "").upper()
    active_direction = str(active_setup.get("direction") or "").upper()
    if candidate_direction and active_direction and candidate_direction != active_direction:
        return True

    if state in {"SETUP_DETECTED", "WAITING_CONFIRMATION", "SIGNAL_FIRED", "ACTIVE", "ENTRY TOUCHED", "TP1_HIT", "BREAKEVEN", "TP2_HIT"}:
        if (active_setup.get("zone") and candidate.get("zone")
                and str(active_setup["zone"]).strip() == str(candidate["zone"]).strip()):
            return False
        if is_same_setup(active_setup, candidate, tolerance=same_zone_tolerance):
            return False
        return True

    if state in {"STOPPED_OUT", "INVALIDATED", "COOLDOWN"}:
        if (active_setup.get("zone") and candidate.get("zone")
                and not _zones_are_close(active_setup.get("zone"), candidate.get("zone"), same_zone_tolerance)):
            return True
        gap = _entry_gap(active_setup, candidate)
        if gap is not None and gap >= min_price_move:
            return True
        return False

    return True
