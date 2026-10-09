# SOLID XAU/USD SCAN AND ALERT RICHSCHEME 001

A Python scanner for analyzing XAU/USD market data and producing structured signals for a person to review. The scanner is a decision-support tool, not an automated trading bot: it does not place, modify, or close orders. Trade execution remains manual.

## Current Scope

- Instrument: XAU/USD (`XAUUSD`) only
- Market data: BiQuote REST API at `https://biquote.io/api`
- Timeframes: H4 higher-timeframe context, H1 structure, and M15 setup/entry analysis
- Output: local console/log signal summary, with Telegram as an optional alert channel
- Strategy: retain and validate the existing analysis and scoring logic where practical
- Intent: identify potential upcoming setups where supported by the strategy, with a planned entry and the conditions that would support the scenario

Signals are strategy-based potential setups or conditional scenarios, not certain predictions. The goal is to give the user a plan before the expected price movement occurs where the available market structure and strategy allow it. A signal should communicate its direction, planned entry, Stop Loss, Take Profit, and supporting conditions/structure, along with risk/reward information when available.

Where supported by the strategy, the signal should distinguish among:

- **BUY LIMIT**: anticipate a bullish reaction at a planned lower entry level.
- **SELL LIMIT**: anticipate a bearish reaction at a planned higher entry level.
- **BUY STOP**: anticipate bullish continuation after a specified breakout level.
- **SELL STOP**: anticipate bearish continuation after a specified breakdown level.
- **MARKET/IMMEDIATE**: identify a valid current-entry setup explicitly; do not use this type merely because price has already moved.

These labels describe the intended setup, not broker orders. The scanner must never place pending orders or market orders. The user decides manually whether and how to execute a signal on their broker.

BiQuote is the current provider, not a permanent dependency of the analysis layer. The connector boundary should allow another provider to be substituted without rewriting the strategy. XAU/USD is an OTC/CFD instrument; feeds and quoted prices vary by broker. BiQuote prices must not be assumed to match Deriv, HFM, or another broker.

## Architecture

```text
BiQuote Market Data
	↓
Data Normalization
	↓
H4 Analysis
	↓
H1 Analysis
	↓
M15 Analysis
	↓
Existing Strategy / Scoring
	↓
Signal Generation
	↓
Entry / SL / TP / Risk-Reward
	↓
Structured Signal Output
	↓
Optional Telegram Alert
	↓
Manual Trade Execution by User
```

The current connector returns pandas DataFrames with `Open`, `High`, `Low`, `Close`, and `Volume` columns. The provider's `tickVolume` is used for `Volume` because its `volume` field is zero. The scanner requests 200 H4 bars, 200 H1 bars, and 100 M15 bars per scan. The existing strategy uses H4 EMA bias, H1 swing structure/BOS and liquidity sweeps, and M15 FVG, retest, rejection-candle, entry, and stop/target calculations. Scoring grades setups against the existing confluence rules.

Signal generation describes potential upcoming setups rather than only summarizing past price movement. A BUY/SELL LIMIT is generated only for a direction-aligned active FVG that has not been retested since formation. A BUY/SELL STOP is generated only ahead of an unbroken H1 swing level. MARKET/IMMEDIATE requires an M15 retest with a directional rejection candle. Signals include the entry condition, entry, SL, TP, risk/reward, and supporting conditions when available. These are strategy-based scenarios, not guarantees; neither local output nor Telegram submits orders.

Generated signal types are stored with setup history and shown in the dashboard. Existing databases are migrated by adding the nullable `signal_type` column; older setup rows without a recorded type remain marked as not recorded.

## Repository Layout

```text
main.py                     Scanner loop, multi-timeframe fetch and signal output
config.py                   Environment and scanner configuration
scanner/
  mt5_connector.py          Legacy module name; currently provides BiQuote REST data
	market_analyzer.py        Multi-timeframe strategy, setup classification and levels
	oanda_connector.py        Read-only OANDA practice candles and history archival
  scoring_engine.py         Setup scoring and grade classification
  chart_generator.py        Signal chart generation
  news_filter.py            Existing economic-calendar filter
alerts/telegram_bot.py      Optional Telegram message/photo output
risk/risk_manager.py        Existing risk checks
database/db_manager.py      SQLite persistence and setup-type migration
dashboard/app.py            Existing Streamlit dashboard
scanner/csv_market_data.py  Broker OHLC CSV normalization and import
scanner/import_market_csv.py CSV import command-line entry point
scanner/signal_replay.py     Historical signal replay and OHLC outcome estimates
tests/
	test_oanda_connector.py   OANDA practice candle request and safety tests
	test_csv_market_data.py   CSV parsing, validation, and persistence tests
	test_biquote_connector.py Provider bar ordering/normalization tests
	test_signal_generation.py Signal classification and level tests
	test_setup_signal_type.py SQLite persistence and migration tests
requirements.txt            Python dependencies; no MetaTrader5 package
```

