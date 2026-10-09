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
- if Ollama is offline or unreachable, the scanner falls back to a conservative NO_TRADE outcome
- AI does not place orders or control execution

### 3) Lifecycle persistence and audit trail
Each setup is now persisted with lifecycle metadata and AI decision metadata.

Persisted columns include:
- lifecycle_state
- lifecycle_reason
- reviewed_at
- ai_decision
- ai_quality_score
- ai_confidence
- ai_summary
- ai_reasons
- ai_invalidations
- ai_risk_note
- ai_reviewed_at

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

This project is currently in a partially validated state, not a fully green one.

Verified from the active project environment on 2026-10-09:
- the repository virtual environment is active and dependencies are installed
- the current regression run is: 78 passed, 6 failed in 1.71s
- the failures are concentrated in the lifecycle/state validation path and one simulation-risk test

The current blockers are real and should be treated as the active baseline for the next agent:
- `tests/test_signal_lifecycle.py` is failing because the lifecycle evaluator is returning `INVALIDATED` before precedence checks for `NEWS BLOCKED`, `READY`, and clear invalidation reasons are reached
- the reason strings for invalidation are not matching the expected wording (`minimum grade`, `below 1:1`, `stop-loss`)
- `tests/test_main_simulation_risk.py` is failing because `main.save_broker_account_snapshot` is missing from the module even though the test patches it

This means the project has working core components, but the state machine and risk-account integration are not yet fully aligned with the expected contract.

---

## What the next agent should focus on

### Highest-priority next step
Repair the failing lifecycle and simulation-risk tests before expanding feature work.

The next milestone should be:
1. fix the `evaluate_setup` precedence so `NEWS BLOCKED` and `READY` states can win when appropriate
2. correct lifecycle invalidation reason strings and grade/rr/stop validation logic to match the test contract
3. restore the missing broker-account snapshot API expected by the simulation-risk test
4. rerun the suite in the project venv and confirm the project is green before adding more lifecycle features

This is the correct next step because the scanner already has detection, duplicate suppression, AI review support, and persistence. The current weak point is not market analysis itself; it is the contract between state evaluation, risk gating, and test expectations.

### Secondary priorities
- add richer lifecycle outcome tracking once the current state engine is green
- add dashboard visibility for AI verdicts and setup age
- add stronger review labels for manually dismissed setups
- tune scoring thresholds via backtesting and comparison, not guesses
- evaluate demo/manual trade testing only if the operator explicitly approves it

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
- [dashboard/signal_lifecycle.py](dashboard/signal_lifecycle.py)
- [dashboard/app.py](dashboard/app.py)
- [tests/test_signal_generation.py](tests/test_signal_generation.py)
- [tests/test_ai_advisor.py](tests/test_ai_advisor.py)
- [tests/test_setup_signal_type.py](tests/test_setup_signal_type.py)

---

## Validation note

The current implementation is not fully green yet. The verified baseline from the project venv is:
- 78 passed
- 6 failed
- failing areas are lifecycle precedence logic and simulation-risk integration

This is the current working baseline for the next AI agent.
- activate the project venv before running tests: `. .venv/bin/activate`
- verify with `pytest -q` from the repo root
- prioritize the failing lifecycle/risk contracts before adding more feature work
- keep duplicates suppressed, state transitions auditable, and AI advisory-only
- evaluate the system using expectancy, drawdown, and duplicate suppression metrics once the current regressions are resolved

---

## Required output objects

The system should eventually produce or store structured setup records including:

- timestamp
- symbol
- direction
- setup_id
- zone
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

At this point, the project has already taken the first step:
- duplicate same-idea setup guard implemented and regression-tested

The next required step is the explicit lifecycle state engine and new setup gate.

That is the next milestone.
