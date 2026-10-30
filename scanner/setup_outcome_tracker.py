"""Track hypothetical outcomes for emitted setups using archived M15 candles.

These results are scenario estimates. They never confirm a broker fill or alter
the separately recorded manual trade journal.
"""

from datetime import datetime, timezone

import pandas as pd

import config
from database.db_manager import (
    get_pending_setup_outcomes,
    update_setup_modeled_outcome,
)
from scanner.csv_market_data import load_market_bars
from scanner.signal_replay import evaluate_signal_outcomes


MAX_HOLDING_BARS = 96
MAX_PENDING_BARS = 4
M15_MINUTES = 15


def _utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _store_outcome(setup_id, status, source, *, note=None, **values):
    values.update({
        "status": status,
        "source": source,
        "notes": note or (
            "Hypothetical M15 OHLC estimate; no broker fill is confirmed. "
            "Same-bar SL/TP1 collisions count as stop loss; intrabar path is unknown."
        ),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    })
    update_setup_modeled_outcome(setup_id, values)


def refresh_setup_outcomes(source=None, *, limit=100, now=None):
    """Advance a bounded batch of nonterminal setup outcomes.

    The one-position overlap constraint belongs to the batch replay. Here each
    setup is assessed independently, so skipped and overlapping signals still
    receive a comparable hypothetical outcome.
    """
    source = (source or config.MARKET_DATA_SOURCE_LABEL).strip().upper()
    current = _utc_timestamp(now or datetime.now(timezone.utc))
    pending = get_pending_setup_outcomes(limit=limit)
    if not pending:
        return {"checked": 0, "updated": 0, "terminal": 0}

    by_symbol = {}
    for setup in pending:
        by_symbol.setdefault(setup["symbol"], []).append(setup)

    updated = 0
    terminal = 0
    for symbol, setups in by_symbol.items():
        parsed_times = []
        for setup in setups:
            try:
                parsed_times.append(_utc_timestamp(setup["detected_at"]))
            except (TypeError, ValueError, OverflowError):
                parsed_times.append(None)
        valid_times = [timestamp for timestamp in parsed_times if timestamp is not None]
        if not valid_times:
            for setup in setups:
                _store_outcome(
                    setup["id"], "INVALID_SETUP", source,
                    note="Setup timestamp is missing or invalid; no outcome was estimated.",
                )
                updated += 1
                terminal += 1
            continue

        bars = load_market_bars(
            source, symbol, "M15", since=min(valid_times).to_pydatetime()
        )
        if bars.empty:
            for setup in setups:
                _store_outcome(
                    setup["id"], "WAITING_FOR_BARS", source,
                    note=f"No archived M15 bars are available from source {source}; outcome is unknown.",
                )
                updated += 1
            continue

        # Stored timestamps follow provider candle timestamps. Exclude the
        # newest candle until a full M15 interval has elapsed, conservatively
        # avoiding a partial-candle outcome.
        bars = bars.loc[
            bars.index + pd.Timedelta(minutes=M15_MINUTES) <= current
        ]
        if bars.empty:
            for setup in setups:
                _store_outcome(
                    setup["id"], "WAITING_FOR_BARS", source,
                    note="Archived M15 candles have not closed yet; outcome is unknown.",
                )
                updated += 1
            continue

        first_bar_time = bars.index[0]
        for setup, decision_time in zip(setups, parsed_times):
            setup_id = setup["id"]
            if decision_time is None:
                _store_outcome(
                    setup_id, "INVALID_SETUP", source,
                    note="Setup timestamp is missing or invalid; no outcome was estimated.",
                )
                updated += 1
                terminal += 1
                continue

            if first_bar_time > decision_time + pd.Timedelta(minutes=M15_MINUTES):
                _store_outcome(
                    setup_id, "DATA_UNAVAILABLE", source,
                    note="The archive starts more than one M15 interval after the setup; a complete outcome cannot be estimated.",
                )
                updated += 1
                terminal += 1
                continue

            future_count = int((bars.index >= decision_time).sum())
            if future_count == 0:
                _store_outcome(
                    setup_id, "WAITING_FOR_BARS", source,
                    note="No fully closed M15 bars have followed this setup yet; outcome is unknown.",
                )
                updated += 1
                continue

            direction = str(setup.get("direction") or "").upper()
            if direction not in {"BUY", "SELL"}:
                direction = "BUY" if str(setup.get("bias") or "").lower() == "bullish" else "SELL"
            try:
                signal = {
                    "setup_id": setup_id,
                    "decision_time": decision_time,
                    "signal_type": setup["signal_type"],
                    "direction": direction,
                    "entry": float(setup["entry"]),
                    "sl": float(setup["sl"]),
                    "tp1": float(setup["tp1"]),
                    "tp2": float(setup["tp2"]) if setup.get("tp2") is not None else None,
                }
                modeled = evaluate_signal_outcomes(
                    pd.DataFrame([signal]),
                    bars,
                    max_holding_bars=MAX_HOLDING_BARS,
                    max_pending_bars=MAX_PENDING_BARS,
                    transaction_cost_r=0.0,
                ).iloc[0].to_dict()
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                _store_outcome(
                    setup_id, "INVALID_SETUP", source,
                    note=f"Signal fields could not be modeled ({type(exc).__name__}); no outcome was estimated.",
                )
                updated += 1
                terminal += 1
                continue

            raw_outcome = modeled.get("outcome")
            fill_status = modeled.get("fill_status")
            if raw_outcome == "take_profit":
                status = "TP1"
            elif raw_outcome == "stop_loss":
                status = "STOP_LOSS"
            elif fill_status == "unfilled":
                status = "UNFILLED" if future_count >= MAX_PENDING_BARS else "PENDING_ENTRY"
            elif fill_status == "filled":
                status = "UNRESOLVED" if future_count >= MAX_HOLDING_BARS else "MODELED_OPEN"
            else:
                status = "INVALID_SETUP"

            terminal_status = status in {
                "TP1", "STOP_LOSS", "UNFILLED", "UNRESOLVED", "INVALID_SETUP"
            }
            note = (
                "Hypothetical M15 OHLC estimate only; no broker fill is confirmed. "
                "Same-bar SL/TP1 collisions count as stop loss; intrabar path is unknown."
            )
            _store_outcome(
                setup_id,
                status,
                source,
                note=note,
                fill_status=fill_status,
                outcome=raw_outcome,
                fill_time=modeled.get("fill_time"),
                fill_price=modeled.get("fill_price"),
                exit_time=modeled.get("exit_time"),
                exit_price=modeled.get("exit_price"),
                outcome_end_time=modeled.get("outcome_end_time"),
                gross_r_multiple=modeled.get("gross_r_multiple"),
                mfe_r=modeled.get("mfe_r"),
                mae_r=modeled.get("mae_r"),
                bars_held=modeled.get("bars_held"),
                tp1_reached=(
                    int(bool(modeled["tp1_reached"]))
                    if modeled.get("tp1_reached") is not None else None
                ),
                tp2_reached=(
                    int(bool(modeled["tp2_reached"]))
                    if modeled.get("tp2_reached") is not None else None
                ),
                stop_reached=(
                    int(bool(modeled["stop_reached"]))
                    if modeled.get("stop_reached") is not None else None
                ),
            )
            updated += 1
            terminal += int(terminal_status)

    return {"checked": len(pending), "updated": updated, "terminal": terminal}