The dashboard, database, risk, and news modules remain in the repository from the earlier application shape. The active development target is the XAU/USD scanner and its signal-validation path; this README does not imply that every retained module has been revalidated for the current data-only workflow.

## Development Status

- The MetaTrader5 Python dependency and runtime connection have been removed. The connector's old filename and unused MT5 credential settings remain as cleanup items; they do not provide an MT5 market-data connection.
- BiQuote is configured as the current REST data source. The connector has an XAUUSD connectivity check and maps H4, H1, and M15 to the provider intervals `4h`, `1h`, and `15m`.
- BiQuote returns bars newest-first; the connector now sorts normalized bars oldest-to-newest so the analyzer's final row is the latest candle. A connector regression test covers this behavior.
- A read-only live validation on 2026-09-29 retrieved H4, H1, and M15 bars with numeric, internally consistent OHLC values and nonzero normalized tick volume. The analyzer produced a bearish MARKET/IMMEDIATE scenario (score 10/A+) from an M15 retest and shooting-star rejection, with sell-side Entry/SL/TP ordering. This is one observed scan, not evidence of predictive performance or broad strategy validation.
- BiQuote confirmed that its endpoint is a rolling window, not a historical archive: XAUUSD provides up to 168 closed H1 candles plus the open candle, 180 H4 candles, and 500 D1 candles. `from`/`to` only filter within those windows; older candles are not retained and there is no separate history endpoint or export. The connector caps inclusive responses at the requested maximum and keeps the newest bars. This feed is suitable for live scanning, but not multi-year H1/H4 backtesting. Build a forward archive by polling and storing candles, and use broker MT5 history, Dukascopy tick data, or the existing OANDA archive for deeper research.
- Each live scan now stores the fetched H4, H1, and M15 candles in the local `market_bars` table under source `BIQUOTE`, separate from OANDA and broker imports. Polling follows `SCAN_INTERVAL`; repeated bars are deduplicated by source/symbol/timeframe/open-time, while changed values at an existing timestamp update the row so the current forming candle stays current. Archive write failures are logged without stopping signal analysis.
- The read-only OANDA practice connector successfully authenticated and retrieved `XAU_USD` midpoint candles for H4, H1, and M15. It excludes incomplete candles, archives rows under `OANDA-PRACTICE`, and has no order-submission calls.
- OANDA history was backfilled in paginated requests. Current archive totals are 4,999 H4, 19,117 H1, and 76,426 M15 candles. All three start at 2023-07-06 17:00 UTC; timestamps are unique and OHLC integrity checks found zero invalid candles. Coverage and archive validation reflect the data retrieved on 2026-09-29.
- Yahoo Finance's `XAUUSD=X` chart requests returned no data; its `GC=F` symbol returned COMEX gold-futures bars, which are not equivalent to broker XAU/USD CFD prices. Dukascopy's direct history host timed out from this environment.
- `tickVolume` is normalized as the output `Volume` column.
- The analyzer now classifies potential LIMIT setups from unretested active FVGs, STOP setups ahead of unbroken H1 swing levels, and MARKET/IMMEDIATE setups only after an M15 retest and directional rejection. It rejects levels whose SL/TP geometry is invalid.
- Signal type is persisted in SQLite and displayed on the Active Setups page. Existing databases are migrated without deleting setup history; older records show "Not recorded".
- Broker-exported OHLC CSV files can be normalized, stored in a separate `market_bars` table, and loaded back as pandas OHLCV DataFrames. Rows are keyed by source, symbol, timeframe, and UTC candle timestamp; re-importing is idempotent, and broker feeds remain distinguishable from BiQuote.
- Unit tests cover OANDA practice request construction, backward pagination and incomplete-candle filtering, CSV parsing and timezone conversion, candle validation, idempotent/source-separated persistence, chronological BiQuote normalization, signal classification, replay timing/outcomes, and setup-type migration.
- `scanner.signal_replay` replays using only closed H4/H1/M15 candles and estimates entry fills, TP1/SL outcomes, holding time, and R-multiples from later M15 OHLC bars. Same-bar SL/TP collisions count as SL; pending entries may remain unfilled, and outcomes unresolved at the holding limit are reported separately. A one-week OANDA sample (2026-09-23 through 2026-09-29) produced 317 signals across 418 available M15 decisions: 66 reached TP1, 55 reached SL, 127 were unfilled, and 69 remained unresolved. The resolved-only win rate was 54.5% with mean +0.64R. This short sample is a pipeline check, not evidence of strategy profitability; spread, slippage, funding, and position-management rules are not modeled.
- Telegram code is present as an output layer. Missing credentials make sends no-ops, and Telegram request errors are caught; successful Telegram delivery has not been established by the local scanner log. Local console/log output is generated independently of Telegram.
- Full-history replay and robust historical performance validation remain outstanding; the current OHLC outcome evaluator is an initial research tool, not a broker-execution simulator.

