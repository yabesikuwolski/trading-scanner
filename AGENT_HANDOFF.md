# SOLID XAUUSD SCAN AND ALERT RICHSCHEME 001

## Current project goal

This project is a conservative, structure-first XAUUSD scanner for setup discovery and alerting. It is designed to identify valid market structure setups, suppress duplicate repeated versions of the same trade idea, and support trader decision-making without becoming an automated execution system.

The scanner does not aim to trade live by default. It aims to produce high-quality, reviewable setups with state tracking, AI review support, and clear auditability.

---

## What has been implemented

### 1) Setup-state and duplicate suppression
The scanner now blocks repeated same-idea entries using a setup-state logic layer.

Core files:
- scanner/setup_state.py
- main.py
- database/db_manager.py

This prevents near-identical signal re-entry where:
- same symbol
- same direction
- same zone
- tiny price drift
- active or invalidated setup state

are treated as duplicate noise rather than a new opportunity.

### 2) AI advisory layer without execution
The project includes a local Ollama-based AI review flow that acts as a second opinion only.

Core files:
- scanner/ai_advisor.py
- config.py

Behavior:
- AI is enabled through config flags
- model calls are local and advisory-only
- if Ollama is offline, the review is stored as `unavailable`; malformed output is `invalid_response`; neither state invents a verdict
- AI does not place orders or control execution
- AI output does not gate qualified signals or override risk sizing, lifecycle, entry, SL, or TP
- model output is validated against the required JSON schema before it is stored as an available review

### 3) Lifecycle persistence and audit trail
Each setup is now persisted with lifecycle metadata and AI decision metadata.

Persisted columns include:
- lifecycle_state
- lifecycle_reason
- entry_touched_at (price touch only; not a broker fill)
- reviewed_at
- ai_status
- ai_decision
- ai_quality_score
- ai_confidence
- ai_summary
- ai_reasons
- ai_invalidations
- ai_risk_note
- ai_reviewed_at
- telegram_status / telegram_error / telegram_attempted_at / telegram_sent_at
- lifecycle Telegram delivery status and timestamp
- trade gross R, MFE/MAE, target/stop touches, and OHLC excursion provenance

This creates an auditable trail for every setup and lets the next agent reason about why a setup was accepted, ignored, invalidated, or reviewed.

### 4) Stateful trade and setup review flow
The system can now support a trader-facing review model where a setup is tracked as it evolves from detection to completion, instead of being treated as a one-time event.

Related files:
- database/db_manager.py
- dashboard/signal_lifecycle.py
- dashboard/app.py

---

## Architectural rule

The project must remain advisory-first and conservative.

The scanner should be treated as a decision-support engine, not as a live broker automation layer.

This means:
- setup quality matters more than signal count
- duplicate setups are rejected aggressively
- AI is used for review and explanation
- the human remains the final decision-maker
- demo or test execution should be isolated and manual, not the core path

---

## Current working baseline

Verified on 2026-10-16 after signal ledger and trade execution-record updates:
- full regression suite: `.venv/bin/pytest -q` — 140 passed, 7 subtests passed
- the tracked provider default is BiQuote, but the ignored local `.env` currently selects `DERIV_DEMO`; AI is currently disabled in this workspace (`AI_ADVISOR_ENABLED=false`)
- the scanner checks risk against the persistent simulation account and records provider-account metadata separately
- simulation sizing plans, setup identity/zone, and optional AI advisory results are stored with signals
- the latest persisted setup is checked before a repeated alert is emitted
- AI remains disabled by default and never overrides scoring, lifecycle, or risk checks. A live local `llama3.2:3b` strict-schema smoke check returned a valid `WATCH` review: 58.89 seconds cold and 12.03 seconds warm. The configured default timeout is 75 seconds to accommodate the observed cold start; an enabled review runs synchronously and can pause the scan.
- the qwen2.5 model named in an earlier environment was not installed; the installed local default is `llama3.2:3b`
- Telegram delivery and lifecycle update results are persisted, but no local bot token/chat ID is configured for a real delivery check
- account feasibility remains `UNKNOWN` when margin, verified broker specifications, or currency conversion data are unavailable
- full replay: 76,426 M15 decisions; 28,548 repeated candidates suppressed; 21,553 candidates; 15,758 overlap-blocked; 4,482 unfilled; 249 unresolved; 1,064 resolved (356 TP1, 708 SL), 33.5% resolved-only win rate, +0.02R mean gross. An illustrative 0.05R cost changes the mean to -0.03R. The run took roughly 20 minutes and used about one CPU core in this workspace. See `reports/oanda_full_history_replay_2023-2026.md` and its CSV/metadata.
- Signal Ledger is implemented. Each setup has an append-only decision history (`PAPER_TRACKED`, `SKIPPED` with reason, or `TRADE_LOGGED`; no event means `UNREVIEWED`) and a separate modeled-outcome record. The scanner evaluates up to 100 pending setups per scan from configured-source M15 OHLC, with four pending bars and a 96-bar horizon. These are hypothetical per-signal scenarios, independent of the replay overlap limit, separate from manual journal outcomes, and do not confirm fills or include costs.
- Dashboard users can inspect the latest 2,000 setups on the Signal Ledger page, paper-track or skip a setup, and compare modeled OHLC results with linked journal results. Paper net R and manually reported net R are summarized separately. A journal link is user-reported; broker execution is not independently verified.
- Trade Journal now distinguishes `PAPER`, `MANUAL_REPORTED`, and migrated legacy `UNSPECIFIED` records. It accepts entry time, position size, reported risk amount/currency, and total transaction costs/currency. Gross R is price-based; net R is calculated only when risk and costs share a currency. Recorded costs in the simulation-account currency reduce paper P/L. Manually reported trades and losses are excluded from the simulation balance and consecutive-loss gate. Old records remain classified `UNSPECIFIED` after migration.
- The scanner was restarted on 2026-10-16 using the updated code. Two consecutive scans each updated 23 pending modeled outcomes from `DERIV-DEMO`; each batch left 20 in `MODELED_OPEN` and 3 in `WAITING_FOR_BARS`, with no terminal resolutions. One `main.py` process was confirmed running. A Streamlit dashboard is also running at `http://127.0.0.1:8501`. Continue using these processes and avoid starting duplicates. `init_db()` applies additive action/outcome and trade-metadata migrations at startup.

