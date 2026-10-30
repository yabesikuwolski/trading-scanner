# OANDA XAU/USD Full-History Replay

Generated from `reports/oanda_full_history_replay_2023-2026.csv`.
Period represented by candidate records: 2023-07-19T05:15:00+00:00 to 2026-09-29T11:30:00+00:00.
Replay decisions evaluated: 76426; repeated candidates suppressed: 28548.

## Replay assumptions

- The analyzer uses only H4/H1/M15 candles that have closed by each M15 decision time.
- One pending or open position at a time; unfilled entries expire after the configured pending window.
- Same-bar SL/TP1 collisions count as stop loss; modeled fills include favorable limit gaps and adverse stop gaps.
- MFE/MAE use full M15 OHLC extrema including the fill candle. Intrabar path and fill ordering are unknown.
- Favorable time is counted from M15 candle closes beyond entry, not continuous time in profit.
- TP2 reached after the modeled TP1 exit is reported as follow-through, not as profit captured by the modeled trade.
- Broker spread, commission, financing, slippage, margin, and manual execution delay are not modeled.

## Coverage and outcomes

- Candidate outcomes: {"overlap_blocked": 15758, "stop_loss": 708, "take_profit": 356, "unfilled": 4482, "unresolved": 249}.
- Resolved trades: 356 wins and 708 losses of 1064 resolved outcomes (33.5% resolved-only win rate).
- Mean resolved gross R: +0.02R; mean MFE: +1.82R; mean MAE: +1.65R.
- TP2 reached after the modeled TP1 exit: 258 (follow-through only; not included in modeled trade R).

## Chronological split

Development outcomes crossing the 2025-10-01T00:00:00+00:00 boundary are excluded (1 candidates); the maximum replay horizon is 96 bars. Holdout start: 2025-10-01T00:00:00+00:00. This split was selected after prior inspection of the full-history report, so it is retrospective and not a pristine untouched holdout. Do not tune against it; collect a future forward sample.

| Segment | Candidates | Filled | Resolved | Wins | Win rate | Mean gross R |
|---|---|---|---|---|---|---|
| development segment | 14827 | 912 | 739 | 240 | 32.5% | -0.01R |
| chronological holdout | 6725 | 400 | 324 | 115 | 35.5% | +0.08R |

## Results by year

| Year | Resolved | Wins | Win rate | Mean gross R |
|---|---|---|---|---|
| 2023 | 160 | 68 | 42.5% | +0.27R |
| 2024 | 338 | 97 | 28.7% | -0.11R |
| 2025 | 320 | 108 | 33.8% | +0.02R |
| 2026 | 246 | 83 | 33.7% | +0.03R |

## Results by signal type

| Signal type | Resolved | Wins | Win rate | Mean gross R |
|---|---|---|---|---|
| BUY LIMIT | 463 | 159 | 34.3% | +0.06R |
| BUY STOP | 25 | 6 | 24.0% | -0.28R |
| MARKET/IMMEDIATE | 230 | 82 | 35.7% | +0.11R |
| SELL LIMIT | 317 | 100 | 31.5% | -0.06R |
| SELL STOP | 29 | 9 | 31.0% | -0.11R |

## H4 trend and M15 volatility regimes

ATR tercile boundaries (2.24393, 3.66679) are estimated from candidate ATR values before the holdout start. These buckets describe this sample and do not change signal decisions.

| Regime | Candidates | Resolved | Win rate | Mean gross R |
|---|---|---|---|---|
| trend_regime: bullish | 12737 | 627 | 34.6% | +0.06R |
| trend_regime: bearish | 8816 | 437 | 31.8% | -0.05R |
| trend_regime: neutral | 0 | 0 | — | — |
| volatility_regime: low ATR | 4945 | 292 | 33.9% | +0.02R |
| volatility_regime: mid ATR | 4979 | 246 | 30.9% | -0.06R |
| volatility_regime: high ATR | 11629 | 526 | 34.4% | +0.05R |

## Cost sensitivity

| Assumed round-trip cost | Mean resolved net R |
|---|---|
| 0.00R | +0.02R |
| 0.05R | -0.03R |
| 0.10R | -0.08R |
| 0.20R | -0.18R |

The fixed costs above are sensitivity cases, not broker-specific estimates. Resolved-only metrics exclude overlap-blocked, unfilled, and unresolved candidates; they do not represent returns on all emitted signals or account equity.
