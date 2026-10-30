"""Build a compact, reproducible Markdown summary from signal_replay.py outputs."""

import argparse
import json
from pathlib import Path

import pandas as pd


RESOLVED = {"stop_loss", "take_profit"}


def summarize(frame, label):
    resolved = frame[frame["outcome"].isin(RESOLVED)]
    wins = int((resolved["outcome"] == "take_profit").sum())
    return {
        "label": label,
        "candidates": len(frame),
        "filled": int((frame["fill_status"] == "filled").sum()),
        "resolved": len(resolved),
        "wins": wins,
        "losses": int((resolved["outcome"] == "stop_loss").sum()),
        "win_rate": wins / len(resolved) if len(resolved) else None,
        "gross_r": resolved["gross_r_multiple"].mean() if len(resolved) else None,
        "mfe_r": resolved["mfe_r"].mean() if len(resolved) else None,
        "mae_r": resolved["mae_r"].mean() if len(resolved) else None,
    }


def markdown_table(rows, columns):
    if not rows:
        return "(no data)"
    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    lines = [header, separator]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "—")) for column in columns) + " |")
    return "\n".join(lines)


def format_metric(value, percent=False):
    if pd.isna(value):
        return "—"
    return f"{value:.1%}" if percent else f"{value:+.2f}R"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--holdout-start", default="2025-10-01T00:00:00Z")
    parser.add_argument("--illustrative-costs", default="0.05,0.10,0.20")
    args = parser.parse_args()

    frame = pd.read_csv(args.csv, parse_dates=["decision_time", "fill_time", "exit_time", "outcome_end_time"])
    for column in ("decision_time", "fill_time", "exit_time", "outcome_end_time"):
        if frame[column].dt.tz is None:
            frame[column] = frame[column].dt.tz_localize("UTC")
    metadata_path = args.metadata or args.csv.with_suffix(".meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    holdout_start = pd.Timestamp(args.holdout_start)
    if holdout_start.tzinfo is None:
        holdout_start = holdout_start.tz_localize("UTC")
    else:
        holdout_start = holdout_start.tz_convert("UTC")
    max_holding_bars = int(metadata.get("max_holding_bars", 96))
    training_mask = (
        (frame["decision_time"] < holdout_start)
        & frame["outcome_end_time"].notna()
        & (frame["outcome_end_time"] < holdout_start)
    )
    training = frame[training_mask].copy()
    training_excluded = int(((frame["decision_time"] < holdout_start) & ~training_mask).sum())
    holdout = frame[frame["decision_time"] >= holdout_start].copy()

    atr_train = pd.to_numeric(training["atr14_m15"], errors="coerce").dropna()
    q1 = atr_train.quantile(1 / 3) if not atr_train.empty else float("nan")
    q2 = atr_train.quantile(2 / 3) if not atr_train.empty else float("nan")
    atr_all = pd.to_numeric(frame["atr14_m15"], errors="coerce")
    if pd.notna(q1) and pd.notna(q2) and q1 < q2:
        frame["volatility_regime"] = pd.cut(
            atr_all, bins=[float("-inf"), q1, q2, float("inf")],
            labels=["low ATR", "mid ATR", "high ATR"], include_lowest=True,
        )
    else:
        frame["volatility_regime"] = "unknown"

    outcome_counts = frame["outcome"].value_counts(dropna=False).to_dict()
    full = summarize(frame, "full period")
    train_stats = summarize(training, "development segment")
    holdout_stats = summarize(holdout, "chronological holdout")
    resolved = frame[frame["outcome"].isin(RESOLVED)]
    costs = [float(value.strip()) for value in args.illustrative_costs.split(",") if value.strip()]
    year_rows = []
    for year, group in frame.groupby(frame["decision_time"].dt.year):
        stats = summarize(group, str(year))
        year_rows.append({
            "Year": year,
            "Resolved": stats["resolved"],
            "Wins": stats["wins"],
            "Win rate": format_metric(stats["win_rate"], percent=True),
            "Mean gross R": format_metric(stats["gross_r"]),
        })
    type_rows = []
    for signal_type, group in frame.groupby("signal_type"):
        stats = summarize(group, signal_type)
        type_rows.append({
            "Signal type": signal_type,
            "Resolved": stats["resolved"],
            "Wins": stats["wins"],
            "Win rate": format_metric(stats["win_rate"], percent=True),
            "Mean gross R": format_metric(stats["gross_r"]),
        })

    period = (
        f"{frame['decision_time'].min().isoformat()} to {frame['decision_time'].max().isoformat()}"
        if not frame.empty else "no candidate rows"
    )
    lines = [
        "# OANDA XAU/USD Full-History Replay",
        "",
        f"Generated from `{args.csv}`.",
        f"Period represented by candidate records: {period}.",
        f"Replay decisions evaluated: {metadata.get('decision_count', 'not available')}; "
        f"repeated candidates suppressed: {metadata.get('duplicate_suppressed_count', 'not available')}.",
        "",
        "## Replay assumptions",
        "",
        "- The analyzer uses only H4/H1/M15 candles that have closed by each M15 decision time.",
        "- One pending or open position at a time; unfilled entries expire after the configured pending window.",
        "- Same-bar SL/TP1 collisions count as stop loss; modeled fills include favorable limit gaps and adverse stop gaps.",
        "- MFE/MAE use full M15 OHLC extrema including the fill candle. Intrabar path and fill ordering are unknown.",
        "- Favorable time is counted from M15 candle closes beyond entry, not continuous time in profit.",
        "- TP2 reached after the modeled TP1 exit is reported as follow-through, not as profit captured by the modeled trade.",
        "- Broker spread, commission, financing, slippage, margin, and manual execution delay are not modeled.",
        "",
        "## Coverage and outcomes",
        "",
        f"- Candidate outcomes: {json.dumps({str(key): int(value) for key, value in outcome_counts.items()}, sort_keys=True)}.",
        f"- Resolved trades: {full['wins']} wins and {full['losses']} losses of {full['resolved']} resolved outcomes "
        f"({format_metric(full['win_rate'], percent=True)} resolved-only win rate).",
        f"- Mean resolved gross R: {format_metric(full['gross_r'])}; mean MFE: {format_metric(full['mfe_r'])}; "
        f"mean MAE: {format_metric(full['mae_r'])}.",
        f"- TP2 reached after the modeled TP1 exit: {int(((frame['tp2_reached_after_exit'] == True) & (frame['outcome'] == 'take_profit')).sum())} "
        "(follow-through only; not included in modeled trade R).",
        "",
        "## Chronological split",
        "",
        f"Development outcomes crossing the {holdout_start.isoformat()} boundary are excluded "
        f"({training_excluded} candidates); the maximum replay horizon is {max_holding_bars} bars. "
        f"Holdout start: {holdout_start.isoformat()}. This split was selected after prior inspection of the full-history report, "
        "so it is retrospective and not a pristine untouched holdout. Do not tune against it; collect a future forward sample.",
        "",
        markdown_table([
            {
                "Segment": stats["label"],
                "Candidates": stats["candidates"],
                "Filled": stats["filled"],
                "Resolved": stats["resolved"],
                "Wins": stats["wins"],
                "Win rate": format_metric(stats["win_rate"], percent=True),
                "Mean gross R": format_metric(stats["gross_r"]),
            }
            for stats in (train_stats, holdout_stats)
        ], ["Segment", "Candidates", "Filled", "Resolved", "Wins", "Win rate", "Mean gross R"]),
        "",
        "## Results by year",
        "",
        markdown_table(year_rows, ["Year", "Resolved", "Wins", "Win rate", "Mean gross R"]),
        "",
        "## Results by signal type",
        "",
        markdown_table(type_rows, ["Signal type", "Resolved", "Wins", "Win rate", "Mean gross R"]),
        "",
        "## H4 trend and M15 volatility regimes",
        "",
        f"ATR tercile boundaries ({q1:.5f}, {q2:.5f}) are estimated from candidate ATR values before the holdout start. "
        "These buckets describe this sample and do not change signal decisions.",
        "",
    ]

    regime_rows = []
    for column, labels in (("trend_regime", ["bullish", "bearish", "neutral"]),
                           ("volatility_regime", ["low ATR", "mid ATR", "high ATR"])):
        for label in labels:
            subset = frame[frame[column].astype("string") == label]
            stats = summarize(subset, label)
            regime_rows.append({
                "Regime": f"{column}: {label}",
                "Candidates": stats["candidates"],
                "Resolved": stats["resolved"],
                "Win rate": format_metric(stats["win_rate"], percent=True),
                "Mean gross R": format_metric(stats["gross_r"]),
            })
    lines.append(markdown_table(regime_rows, ["Regime", "Candidates", "Resolved", "Win rate", "Mean gross R"]))
    lines.extend(["", "## Cost sensitivity", ""])
    cost_rows = []
    gross_mean = resolved["gross_r_multiple"].mean() if not resolved.empty else float("nan")
    for cost in [0.0, *costs]:
        cost_rows.append({
            "Assumed round-trip cost": f"{cost:.2f}R",
            "Mean resolved net R": format_metric(gross_mean - cost),
        })
    lines.append(markdown_table(cost_rows, ["Assumed round-trip cost", "Mean resolved net R"]))
    lines.extend([
        "",
        "The fixed costs above are sensitivity cases, not broker-specific estimates. Resolved-only metrics exclude overlap-blocked, "
        "unfilled, and unresolved candidates; they do not represent returns on all emitted signals or account equity.",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
