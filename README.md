# SOLID XAU/USD Scanner

SOLID is a Python market-scanning and trade-review workspace for XAU/USD. It reads market data, analyzes H4/H1/M15 structure with M5 entry confirmation, records conditional setup ideas in SQLite, and presents them in a Streamlit dashboard. It is intended for manual decision support. It does not submit, modify, or close broker orders, and it cannot confirm that a setup was filled.

## What runs today

The live scanner in `main.py` repeatedly fetches XAUUSD candles, validates their timestamps and OHLC values, archives them, analyzes the market, and logs a summary. H4 supplies directional bias, H1 supplies confirmation and structure, M15 forms a setup candidate, and a verified completed M5 candle must break the preceding M5 candle's high or low with sufficient body and valid stop geometry before the scanner issues an actionable entry alert. Missing, stale, unverified, or unconfirmed M5 data prevents setup persistence and entry alerts. BiQuote supports M5. The optional Deriv demo connector supports only M15, H1, and H4, so selecting it leaves the scanner safely paused for missing M5 data.

The baseline analysis uses H4 EMA bias; H1 swings, breaks of structure, and liquidity sweeps; and M15 fair value gaps, retests, rejection candles, and entry/stop/target geometry. The phone channel sends only `ENTRY SIGNAL CONFIRMED`, and only for a candidate passing H4, H1, M15, and the verified completed-M5 breakout. The alert includes direction, levels, risk/reward, and rationale. Developing setups and lifecycle events remain local diagnostics. These describe hypothetical entry conditions, not broker orders. Invalid level geometry is rejected.

The scanner checks candle quality and age, a persistent simulation-account risk gate, duplicate setup identity, optional economic-news blackout, and alert cooldowns. It stores accepted setups, chart paths, risk-sizing scenarios, optional AI review, and notification status. Undelivered qualified entries are retried after a five-minute backoff while still inside the setup age window. Startup, market-data, risk, news, M5-wait, and lifecycle messages are written to local logs rather than the phone channel. A price touching an entry is not evidence of a broker fill.

## Components

| Area | What it does |
| --- | --- |
| `main.py` | Live scan loop, data-quality checks, analysis, deduplication, risk gating, persistence, and notifications |
| `scanner/data_provider.py` | Selects the configured read-only provider |
| `scanner/mt5_connector.py` | Legacy filename; currently the BiQuote REST OHLC and quote adapter. It does not connect to MetaTrader 5. |
| `scanner/deriv_connector.py` | Optional Deriv demo read-only market-data/account connector |
| `scanner/market_analyzer.py`, `scanner/scoring_engine.py` | Multi-timeframe setup analysis, levels, and scoring |
| `scanner/m5_strategy.py` | Closed-candle M5 trigger that qualifies and prices actionable entries |
| `scanner/setup_state.py`, `dashboard/signal_lifecycle.py` | Duplicate identity and observed setup lifecycle rules |
| `scanner/ai_advisor.py` | Optional local Ollama review, schema-validated and advisory only |
| `scanner/news_filter.py` | Optional economic-calendar blackout filter |
| `risk/risk_manager.py` | Simulation risk checks and hypothetical sizing plan |
| `database/db_manager.py` | SQLite storage for setups, candles, risk/account snapshots, decisions, modeled outcomes, and journal records |
| `dashboard/app.py` | Streamlit dashboard, setup ledger, journal, analytics, daily review, and risk status |
| `alerts/notifier.py`, `alerts/telegram_bot.py` | ntfy/Discord transport and alert formatting |
| `scanner/oanda_connector.py` | Read-only OANDA practice candle fetch and history archive utility; not the live scanner's selected provider |
| `scanner/csv_market_data.py`, `scanner/import_market_csv.py` | Normalize and import broker-exported OHLC CSV data into source-separated candle storage |
| `scanner/signal_replay.py` | Historical, chronological signal replay and approximate OHLC outcome analysis |

The database is created at `DB_PATH` (default `trading_scanner.db`). It is migrated in place as fields are added. Keep the database and generated artifacts backed up if you need their history.

## Setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` for your environment. Do not commit credentials. The tracked default is `MARKET_DATA_PROVIDER=BIQUOTE`. The scanner also supports `DERIV_DEMO`; it requires the corresponding Deriv API token, app ID, and demo account configuration. The active provider is selected at process start. OANDA credentials are used by the separate OANDA archive utility, not by the live scanner selector.

The repository's local `.env` is intentionally untracked and may differ from `.env.example` or the code defaults. Check `MARKET_DATA_PROVIDER` and other local settings before running this workspace.

## Running

Start the scanner loop:

```bash
source .venv/bin/activate
python main.py
```

Start the dashboard in a second terminal:

```bash
source .venv/bin/activate
streamlit run dashboard/app.py
```

The dashboard includes Dashboard, Economic Calendar, Active Setups, Signal Ledger, Trade Journal, Analytics, Daily Review, and Risk Status pages. The Signal Ledger separates a hypothetical candle-based outcome from the user's decision and any separately journaled result. Paper journal entries and manually reported trades are distinguished; manually reported trades are user supplied and are not independently verified.

## Configuration

Common settings are in `.env.example` and `config.py`:

