import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from database.db_manager import init_db
from scanner.csv_market_data import load_market_bars
from scanner.market_analyzer import analyze_symbol, calculate_atr
from scanner.scoring_engine import score_setup
from scanner.setup_state import should_start_new_setup


TIMEFRAME_DELTAS = {
    "M5": pd.Timedelta(minutes=5),
    "M15": pd.Timedelta(minutes=15),
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
}


def closed_window(bars, timeframe, decision_time, max_bars):
    timeframe = timeframe.upper()
    if timeframe not in TIMEFRAME_DELTAS:
        raise ValueError(f"Unsupported replay timeframe: {timeframe}")
    cutoff = pd.Timestamp(decision_time)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    last_open_time = cutoff - TIMEFRAME_DELTAS[timeframe]
    end_position = bars.index.searchsorted(last_open_time, side="right")
    return bars.iloc[max(0, end_position - max_bars):end_position]


def replay_signals(h4_bars, h1_bars, m15_bars, symbol="XAUUSD",
                   max_h4=200, max_h1=200, max_m15=100,
                   start_time=None, end_time=None, progress_every=0,
                   max_setup_age_minutes=60):
    if any(frame.index.tz is None for frame in (h4_bars, h1_bars, m15_bars)):
        raise ValueError("Replay candle indexes must be timezone-aware")
    if any(not frame.index.is_monotonic_increasing for frame in (h4_bars, h1_bars, m15_bars)):
        raise ValueError("Replay candle indexes must be sorted oldest-to-newest")

    start = pd.Timestamp(start_time) if start_time is not None else None
    end = pd.Timestamp(end_time) if end_time is not None else None
    if start is not None:
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    if end is not None:
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")

    records = []
    start_position = 0
    if start is not None:
        first_open_time = start - TIMEFRAME_DELTAS["M15"]
        start_position = m15_bars.index.searchsorted(first_open_time, side="left")

    decisions = 0
    duplicate_suppressed = 0
    previous_candidate = None
    replay_times = m15_bars.index[start_position:]
    for m15_open_time in replay_times:
        decision_time = m15_open_time + TIMEFRAME_DELTAS["M15"]
        if end is not None and decision_time > end:
            break
        decisions += 1
        if progress_every and decisions % progress_every == 0:
            print(f"Replay progress: {decisions} M15 decisions", file=sys.stderr, flush=True)

        h4_window = closed_window(h4_bars, "H4", decision_time, max_h4)
        h1_window = closed_window(h1_bars, "H1", decision_time, max_h1)
        m15_window = closed_window(m15_bars, "M15", decision_time, max_m15)

        if len(h4_window) < 50 or len(h1_window) < 10 or len(m15_window) < 3:
            continue

        analysis = analyze_symbol(
            h4_window,
            h1_window,
            m15_window,
            symbol,
            as_of=decision_time.to_pydatetime(),
        )
        scoring = score_setup(analysis)
        signal = analysis.get("signal")
        if signal is None:
            continue

        candidate = {
            "symbol": symbol,
            "direction": signal["direction"],
            "zone": signal.get("zone") or signal["type"],
            "entry": signal["entry"],
        }
        if previous_candidate is not None:
            previous_time = previous_candidate["decision_time"]
            if (decision_time - previous_time).total_seconds() / 60 < max_setup_age_minutes:
                if not should_start_new_setup(
                    previous_candidate["setup"], candidate
                ):
                    duplicate_suppressed += 1
                    continue

        previous_candidate = {
            "decision_time": decision_time,
            "setup": {**candidate, "state": "ACTIVE"},
        }

        atr14_m15 = calculate_atr(m15_window)
        atr14_m15 = float(atr14_m15) if pd.notna(atr14_m15) else None
        records.append({
            "setup_id": f"{symbol}:{signal['direction']}:{candidate['zone']}:{decision_time.isoformat()}",
            "decision_time": decision_time,
            "signal_type": signal["type"],
            "zone": candidate["zone"],
            "direction": signal["direction"],
            "bias": analysis["bias"],
            "trend_regime": analysis["bias"],
            "atr14_m15": atr14_m15,
            "grade": scoring.get("grade"),
            "score": scoring.get("score"),
            "entry": signal["entry"],
            "sl": signal["sl"],
            "tp1": signal["tp1"],
            "tp2": signal["tp2"],
            "rr": signal["rr"],
            "entry_condition": signal["entry_condition"],
            "conditions": "; ".join(signal.get("conditions", [])),
            "h4_last_closed": h4_window.index[-1],
            "h1_last_closed": h1_window.index[-1],
            "m15_last_closed": m15_window.index[-1],
        })

    result = pd.DataFrame(records)
    result.attrs["decision_count"] = decisions
    result.attrs["duplicate_suppressed_count"] = duplicate_suppressed
    return result