## Setup

Python 3.10 or newer is required. The scanner does not require Windows or a MetaTrader 5 terminal. Install the dependencies in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate` instead. Create a local `.env` file for optional settings:

```env
BIQUOTE_BASE_URL=https://biquote.io/api
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
OANDA_API_TOKEN=
MARKET_DATA_PROVIDER=BIQUOTE
DERIV_API_TOKEN=
DERIV_APP_ID=
DERIV_DEMO_ACCOUNT_ID=
```

Telegram credentials are optional during development. If enabled, keep the bot token and chat ID in `.env`; never hardcode credentials in source. The repository ignores `.env`; do not commit it.

### Optional Deriv Demo Read-Only Check

The Deriv connector is opt-in and read-only. It uses Deriv's documented account-list and one-time-password flow to select a **demo** Options account, then reads account balance and Gold candles. It includes no order, buy, sell, or contract execution calls. Create a Deriv Personal Access Token with the required account read/trade scope and use your Deriv app ID; store both only in the ignored local `.env` file. Never paste tokens into chat or commit them. `DERIV_DEMO_ACCOUNT_ID` is optional; if omitted, the first demo account returned for that token is selected. Real accounts are rejected.

To check the credentials and read sample H4/H1/M15 candles without changing the live scanner's feed:

```bash
python -m scanner.deriv_connector --count 5
```

To opt the scanner into Deriv demo candles and balance checks, set:

```env
MARKET_DATA_PROVIDER=DERIV_DEMO
```

The default remains `BIQUOTE`. Deriv and BiQuote XAU/USD quotes may differ; setups generated from one feed must not be assumed to match another broker's executable prices. The Deriv connector should be validated with your account before switching the scanner provider.

### Simulation Risk Account

The scanner keeps the selected provider's broker/demo balance separate from strategy capital. The broker balance is retained as connectivity/account metadata; active drawdown checks and journal P/L use a persistent simulation account seeded from `SIMULATION_ACCOUNT_BALANCE` (default `$10`). The default `MAX_RISK_PER_TRADE` is `2%`, and `SIMULATION_RR_MULTIPLE` is `2.0`. Changing the configured starting balance rebases current simulation equity by preserving realized dollar P/L and resets the drawdown high-water baseline; existing trade history remains available.

Position size is calculated as `risk amount / (entry-to-stop price distance × XAUUSD contract size)`, then rounded down to the broker's volume step. Configure `XAUUSD_CONTRACT_SIZE`, `BROKER_MIN_VOLUME`, `BROKER_VOLUME_STEP`, and optionally `BROKER_MAX_VOLUME` only from the exact CFD symbol specification for the broker you intend to model. Missing specifications or a required size below broker minimum are recorded as non-executable; the scanner never rounds volume up and never raises risk to fit a minimum lot.

The current Deriv connector is a read-only Options account/candle connector. It provides no CFD contract size or minimum-volume/step specification and does not place orders. Therefore it can supply broker connectivity metadata, but exact XAUUSD CFD position sizing remains unavailable while using Deriv unless valid CFD specifications are explicitly configured for a separate broker model. A `$10` account at `2%` risk still has `$0.20` planned risk and `$0.40` planned reward at `2R`; whether that risk can be represented by an executable volume depends on those specifications.

Start the scanner:

```bash
python main.py
```

The scanner checks BiQuote connectivity at startup, then polls and archives H4/H1/M15 candles each scan before logging analysis and signal summaries to the console and `scanner.log`. A data-source connection failure prevents scanning; an archive write failure is logged but does not prevent analysis, and Telegram unavailability must not prevent local signal output. The existing dashboard can be started separately with `streamlit run dashboard/app.py`, but it is not required for scanning.

### Archive OANDA Practice Candles

The optional OANDA connector is separate from the live BiQuote scanner. It uses the OANDA practice API and only requests midpoint XAU/USD candles; it contains no order-submission calls. API access requires an eligible OANDA v20 practice account. Add a newly generated practice API token to local `.env` as `OANDA_API_TOKEN`; never paste it into chat or commit `.env`. Any token previously shared in chat should be revoked and replaced.

Fetch and archive up to 5,000 complete candles per timeframe:

```bash
python -m scanner.oanda_connector --count 5000
```

The command requests H4, H1, and M15, excludes each currently open candle, and stores data under the `OANDA-PRACTICE` source label. It does not switch the scanner away from BiQuote. To extend history backward to a chosen UTC date, use paginated requests with `--from`:

```bash
python -m scanner.oanda_connector --timeframes H1 M15 --count 5000 \
	--from 2023-07-06T17:00:00Z