| Setting | Purpose |
| --- | --- |
| `MARKET_DATA_PROVIDER` | `BIQUOTE` (default) or `DERIV_DEMO` |
| `SCAN_INTERVAL` | Seconds between live scans; default 60 |
| `MAX_SETUP_AGE_MINUTES` | Setup deduplication/lifecycle age window; default 60 |
| `MAX_MARKET_BAR_AGE_MINUTES` | Extra permitted candle age beyond its timeframe; default 30 |
| `DB_PATH` | SQLite file location |
| `NOTIFICATION_PROVIDER` | `NTFY` (default) or `DISCORD`; configure the matching topic or webhook |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Direct Telegram adapter credentials; the live scanner notifier uses `NOTIFICATION_PROVIDER` (ntfy or Discord) |
| `NEWS_FILTER_ENABLED` | Enable the calendar blackout check; default true |
| `AI_ADVISOR_ENABLED` | Enable local Ollama review; default false |
| `SIMULATION_ACCOUNT_BALANCE`, `SIMULATION_ACCOUNT_CURRENCY` | Starting simulation-account baseline |
| `MAX_RISK_PER_TRADE`, `MAX_DAILY_DRAWDOWN`, `MAX_WEEKLY_DRAWDOWN`, `MAX_CONSECUTIVE_LOSSES` | Simulation risk thresholds |
| `XAUUSD_CONTRACT_SIZE`, `BROKER_MIN_VOLUME`, `BROKER_VOLUME_STEP`, `BROKER_MAX_VOLUME` | Optional user-entered sizing assumptions; verify them against the intended broker |

Provider account balance/equity, when available, is stored as account metadata. Scanner drawdown checks use the persistent simulation account. Position size and account feasibility can remain unknown because contract rules, margin, conversion, and broker-specific specifications are not necessarily available or verified.

Signal notifications use the configured ntfy topic or Discord webhook. Confirmed entries receive high ntfy priority. Local logging and persistence remain useful when delivery fails; the scanner records the failure and retries an eligible confirmed entry after five minutes. A configured endpoint and a subscribed phone client are still required for actual phone delivery.

## Candle archive and research tools

Each live scan stores its candles in `market_bars`, keyed by source, symbol, timeframe, and UTC open time. Repeated timestamps update existing rows, which allows the currently forming candle to be refreshed. Broker CSV imports use a source label so feeds remain distinguishable:

```bash
python -m scanner.import_market_csv path/to/export.csv \
  --symbol XAUUSD --timeframe M15 --source MY_BROKER \
  --timezone Europe/Athens
```

Supply `--timezone` when CSV timestamps do not include a UTC offset. Omit it for timestamps that already specify a timezone. Supported CSVs need timestamp (or date and time) plus open, high, low, and close columns; volume is optional.

Fetch recent complete OANDA practice candles or backfill a date range (requires `OANDA_API_TOKEN`):

```bash
python -m scanner.oanda_connector --timeframes H4 H1 M15 --count 200
python -m scanner.oanda_connector --timeframes M15 --from 2023-07-06T00:00:00Z --to 2026-09-29T00:00:00Z
```

The OANDA adapter only requests candles and stores them under `OANDA-PRACTICE`; it has no order-submission path. Historical replay reads source-separated archived candles. See `reports/oanda_full_history_replay_2023-2026.md`, its CSV, and metadata for the recorded OANDA replay and its assumptions.

Replay the archived H4/H1/M15 data into a CSV (the source must already exist in the local database):

```bash
python -m scanner.signal_replay \
  --source OANDA-PRACTICE --symbol XAU_USD \
  --from 2023-07-06T00:00:00Z --to 2026-09-29T00:00:00Z \
  --output signal_replay.csv
```

BiQuote's OHLC endpoint is a rolling window rather than a deep historical archive. Repeated live polling can build a forward local archive, but the available feed history is not by itself a multi-year backtest dataset. OANDA practice candles, broker CSVs, and BiQuote candles have different feed provenance and should not be treated as interchangeable prices.

## Research limits

The stored full-history replay is an exploratory retrospective study, not evidence of profitability or a clean out-of-sample result. Its outcomes are estimated from OHLC candles: pending-entry timing, same-candle stop/target ordering, spread, commission, slippage, swaps, liquidity, margin, and broker execution may differ from real trading. The report documents the sample, filters, and cost sensitivity. A chronological split was added after the report had already been inspected, so it is not an untouched holdout. Forward observation and broker-specific cost assumptions are still needed.

Signal Ledger modeled outcomes are also hypothetical per-setup M15 candle scenarios (configured source, up to four pending bars and a 96-bar horizon). They are independent of portfolio overlap and journal records; they do not model all execution costs or confirm fills. Paper trade records are simulations. Manual trade records are self-reported.

## Tests

Run the current test suite with:

```bash
.venv/bin/pytest -q
```

The latest full run reported 165 passed and 7 subtests passed. Tests cover connector behavior, candle normalization and persistence, setup generation and lifecycle, replay timing/outcomes, risk/account separation, journal flows, dashboard views, M5 confirmation, and staged notification routing. Passing tests validate code paths, not trading performance, provider uptime, or live phone delivery.

## Safety and operating boundaries

- The live connectors are read-only for market data/account metadata. There is no broker order placement, modification, or closure flow.
- A signal is a conditional strategy scenario, not a prediction or recommendation and not proof of execution.
- Check the feed, quote, spread, contract details, account feasibility, and current price at the broker you intend to use.
- AI output is an optional second opinion. It does not qualify signals, change levels, or override risk calculations.
- Do not commit `.env`, API tokens, bot tokens, or webhook secrets.

## Repository notes

`AGENT_HANDOFF.md` contains detailed implementation history and development handoff notes. `reports/` contains generated project/replay material. Runtime files such as the SQLite database, scanner log, screenshots, and local environment settings are workspace artifacts rather than required source inputs.

## Author

Yabesi