def evaluate_signal_outcomes(
    signals,
    m15_bars,
    max_holding_bars=96,
    max_pending_bars=4,
    transaction_cost_r=0.0,
):
    if not m15_bars.index.is_monotonic_increasing:
        raise ValueError("Outcome candle indexes must be sorted oldest-to-newest")
    if m15_bars.index.tz is None:
        raise ValueError("Outcome candle indexes must be timezone-aware")
    if max_holding_bars < 1:
        raise ValueError("max_holding_bars must be at least 1")
    if max_pending_bars < 1:
        raise ValueError("max_pending_bars must be at least 1")
    if transaction_cost_r < 0:
        raise ValueError("transaction_cost_r cannot be negative")

    outcomes = []
    busy_until = None
    for signal in signals.to_dict("records"):
        decision_time = pd.Timestamp(signal["decision_time"])
        if decision_time.tzinfo is None:
            decision_time = decision_time.tz_localize("UTC")
        else:
            decision_time = decision_time.tz_convert("UTC")
        if busy_until is not None and decision_time < busy_until:
            outcomes.append({
                "fill_status": "overlap_blocked",
                "outcome": "overlap_blocked",
                "fill_time": None,
                "fill_price": None,
                "exit_time": None,
                "outcome_end_time": decision_time,
                "exit_price": None,
                "bars_held": 0,
                "gross_r_multiple": None,
                "r_multiple": None,
                "mfe_price": None,
                "mae_price": None,
                "mfe_r": None,
                "mae_r": None,
                "tp1_reached": None,
                "tp2_reached": None,
                "tp2_reached_after_exit": None,
                "tp2_after_exit_time": None,
                "stop_reached": None,
                "favorable_close_bars": None,
                "favorable_close_minutes": None,
                "excursion_method": None,
            })
            continue
        start = m15_bars.index.searchsorted(decision_time, side="left")
        future = m15_bars.iloc[start:start + max_holding_bars]
        direction = 1 if signal["direction"] == "BUY" else -1
        entry = float(signal["entry"])
        stop = float(signal["sl"])
        target = float(signal["tp1"])
        fill_time = None
        fill_price = None
        exit_time = None
        exit_price = None
        outcome = "unfilled"
        bars_held = 0
        last_evaluated_time = None
        mfe_price = 0.0
        mae_price = 0.0
        tp1_reached = False
        tp2_reached = False
        tp2_reached_after_exit = False
        tp2_after_exit_time = None
        stop_reached = False
        favorable_close_bars = 0
        tp2 = float(signal["tp2"]) if pd.notna(signal.get("tp2")) else None

        for position, (bar_time, bar) in enumerate(future.iterrows(), start=1):
            open_price = float(bar["Open"])
            high = float(bar["High"])
            low = float(bar["Low"])

            if fill_price is None:
                if position > max_pending_bars:
                    break
                last_evaluated_time = bar_time
                signal_type = signal["signal_type"]
                if signal_type == "MARKET/IMMEDIATE":
                    fill_price = entry
                elif signal_type.endswith("LIMIT"):
                    touched = low <= entry if direction == 1 else high >= entry
                    if touched:
                        gap_favorable = open_price < entry if direction == 1 else open_price > entry
                        fill_price = open_price if gap_favorable else entry
                elif signal_type.endswith("STOP"):
                    touched = high >= entry if direction == 1 else low <= entry
                    if touched:
                        gap_adverse = open_price > entry if direction == 1 else open_price < entry
                        fill_price = open_price if gap_adverse else entry
                else:
                    raise ValueError(f"Unsupported signal type: {signal_type}")
                if fill_price is None:
                    continue
                fill_time = bar_time

            last_evaluated_time = bar_time
            bars_held += 1
            stop_hit = low <= stop if direction == 1 else high >= stop
            target_hit = high >= target if direction == 1 else low <= target
            tp1_reached = tp1_reached or target_hit
            if tp2 is not None:
                tp2_reached = tp2_reached or (high >= tp2 if direction == 1 else low <= tp2)
            stop_reached = stop_reached or stop_hit
            favorable_excursion = max(0.0, high - fill_price) if direction == 1 else max(0.0, fill_price - low)
            adverse_excursion = max(0.0, fill_price - low) if direction == 1 else max(0.0, high - fill_price)
            mfe_price = max(mfe_price, favorable_excursion)
            mae_price = max(mae_price, adverse_excursion)
            if stop_hit or target_hit:
                outcome = "stop_loss" if stop_hit else "take_profit"
                if stop_hit:
                    gap_through_stop = open_price < stop if direction == 1 else open_price > stop
                    exit_price = open_price if gap_through_stop else stop
                else:
                    exit_price = target
                exit_time = bar_time
                break
            close_price = float(bar["Close"])
            if (close_price - fill_price) * direction > 0:
                favorable_close_bars += 1
            outcome = "unresolved"

        if outcome == "take_profit" and tp2 is not None and not tp2_reached and exit_time is not None:
            after_exit_start = m15_bars.index.searchsorted(pd.Timestamp(exit_time), side="right")
            after_exit = m15_bars.iloc[after_exit_start:after_exit_start + max_holding_bars]
            for bar_time, bar in after_exit.iterrows():
                high = float(bar["High"])
                low = float(bar["Low"])
                if (high >= tp2 if direction == 1 else low <= tp2):
                    tp2_reached = True
                    tp2_reached_after_exit = True
                    tp2_after_exit_time = bar_time
                    break

        risk = abs(fill_price - stop) if fill_price is not None else None
        gross_r_multiple = None
        if exit_price is not None and risk:
            gross_r_multiple = round((exit_price - fill_price) * direction / risk, 4)
        r_multiple = (
            round(gross_r_multiple - transaction_cost_r, 4)
            if gross_r_multiple is not None
            else None
        )
        mfe_r = round(mfe_price / risk, 4) if fill_price is not None and risk else None
        mae_r = round(mae_price / risk, 4) if fill_price is not None and risk else None
        if fill_price is None:
            busy_until = decision_time + pd.Timedelta(minutes=15 * max_pending_bars)
        elif exit_time is not None:
            busy_until = pd.Timestamp(exit_time) + TIMEFRAME_DELTAS["M15"]
        elif not future.empty:
            busy_until = future.index[-1] + TIMEFRAME_DELTAS["M15"]
        outcomes.append({
            "fill_status": "filled" if fill_price is not None else "unfilled",
            "outcome": outcome,
            "fill_time": fill_time,
            "fill_price": fill_price,
            "exit_time": exit_time,
            "outcome_end_time": exit_time or last_evaluated_time,
            "exit_price": exit_price,
            "bars_held": bars_held,
            "gross_r_multiple": gross_r_multiple,
            "r_multiple": r_multiple,
            "mfe_price": round(mfe_price, 5) if fill_price is not None else None,
            "mae_price": round(mae_price, 5) if fill_price is not None else None,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "tp1_reached": tp1_reached if fill_price is not None else None,
            "tp2_reached": tp2_reached if fill_price is not None else None,
            "tp2_reached_after_exit": tp2_reached_after_exit if fill_price is not None else None,
            "tp2_after_exit_time": tp2_after_exit_time,
            "stop_reached": stop_reached if fill_price is not None else None,
            "favorable_close_bars": favorable_close_bars if fill_price is not None else None,
            "favorable_close_minutes": favorable_close_bars * 15 if fill_price is not None else None,
            "excursion_method": (
                "M15 OHLC extrema; fill candle included; intrabar path unknown"
                if fill_price is not None else None
            ),
        })

    outcome_frame = pd.DataFrame(outcomes, index=signals.index)
    result = pd.concat([signals.copy(), outcome_frame], axis=1)
    result.attrs.update(signals.attrs)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Chronologically replay the current strategy on archived candles"
    )
    parser.add_argument("--source", default="OANDA-PRACTICE")
    parser.add_argument("--symbol", default="XAU_USD")
    parser.add_argument("--output", default="signal_replay.csv")
    parser.add_argument("--from", dest="from_time", help="Optional UTC start timestamp")
    parser.add_argument("--to", dest="to_time", help="Optional UTC end timestamp")
    parser.add_argument("--holding-bars", type=int, default=96,
                        help="Maximum M15 bars to evaluate each signal (default: 96)")
    parser.add_argument("--pending-bars", type=int, default=4,
                        help="Maximum M15 bars to keep an unfilled setup actionable (default: 4)")
    parser.add_argument("--cost-r", type=float, default=0.0,
                        help="Round-trip costs as a fraction of initial risk; report sensitivity separately")
    args = parser.parse_args()

    init_db()
    h4 = load_market_bars(args.source, args.symbol, "H4")
    h1 = load_market_bars(args.source, args.symbol, "H1")
    m15 = load_market_bars(args.source, args.symbol, "M15")

    if any(frame.empty for frame in (h4, h1, m15)):
        parser.error(f"No archived candles found for source {args.source}")

    signals = replay_signals(
        h4,
        h1,
        m15,
        symbol=args.symbol,
        start_time=args.from_time,
        end_time=args.to_time,
        progress_every=5000,
    )
    signals = evaluate_signal_outcomes(
        signals,
        m15,
        args.holding_bars,
        max_pending_bars=args.pending_bars,
        transaction_cost_r=args.cost_r,
    )
    signals.to_csv(args.output, index=False)
    metadata_path = Path(args.output).with_suffix(".meta.json")
    metadata_path.write_text(json.dumps({
        "source": args.source,
        "symbol": args.symbol,
        "period_start": str(signals["decision_time"].min()) if not signals.empty else None,
        "period_end": str(signals["decision_time"].max()) if not signals.empty else None,
        "decision_count": signals.attrs.get("decision_count", 0),
        "duplicate_suppressed_count": signals.attrs.get("duplicate_suppressed_count", 0),
        "emitted_candidate_count": len(signals),
        "max_holding_bars": args.holding_bars,
        "max_pending_bars": args.pending_bars,
        "transaction_cost_r": args.cost_r,
        "timeframe_bars_closed_before_decision": True,
        "overlap_policy": "one open or pending position",
        "intrabar_policy": "M15 OHLC; stop-loss wins same-bar SL/TP1 collisions",
    }, indent=2), encoding="utf-8")
    print(f"Replay decisions: {signals.attrs.get('decision_count', 0)} M15 bars")
    print(f"Repeated candidates suppressed: {signals.attrs.get('duplicate_suppressed_count', 0)}")
    print(f"Signals: {len(signals)}")
    print(f"Signal report: {args.output}")
    print(f"Replay metadata: {metadata_path}")
    if not signals.empty:
        print("Signal counts:")
        print(signals.groupby(["signal_type", "grade"]).size().to_string())
        print("Outcome counts:")
        print(signals.groupby(["signal_type", "outcome"], dropna=False).size().to_string())
        resolved = signals[signals["outcome"].isin(["stop_loss", "take_profit"])]
        if not resolved.empty:
            win_rate = (resolved["outcome"] == "take_profit").mean()
            print(f"Resolved win rate: {win_rate:.1%}")
            print(f"Resolved mean net R: {resolved['r_multiple'].mean():.2f}")
            gross_mean = resolved["gross_r_multiple"].mean()
            print(f"Resolved mean gross R: {gross_mean:.2f}")
            print("Illustrative net mean R at costs of 0.05/0.10/0.20R: " + ", ".join(
                f"{gross_mean - cost:.2f}" for cost in (0.05, 0.10, 0.20)
            ))
        print(
            "Timeframe close checks: ",
            bool((signals["h4_last_closed"] + TIMEFRAME_DELTAS["H4"] <= signals["decision_time"]).all()),
            bool((signals["h1_last_closed"] + TIMEFRAME_DELTAS["H1"] <= signals["decision_time"]).all()),
            bool((signals["m15_last_closed"] + TIMEFRAME_DELTAS["M15"] <= signals["decision_time"]).all()),
        )
    print("Outcome estimates use M15 OHLC; when SL and TP1 occur in one bar, SL is counted first.")
    print("MFE/MAE use whole-bar extrema including the fill candle; intrabar ordering is unknown.")


if __name__ == "__main__":
    main()