```

An optional `--to` timestamp bounds the end of the requested range. OANDA candles are a separate feed and may differ from BiQuote or another broker's XAU/USD CFD.

### Import Broker History from CSV

After exporting OHLC candles from a broker, import them without replacing the live BiQuote feed:

```bash
python -m scanner.import_market_csv /path/to/export.csv \
	--symbol XAUUSD --timeframe H1 --source HFM --timezone Europe/Athens
```

Set `--source` to the broker/feed name and `--timezone` to the export's timezone when timestamps have no explicit UTC offset. The importer accepts common `Date` + `Time` or timestamp columns and OHLC headers, including MT-style semicolon exports. It rejects invalid candle ranges, normalizes timestamps to UTC, and stores the data separately from live scanner bars. We need a sample of your actual broker export to confirm its headers, timestamp convention, and volume fields before claiming compatibility with that exact export.

### Replay Archived Signals

Replay archived OANDA practice candles and evaluate each signal against subsequent M15 bars, with a default maximum holding period of 96 bars (24 hours):

```bash
python -m scanner.signal_replay --source OANDA-PRACTICE --symbol XAU_USD \
	--from 2026-09-23T00:00:00Z --to 2026-09-30T00:00:00Z \
	--holding-bars 96 --output signal_replay.csv
```

The report distinguishes unfilled entries, unresolved trades, stop losses, and TP1 exits. Because candles contain no intrabar path, a bar that reaches both SL and TP1 is conservatively counted as an SL. The report does not include spread, slippage, commissions, or overlapping-position constraints.

## Roadmap

### Stage 1 — Market Data (Implemented; reliability validation ongoing)

- [x] Remove the MT5 runtime dependency
- [x] Integrate BiQuote and normalize OHLCV data
- [x] Verify H4/H1/M15 data retrieval
- [x] Normalize provider bars to chronological order
- [x] Cap inclusive provider responses at the requested maximum
- [x] Confirm documented `from`/`to` range filtering; no offset/page pagination is documented
- [ ] Continue testing provider reliability and error handling
- [ ] Confirm deeper XAUUSD H4/H1 history availability with BiQuote and evaluate a comparable free historical source; do not substitute gold futures as an equivalent CFD feed
- [x] Add a separate OANDA practice candle archive path
- [x] Verify OANDA practice token access and live candle retrieval without exposing credentials
- [x] Backfill H1 and M15 to align with the available H4 history
- [ ] Validate strategy behavior across the expanded OANDA history
- [x] Persist live BiQuote candles locally so its rolling window builds into a forward archive

### Stage 2 — Analysis & Signal Generation (In progress)

- [x] Preserve the existing strategy and scoring logic
- [x] Generate typed potential setups with entry conditions and levels
- [x] Add unit coverage for supported types, stale setups, and invalid level geometry
- [x] Complete an initial read-only live validation of H4/H1/M15 analysis and signal output
- [ ] Repeat validation across representative market conditions
- [ ] Review Entry, SL, TP, and risk/reward calculations across those examples

### Stage 3 — Output (Partially implemented)

- [x] Include signal type, levels, and conditions in local output
- [x] Persist and display signal type in setup history
- [x] Keep Telegram optional and alerts manual-only
- [ ] Validate Telegram delivery and failure behavior end to end

### Stage 4 — Backtesting

- [x] Add broker CSV candle import and source-separated storage
- [x] Add chronological signal replay and an initial conservative OHLC outcome estimator
- [ ] Run replay across the full archived history and investigate runtime/scalability
- [ ] Validate signal logic and measure results across representative historical conditions
- Identify weaknesses and edge cases

### Stage 5 — Finalization

- Add and run tests
- Improve error handling
- Complete documentation and cleanup
- Make the final Git commit and push (This is the only commit and push we will have as far as this project is concerned)

## Development Principles

- Keep current scope to XAU/USD and manual trading.
- Treat signals as potential, conditional strategy scenarios rather than certain predictions.
- Never place automatic pending orders or market orders; execution decisions remain with the user.
- Prefer free data sources where practical and keep the market-data interface provider-independent.
- Preserve useful existing strategy logic and avoid unnecessary rewrites.
- Test changes before considering them complete.
- Never expose API keys, Telegram tokens, or other secrets in source code; do not commit `.env`.
- Keep local scanner output available when optional services such as Telegram are unavailable.

Signals and calculated levels are informational, not broker instructions. Verify prices, contract specifications, and risk at the intended broker before any manual trade. This project makes no performance claims.

## Author

Yabesi