The scanner remains advisory-only. Passing tests checks implementation behavior; it does not establish predictive performance or live-trading readiness.

---

## What the next agent should focus on

### Next priorities
1. Use the Signal Ledger consistently: paper-track or skip signals, and log taken trades from their setup cards so results stay linked. Record actual entry time, size, risk, and total costs when known.
2. Replace illustrative research costs with broker-specific spread, commission, financing, margin, and slippage assumptions. Net R remains unavailable on trades missing risk or cost data.
3. Run a genuinely forward chronological sample. The retrospective split is not untouched because the complete archive was already reviewed.
4. Configure Telegram locally and verify one real delivery. Keep all outcomes labeled as estimates unless broker fills are confirmed.

---

## Rules for future work

### Always do this
- keep the scanner advisory-only
- preserve the duplicate suppression model
- persist lifecycle transitions in SQLite
- store AI reasoning and decision metadata with each setup
- validate with targeted unit tests before claiming the system is stable

### Never do this
- do not auto-execute trades from the core scanner path
- do not let AI override the state machine without validation
- do not treat small entry drift as a new setup
- do not remove the local offline fallback path
- do not claim the system is ready for live trading without human review and full validation

---

## Important files

- [config.py](config.py)
- [main.py](main.py)
- [database/db_manager.py](database/db_manager.py)
- [scanner/setup_state.py](scanner/setup_state.py)
- [scanner/ai_advisor.py](scanner/ai_advisor.py)
- [scanner/setup_outcome_tracker.py](scanner/setup_outcome_tracker.py)
- [dashboard/signal_lifecycle.py](dashboard/signal_lifecycle.py)
- [dashboard/app.py](dashboard/app.py)
- [tests/test_signal_generation.py](tests/test_signal_generation.py)
- [tests/test_ai_advisor.py](tests/test_ai_advisor.py)
- [tests/test_setup_outcome_tracker.py](tests/test_setup_outcome_tracker.py)
- [tests/test_setup_signal_type.py](tests/test_setup_signal_type.py)

---

## Validation note

- The latest verified suite result is 140 passed and 7 subtests passed on 2026-10-16; rerun `.venv/bin/pytest -q` after code changes.
- Regression coverage includes repeat suppression across separate scan calls and expiry of old dedup candidates.
- Full OANDA replay output and assumptions are recorded in `reports/oanda_full_history_replay_2023-2026.md` and its CSV.
- Local AI smoke check: `llama3.2:3b` returned a valid strict-schema `WATCH` review (58.89 seconds cold, 12.03 seconds warm); the default timeout is 75 seconds and AI is disabled by default.
- The local workspace has no Telegram bot token/chat ID configured, so mocked delivery/failure tests pass but real Telegram delivery remains unverified.
- The project contains no order-submission path; all alerts and dashboard outputs remain advisory scenarios.
- Dedicated ledger tests cover action history, linked journal trades, pending/unfilled estimates, same-bar stop priority, and existing trade-link migration.
- Journal tests cover reported-versus-paper separation, same-currency net R and simulation costs, mismatched currencies, entry-time normalization, and additive migration.
- A `main.py` process from before the ledger work was left untouched; check the process list before launching another scanner instance.
- keep duplicates suppressed, state transitions auditable, and AI advisory-only
- evaluate the system using expectancy, drawdown, and duplicate suppression metrics; test success alone is not strategy validation

---

## Required output objects

The system should eventually produce or store structured setup records including:

- timestamp
- symbol
- direction
- setup_id
- zone
- entry trigger time, when observed
- entry
- sl
- tp1
- tp2
- 4H bias
- 1H zone
- liquidity event
- 15M confirmation
- score
- RR
- lifecycle state
- outcome
- max favorable excursion
- max adverse excursion
- gross R and net R only when costs are known
- exit reason and whether TP1/TP2/SL levels were reached

This will allow proper analysis of why a trade won or lost.

---

## Recommended working policy

The project should remain intentionally conservative:
- no auto-trade core
- manual decision-making with support from tooling
- AI used for analysis and explanation, not execution
- zero-cost local AI is acceptable for supporting analysis

This is the best realistic architecture before moving into any serious forward-testing or demo automation.

---

## Final objective

The final system behavior should look like this:

- scanner checks every 60 seconds
- if same setup is still active: silent
- if new structure and new zone appear: signal
- if trade ends: cooldown / re-evaluation
- if new setup appears later: new trade

The purpose is not to never lose. The purpose is to avoid turning one losing idea into multiple repeated losses.

---

## Implementation status

The persistent simulation-risk gate, account-feasibility labels, strict AI review state, Telegram delivery tracking, setup lifecycle notifications, and scanner-side repeated-setup check are integrated. Setup zones include FVG bounds, H1 swing levels, or retest levels. Replay now adds MFE/MAE and TP2 follow-through diagnostics, with report generation and chronological/regime summaries. Broker-specific costs and margin, live Telegram delivery, and a clean forward sample remain open.
