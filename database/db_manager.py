import sqlite3
import json
import math
from datetime import date, datetime, timedelta, timezone
import config
from scanner.setup_state import transition_state


def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS setups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT,
            signal_type TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            bias TEXT,
            direction TEXT,
            grade TEXT,
            score INTEGER,
            conditions TEXT,
            entry REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            session TEXT,
            chart_path TEXT,
            simulation_plan TEXT
        )
    """)

    setup_columns = {row["name"] for row in c.execute("PRAGMA table_info(setups)")}
    if "signal_type" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN signal_type TEXT")
    if "direction" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN direction TEXT")
    if "lifecycle_state" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN lifecycle_state TEXT")
    if "lifecycle_reason" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN lifecycle_reason TEXT")
    if "reviewed_at" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN reviewed_at TIMESTAMP")
    if "simulation_plan" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN simulation_plan TEXT")
    if "setup_identity" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN setup_identity TEXT")
    if "setup_zone" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN setup_zone TEXT")
    if "entry_touched_at" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN entry_touched_at TIMESTAMP")
    c.execute("""
        UPDATE setups
        SET direction=CASE
            WHEN UPPER(COALESCE(signal_type, '')) LIKE 'BUY%' THEN 'BUY'
            WHEN UPPER(COALESCE(signal_type, '')) LIKE 'SELL%' THEN 'SELL'
            WHEN LOWER(COALESCE(bias, ''))='bullish' THEN 'BUY'
            WHEN LOWER(COALESCE(bias, ''))='bearish' THEN 'SELL'
            ELSE direction
        END
        WHERE direction IS NULL
    """)
    for name, definition in (
        ("ai_status", "TEXT"),
        ("ai_decision", "TEXT"),
        ("ai_quality_score", "INTEGER"),
        ("ai_confidence", "TEXT"),
        ("ai_summary", "TEXT"),
        ("ai_reasons", "TEXT"),
        ("ai_invalidations", "TEXT"),
        ("ai_risk_note", "TEXT"),
        ("ai_reviewed_at", "TIMESTAMP"),
        ("telegram_status", "TEXT"),
        ("telegram_error", "TEXT"),
        ("telegram_attempted_at", "TIMESTAMP"),
        ("telegram_sent_at", "TIMESTAMP"),
        ("lifecycle_telegram_status", "TEXT"),
        ("lifecycle_telegram_error", "TEXT"),
        ("lifecycle_telegram_attempted_at", "TIMESTAMP"),
    ):
        if name not in setup_columns:
            c.execute(f"ALTER TABLE setups ADD COLUMN {name} {definition}")

    c.execute("""
        CREATE TABLE IF NOT EXISTS market_bars (
            source TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (source, symbol, timeframe, bar_time)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            direction TEXT,
            setup_id INTEGER,
            execution_mode TEXT DEFAULT 'UNSPECIFIED',
            opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            entry_triggered_at TIMESTAMP,
            closed_at TIMESTAMP,
            session TEXT,
            grade TEXT,
            score INTEGER,
            entry REAL,
            sl REAL,
            tp REAL,
            tp2 REAL,
            exit_price REAL,
            outcome TEXT,
            rr_achieved REAL,
            gross_r_multiple REAL,
            net_r_multiple REAL,
            exit_reason TEXT,
            mfe_price REAL,
            mae_price REAL,
            mfe_r REAL,
            mae_r REAL,
            tp1_reached INTEGER,
            tp2_reached INTEGER,
            stop_reached INTEGER,
            favorable_close_bars INTEGER,
            favorable_close_minutes INTEGER,
            excursion_source TEXT,
            notes TEXT,
            chart_path TEXT,
            FOREIGN KEY (setup_id) REFERENCES setups(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS setup_action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('PAPER_TRACKED', 'SKIPPED', 'TRADE_LOGGED')),
            reason TEXT,
            source TEXT NOT NULL DEFAULT 'dashboard',
            recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (setup_id) REFERENCES setups(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS setup_modeled_outcomes (
            setup_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'PENDING',
            source TEXT,
            fill_status TEXT,
            outcome TEXT,
            fill_time TIMESTAMP,
            fill_price REAL,
            exit_time TIMESTAMP,
            exit_price REAL,
            outcome_end_time TIMESTAMP,
            gross_r_multiple REAL,
            mfe_r REAL,
            mae_r REAL,
            bars_held INTEGER,
            tp1_reached INTEGER,
            tp2_reached INTEGER,
            stop_reached INTEGER,
            notes TEXT,
            evaluated_at TIMESTAMP,
            FOREIGN KEY (setup_id) REFERENCES setups(id)
        )
    """)
    c.execute("""
        INSERT OR IGNORE INTO setup_modeled_outcomes (setup_id)
        SELECT id FROM setups
    """)
    c.execute("""
        INSERT INTO setup_action_log (setup_id, action, reason, source)
        SELECT DISTINCT t.setup_id, 'TRADE_LOGGED',
               'Existing linked journal trade; broker fill is not independently verified.',
               'migration'
        FROM trades t
        WHERE t.setup_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM setup_action_log a
              WHERE a.setup_id=t.setup_id AND a.action='TRADE_LOGGED'
          )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            entry_date DATE DEFAULT CURRENT_DATE,
            followed_plan TEXT,
            outcome TEXT,
            moved_stop TEXT,
            better_entry TEXT,
            emotions TEXT,
            notes TEXT,
            FOREIGN KEY (trade_id) REFERENCES trades(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS risk_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            balance REAL,
            equity REAL,
            daily_dd REAL,
            weekly_dd REAL,
            consecutive_losses INTEGER,
            trading_allowed INTEGER
        )
    """)
    risk_columns = {row["name"] for row in c.execute("PRAGMA table_info(risk_log)")}
    if "account_scope" not in risk_columns:
        c.execute("ALTER TABLE risk_log ADD COLUMN account_scope TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS simulation_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            starting_balance REAL NOT NULL,
            current_balance REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            high_water_mark REAL NOT NULL,
            max_drawdown REAL NOT NULL DEFAULT 0,
            daily_start_balance REAL NOT NULL,
            weekly_start_balance REAL NOT NULL,
            daily_period TEXT NOT NULL,
            weekly_period TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS broker_account_snapshot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT NOT NULL,
            account_type TEXT,
            balance REAL,
            equity REAL,
            currency TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    simulation_columns = {row["name"] for row in c.execute("PRAGMA table_info(simulation_account)")}
    for name, definition in (
        ("daily_start_balance", "REAL NOT NULL DEFAULT 10"),
        ("weekly_start_balance", "REAL NOT NULL DEFAULT 10"),
        ("daily_period", "TEXT NOT NULL DEFAULT ''"),
        ("weekly_period", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in simulation_columns:
            c.execute(f"ALTER TABLE simulation_account ADD COLUMN {name} {definition}")

    trade_columns = {row["name"] for row in c.execute("PRAGMA table_info(trades)")}
    for name, definition in (
        ("entry_triggered_at", "TIMESTAMP"),
        ("tp2", "REAL"),
        ("gross_r_multiple", "REAL"),
        ("net_r_multiple", "REAL"),
        ("exit_reason", "TEXT"),
        ("mfe_price", "REAL"),
        ("mae_price", "REAL"),
        ("mfe_r", "REAL"),
        ("mae_r", "REAL"),
        ("tp1_reached", "INTEGER"),
        ("tp2_reached", "INTEGER"),
        ("stop_reached", "INTEGER"),
        ("favorable_close_bars", "INTEGER"),
        ("favorable_close_minutes", "INTEGER"),
        ("excursion_source", "TEXT"),
        ("simulation_risk_amount", "REAL"),
        ("simulation_entry_balance", "REAL"),
        ("simulation_pnl", "REAL"),
        ("simulation_position_size", "REAL"),
        ("simulation_sizing_status", "TEXT"),
        ("execution_mode", "TEXT DEFAULT 'UNSPECIFIED'"),
        ("position_size", "REAL"),
        ("actual_risk_amount", "REAL"),
        ("risk_currency", "TEXT"),
        ("transaction_cost_amount", "REAL"),
        ("cost_currency", "TEXT"),
    ):
        if name not in trade_columns:
            c.execute(f"ALTER TABLE trades ADD COLUMN {name} {definition}")

    conn.commit()
    conn.close()


def save_market_bars(bars):
    if bars.empty:
        return 0

    conn = get_connection()
    c = conn.cursor()
    c.executemany("""
        INSERT INTO market_bars (
            source, symbol, timeframe, bar_time, open, high, low, close, volume
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol, timeframe, bar_time) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume
        WHERE market_bars.open IS NOT excluded.open
            OR market_bars.high IS NOT excluded.high
            OR market_bars.low IS NOT excluded.low
            OR market_bars.close IS NOT excluded.close
            OR market_bars.volume IS NOT excluded.volume
    """, [
        (
            row.source,
            row.symbol,
            row.timeframe,
            row.Index.isoformat(),
            float(row.Open),
            float(row.High),
            float(row.Low),
            float(row.Close),
            float(row.Volume),
        )
        for row in bars.itertuples()
    ])
    conn.commit()
    saved_count = len(bars)
    conn.close()
    return saved_count


def save_setup(symbol, timeframe, analysis, scoring, chart_path=None, simulation_plan=None, lifecycle_state="ACTIVE", lifecycle_reason="Signal fired and setup became active", ai_review=None, setup_identity=None, setup_zone=None):
    conn = get_connection()
    c = conn.cursor()
    levels = analysis.get("levels") or {}
    ai_review = ai_review or {}
    c.execute("""
        INSERT INTO setups (
            symbol, timeframe, signal_type, bias, direction, grade, score, conditions,
            entry, sl, tp1, tp2, session, chart_path, simulation_plan,
            lifecycle_state, lifecycle_reason, setup_identity, setup_zone,
            ai_status, ai_decision, ai_quality_score, ai_confidence, ai_summary,
            ai_reasons, ai_invalidations, ai_risk_note, ai_reviewed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, timeframe,
        (analysis.get("signal") or {}).get("type"),
        analysis.get("bias"),
        (analysis.get("signal") or {}).get("direction")
        or ("BUY" if analysis.get("bias") == "bullish" else "SELL" if analysis.get("bias") == "bearish" else None),
        scoring.get("grade"),
        scoring.get("score"),
        json.dumps(analysis.get("conditions", [])),
        levels.get("entry"),
        levels.get("sl"),
        levels.get("tp1"),
        levels.get("tp2"),
        analysis.get("session"),
        chart_path,
        json.dumps(simulation_plan or {}),
        lifecycle_state,
        lifecycle_reason,
        setup_identity,
        setup_zone,
        ai_review.get("status"),
        ai_review.get("decision"),
        ai_review.get("quality_score"),
        ai_review.get("confidence"),
        ai_review.get("summary"),
        json.dumps(ai_review.get("reasons", [])),
        json.dumps(ai_review.get("invalidations", [])),
        ai_review.get("risk_note"),
        datetime.now(timezone.utc).isoformat()
        if ai_review.get("status") in {"available", "unavailable", "invalid_response"}
        else None,
    ))
    setup_id = c.lastrowid
    c.execute(
        "INSERT OR IGNORE INTO setup_modeled_outcomes (setup_id) VALUES (?)",
        (setup_id,),
    )
    conn.commit()
    conn.close()
    return setup_id


def log_trade(symbol, direction, entry, sl, tp, grade=None, score=None, session=None,
              setup_id=None, notes=None, simulation_plan=None, tp2=None,
              execution_mode="PAPER", entry_triggered_at=None, position_size=None,
              actual_risk_amount=None, risk_currency=None,
              transaction_cost_amount=None, cost_currency=None):
    execution_mode = str(execution_mode or "PAPER").strip().upper()
    if execution_mode not in {"PAPER", "MANUAL_REPORTED"}:
        raise ValueError("Execution mode must be PAPER or MANUAL_REPORTED.")
    _validate_trade_metadata(
        position_size, actual_risk_amount, risk_currency,
        transaction_cost_amount, cost_currency,
    )
    init_db()
    conn = get_connection()
    c = conn.cursor()
    account = _get_or_create_simulation_account(c)
    plan = simulation_plan or {}
    opened_at = datetime.now(timezone.utc).isoformat()
    entry_triggered_at = _normalize_trade_timestamp(entry_triggered_at or opened_at)
    if execution_mode != "PAPER":
        plan = {}
    c.execute("""
        INSERT INTO trades (
            symbol, direction, setup_id, execution_mode, opened_at, entry_triggered_at,
            session, grade, score, entry, sl, tp, tp2, notes,
            simulation_risk_amount, simulation_entry_balance,
            simulation_position_size, simulation_sizing_status, position_size,
            actual_risk_amount, risk_currency, transaction_cost_amount, cost_currency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, direction, setup_id, execution_mode, opened_at, entry_triggered_at,
        session, grade, score, entry, sl, tp, tp2, notes,
        plan.get("risk_amount"), account["current_balance"] if execution_mode == "PAPER" else None,
        plan.get("position_size"), plan.get("sizing_status", "NOT_CALCULATED") if execution_mode == "PAPER" else None,
        position_size, actual_risk_amount, _normalize_currency(risk_currency),
        transaction_cost_amount, _normalize_currency(cost_currency),
    ))
    trade_id = c.lastrowid
    if setup_id is not None:
        c.execute("""
            INSERT INTO setup_action_log (setup_id, action, reason, source)
            VALUES (?, 'TRADE_LOGGED', ?, 'trade_journal')
        """, (
            setup_id,
            f"Linked trade journal entry #{trade_id}; broker fill is not independently verified.",
        ))
    conn.commit()
    conn.close()
    return trade_id


def _normalize_currency(currency):
    return str(currency).strip().upper() if currency is not None and str(currency).strip() else None


def _validate_trade_metadata(position_size, actual_risk_amount, risk_currency,
                             transaction_cost_amount, cost_currency):
    for label, value in (
        ("Position size", position_size),
        ("Actual risk amount", actual_risk_amount),
        ("Transaction costs", transaction_cost_amount),
    ):
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f"{label} must be a finite number.")
    if position_size is not None and float(position_size) <= 0:
        raise ValueError("Position size must be greater than zero when provided.")
    if actual_risk_amount is not None and float(actual_risk_amount) <= 0:
        raise ValueError("Actual risk amount must be greater than zero when provided.")
    if (actual_risk_amount is None) != (not _normalize_currency(risk_currency)):
        raise ValueError("Provide both actual risk amount and its currency.")
    if transaction_cost_amount is not None and float(transaction_cost_amount) < 0:
        raise ValueError("Transaction costs cannot be negative.")
    if (transaction_cost_amount is None) != (not _normalize_currency(cost_currency)):
        raise ValueError("Provide both transaction cost amount and its currency.")
    for currency in (risk_currency, cost_currency):
        normalized = _normalize_currency(currency)
        if normalized and (len(normalized) != 3 or not normalized.isalpha()):
            raise ValueError("Currency must be a three-letter code such as USD or TZS.")


def _normalize_trade_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise ValueError("Entry time must be a valid timestamp.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_utc_timestamp(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trade_excursion_metrics(cursor, trade, closed_at):
    start_time = _parse_utc_timestamp(trade["entry_triggered_at"] or trade["opened_at"])
    end_time = _parse_utc_timestamp(closed_at)
    if start_time is None or end_time is None:
        return {}
    source = config.MARKET_DATA_SOURCE_LABEL
    start_date = start_time.date().isoformat()
    end_date = end_time.date().isoformat()
    rows = cursor.execute("""
        SELECT bar_time, high, low, close
        FROM market_bars
        WHERE source=? AND symbol=? AND timeframe='M15'
          AND substr(bar_time, 1, 10) BETWEEN ? AND ?
        ORDER BY bar_time
    """, (source, trade["symbol"], start_date, end_date)).fetchall()
    bars = []
    for row in rows:
        bar_time = _parse_utc_timestamp(row["bar_time"])
        if bar_time is not None and start_time <= bar_time <= end_time:
            bars.append((bar_time, row))
    if not bars:
        return {}

    direction = 1 if str(trade["direction"] or "").upper() in {"BUY", "LONG"} else -1
    entry = float(trade["entry"])
    stop = float(trade["sl"])
    risk = abs(entry - stop)
    mfe = 0.0
    mae = 0.0
    favorable_close_bars = 0
    tp1_reached = False
    tp2_reached = False
    stop_reached = False
    tp1 = trade["tp"]
    tp2 = trade["tp2"]
    for _, bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        mfe = max(mfe, high - entry if direction == 1 else entry - low)
        mae = max(mae, entry - low if direction == 1 else high - entry)
        if tp1 is not None:
            tp1_reached = tp1_reached or (high >= float(tp1) if direction == 1 else low <= float(tp1))
        if tp2 is not None:
            tp2_reached = tp2_reached or (high >= float(tp2) if direction == 1 else low <= float(tp2))
        stop_reached = stop_reached or (low <= stop if direction == 1 else high >= stop)
        if (close - entry) * direction > 0:
            favorable_close_bars += 1

    return {
        "mfe_price": round(max(0.0, mfe), 5),
        "mae_price": round(max(0.0, mae), 5),
        "mfe_r": round(max(0.0, mfe) / risk, 4) if risk > 0 else None,
        "mae_r": round(max(0.0, mae) / risk, 4) if risk > 0 else None,
        "tp1_reached": int(tp1_reached),
        "tp2_reached": int(tp2_reached),
        "stop_reached": int(stop_reached),
        "favorable_close_bars": favorable_close_bars,
        "favorable_close_minutes": favorable_close_bars * 15,
        "excursion_source": (
            f"{source} M15 OHLC estimate; opening and exit candles may include movement outside the recorded trade; "
            "intrabar path and broker fill are unverified"
        ),
    }


def close_trade(
    trade_id, exit_price, outcome, rr_achieved=None, notes=None, exit_reason=None, closed_at=None,
    transaction_cost_amount=None, cost_currency=None,
):
    init_db()
    conn = get_connection()
    c = conn.cursor()
    _get_or_create_simulation_account(c)
    c.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
    trade = c.fetchone()
    if trade is None:
        conn.close()
        raise ValueError(f"Trade {trade_id} does not exist.")
    if trade["outcome"] is not None:
        conn.close()
        return
    if outcome not in {"win", "loss", "breakeven"}:
        conn.close()
        raise ValueError("Outcome must be win, loss, or breakeven.")
    risk_distance = abs(float(trade["entry"]) - float(trade["sl"]))
    if risk_distance <= 0:
        conn.close()
        raise ValueError("Trade has no valid entry-to-stop distance.")
    direction = 1 if str(trade["direction"] or "").upper() in {"BUY", "LONG"} else -1
    rr_achieved = (float(exit_price) - float(trade["entry"])) * direction / risk_distance
    if outcome == "win" and rr_achieved <= 0:
        conn.close()
        raise ValueError("A winning trade needs an exit price beyond entry in the profitable direction.")
    if outcome == "loss" and rr_achieved >= 0:
        conn.close()
        raise ValueError("A losing trade needs an exit price beyond entry in the adverse direction.")
    if outcome == "breakeven" and abs(rr_achieved) > 1e-6:
        conn.close()
        raise ValueError("A breakeven trade needs an exit price equal to entry.")

    if transaction_cost_amount is not None or cost_currency is not None:
        _validate_trade_metadata(None, None, None, transaction_cost_amount, cost_currency)
        stored_cost = transaction_cost_amount
        stored_cost_currency = _normalize_currency(cost_currency)
    else:
        stored_cost = trade["transaction_cost_amount"]
        stored_cost_currency = _normalize_currency(trade["cost_currency"])
    actual_risk_amount = trade["actual_risk_amount"]
    risk_currency = _normalize_currency(trade["risk_currency"])
    net_r_multiple = None
    if (actual_risk_amount is not None and float(actual_risk_amount) > 0
            and stored_cost is not None and stored_cost_currency
            and risk_currency == stored_cost_currency):
        net_r_multiple = rr_achieved - float(stored_cost) / float(actual_risk_amount)

    close_datetime = closed_at or datetime.now(timezone.utc)
    if isinstance(close_datetime, datetime):
        if close_datetime.tzinfo is None:
            close_datetime = close_datetime.replace(tzinfo=timezone.utc)
        closed_at = close_datetime.astimezone(timezone.utc).isoformat()
    else:
        closed_at = str(close_datetime)
    excursions = _trade_excursion_metrics(c, trade, closed_at)
    simulation_pnl = None
    if trade["simulation_risk_amount"] is not None:
        risk_amount = float(trade["simulation_risk_amount"])
        simulation_pnl = risk_amount * rr_achieved
        if stored_cost is not None and stored_cost_currency == _normalize_currency(
            config.SIMULATION_ACCOUNT_CURRENCY
        ):
            simulation_pnl -= float(stored_cost)
    c.execute("""
        UPDATE trades
        SET exit_price=?, outcome=?, rr_achieved=?, gross_r_multiple=?, net_r_multiple=?,
            transaction_cost_amount=?, cost_currency=?,
            notes=?, simulation_pnl=?, closed_at=?, exit_reason=?,
            mfe_price=?, mae_price=?, mfe_r=?, mae_r=?, tp1_reached=?, tp2_reached=?,
            stop_reached=?, favorable_close_bars=?, favorable_close_minutes=?, excursion_source=?
        WHERE id=?
    """, (
        exit_price, outcome, rr_achieved, rr_achieved, net_r_multiple,
        stored_cost, stored_cost_currency, notes, simulation_pnl,
        closed_at, exit_reason or "MANUAL_EXIT",
        excursions.get("mfe_price"), excursions.get("mae_price"),
        excursions.get("mfe_r"), excursions.get("mae_r"),
        excursions.get("tp1_reached"), excursions.get("tp2_reached"),
        excursions.get("stop_reached"), excursions.get("favorable_close_bars"),
        excursions.get("favorable_close_minutes"), excursions.get("excursion_source"),
        trade_id,
    ))
    if simulation_pnl is not None:
        account = c.execute("SELECT * FROM simulation_account WHERE id=1").fetchone()
        current_balance = float(account["current_balance"]) + simulation_pnl
        high_water_mark = max(float(account["high_water_mark"]), current_balance)
        drawdown = max(0.0, (high_water_mark - current_balance) / high_water_mark * 100)
        c.execute("""
            UPDATE simulation_account
            SET current_balance=?, realized_pnl=realized_pnl+?,
                wins=wins+?, losses=losses+?, high_water_mark=?,
                max_drawdown=MAX(max_drawdown, ?), updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (
            current_balance, simulation_pnl,
            1 if outcome == "win" else 0,
            1 if outcome == "loss" else 0,
            high_water_mark, drawdown,
        ))
    conn.commit()
    conn.close()


def save_journal_entry(trade_id, followed_plan, outcome, moved_stop, better_entry, emotions, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO journal_entries (trade_id, followed_plan, outcome, moved_stop, better_entry, emotions, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (trade_id, followed_plan, outcome, moved_stop, better_entry,
          json.dumps(emotions) if isinstance(emotions, list) else emotions, notes))
    conn.commit()
    conn.close()


def log_risk(balance, equity, risk_status):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO risk_log (balance, equity, daily_dd, weekly_dd, consecutive_losses, trading_allowed, account_scope)
        VALUES (?, ?, ?, ?, ?, ?, 'SIMULATION')
    """, (
        balance, equity,
        risk_status.get("daily_drawdown"),
        risk_status.get("weekly_drawdown"),
        risk_status.get("consecutive_losses"),
        1 if risk_status.get("allowed") else 0,
    ))
    conn.commit()
    conn.close()


def _get_or_create_simulation_account(cursor=None):
    owns_connection = cursor is None
    conn = get_connection() if owns_connection else None
    c = conn.cursor() if owns_connection else cursor
    row = c.execute("SELECT * FROM simulation_account WHERE id=1").fetchone()
    if row is None:
        starting_balance = float(config.SIMULATION_ACCOUNT_BALANCE)
        today = date.today().isoformat()
        week = date.today().isocalendar().week
        weekly_period = f"{date.today().isocalendar().year}-W{week:02d}"
        c.execute("""
            INSERT INTO simulation_account (
                id, starting_balance, current_balance, high_water_mark,
                daily_start_balance, weekly_start_balance, daily_period, weekly_period
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, (starting_balance, starting_balance, starting_balance,
              starting_balance, starting_balance, today, weekly_period))
        row = c.execute("SELECT * FROM simulation_account WHERE id=1").fetchone()
        if owns_connection:
            conn.commit()
    requested_starting_balance = float(config.SIMULATION_ACCOUNT_BALANCE)
    if abs(float(row["starting_balance"]) - requested_starting_balance) > 1e-9:
        current_balance = requested_starting_balance + float(row["realized_pnl"])
        c.execute("""
            UPDATE simulation_account
            SET starting_balance=?, current_balance=?, high_water_mark=?, max_drawdown=0,
                daily_start_balance=?, weekly_start_balance=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (
            requested_starting_balance, current_balance, current_balance,
            current_balance, current_balance,
        ))
        row = c.execute("SELECT * FROM simulation_account WHERE id=1").fetchone()
        if owns_connection:
            conn.commit()
    today = date.today().isoformat()
    iso_date = date.today().isocalendar()
    weekly_period = f"{iso_date.year}-W{iso_date.week:02d}"
    if row["daily_period"] != today or row["weekly_period"] != weekly_period:
        current_balance = float(row["current_balance"])
        c.execute("""
            UPDATE simulation_account
            SET daily_start_balance=?, daily_period=?,
                weekly_start_balance=CASE WHEN weekly_period != ? THEN ? ELSE weekly_start_balance END,
                weekly_period=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (current_balance, today, weekly_period, current_balance, weekly_period))
        row = c.execute("SELECT * FROM simulation_account WHERE id=1").fetchone()
        if owns_connection:
            conn.commit()
    result = dict(row)
    if owns_connection:
        conn.close()
    return result


def get_simulation_account():
    init_db()
    return _get_or_create_simulation_account()


def get_simulation_performance():
    account = get_simulation_account()
    current = float(account["current_balance"])
    daily_drawdown = max(
        0.0,
        (float(account["daily_start_balance"]) - current)
        / float(account["daily_start_balance"]) * 100,
    ) if account["daily_start_balance"] else 0.0
    weekly_drawdown = max(
        0.0,
        (float(account["weekly_start_balance"]) - current)
        / float(account["weekly_start_balance"]) * 100,
    ) if account["weekly_start_balance"] else 0.0
    return {
        **account,
        "equity": current,
        "daily_drawdown": round(daily_drawdown, 2),
        "weekly_drawdown": round(weekly_drawdown, 2),
    }


def get_broker_account_snapshot(account):
    """Return provider account metadata without using it for simulation equity."""
    account = account or {}
    return {
        "provider": config.MARKET_DATA_PROVIDER,
        "account_type": account.get("account_type", "unavailable"),
        "balance": account.get("balance"),
        "equity": account.get("equity"),
        "currency": account.get("currency"),
    }


def save_broker_account_snapshot(account):
    init_db()
    metadata = get_broker_account_snapshot(account)
    conn = get_connection()
    conn.execute("""
        INSERT INTO broker_account_snapshot (id, provider, account_type, balance, equity, currency)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            provider=excluded.provider,
            account_type=excluded.account_type,
            balance=excluded.balance,
            equity=excluded.equity,
            currency=excluded.currency,
            updated_at=CURRENT_TIMESTAMP
    """, (
        metadata["provider"], metadata["account_type"], metadata["balance"],
        metadata["equity"], metadata["currency"],
    ))
    conn.commit()
    conn.close()


def get_saved_broker_account_snapshot():
    init_db()
    conn = get_connection()
    row = conn.execute("SELECT * FROM broker_account_snapshot WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {
        "provider": config.MARKET_DATA_PROVIDER,
        "account_type": "unavailable",
        "balance": None,
        "equity": None,
        "currency": None,
        "updated_at": None,
    }


def get_recent_losses(n=5):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT outcome FROM trades
        WHERE outcome IS NOT NULL AND simulation_risk_amount IS NOT NULL
        ORDER BY closed_at DESC LIMIT ?
    """, (n,))
    rows = c.fetchall()
    conn.close()
    losses = []
    for row in rows:
        if row["outcome"] == "loss":
            losses.append("loss")
        else:
            break
    return losses


def get_daily_stats(target_date=None):
    target = (target_date or date.today()).isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
               AVG(rr_achieved) as avg_rr
        FROM trades WHERE DATE(opened_at) = ?
    """, (target,))
    row = dict(c.fetchone())
    conn.close()
    row["avg_rr"] = round(row["avg_rr"] or 0, 2)
    return row


def get_weekly_stats():
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
               AVG(rr_achieved) as avg_rr
        FROM trades WHERE DATE(opened_at) >= ?
    """, (week_ago,))
    row = dict(c.fetchone())
    conn.close()
    row["avg_rr"] = round(row["avg_rr"] or 0, 2)
    return row


def get_all_trades():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY opened_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_active_setups(limit=20):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT s.*,
               COALESCE((SELECT a.action FROM setup_action_log a
                         WHERE a.setup_id=s.id ORDER BY a.id DESC LIMIT 1), 'UNREVIEWED')
                   AS tracking_action,
               (SELECT a.reason FROM setup_action_log a
                WHERE a.setup_id=s.id ORDER BY a.id DESC LIMIT 1) AS tracking_reason,
               (SELECT a.recorded_at FROM setup_action_log a
                WHERE a.setup_id=s.id ORDER BY a.id DESC LIMIT 1) AS tracking_recorded_at,
               mo.status AS modeled_status,
               mo.source AS modeled_source,
               mo.fill_status AS modeled_fill_status,
               mo.outcome AS modeled_outcome,
               mo.fill_time AS modeled_fill_time,
               mo.fill_price AS modeled_fill_price,
               mo.exit_time AS modeled_exit_time,
               mo.exit_price AS modeled_exit_price,
               mo.outcome_end_time AS modeled_outcome_end_time,
               mo.gross_r_multiple AS modeled_gross_r,
               mo.mfe_r AS modeled_mfe_r,
               mo.mae_r AS modeled_mae_r,
               mo.bars_held AS modeled_bars_held,
               mo.tp1_reached AS modeled_tp1_reached,
               mo.tp2_reached AS modeled_tp2_reached,
               mo.stop_reached AS modeled_stop_reached,
               mo.notes AS modeled_notes,
               mo.evaluated_at AS modeled_evaluated_at,
               t.id AS linked_trade_id,
               t.outcome AS journal_outcome,
               t.gross_r_multiple AS journal_gross_r,
               t.net_r_multiple AS journal_net_r,
               t.execution_mode AS journal_execution_mode,
               t.position_size AS journal_position_size,
               t.actual_risk_amount AS journal_actual_risk,
               t.risk_currency AS journal_risk_currency,
               t.transaction_cost_amount AS journal_transaction_costs,
               t.cost_currency AS journal_cost_currency,
               t.opened_at AS journal_opened_at,
               t.entry_triggered_at AS journal_entry_time,
               t.closed_at AS journal_closed_at
        FROM setups s
        LEFT JOIN setup_modeled_outcomes mo ON mo.setup_id=s.id
        LEFT JOIN trades t ON t.id=(
            SELECT t2.id FROM trades t2
            WHERE t2.setup_id=s.id ORDER BY t2.id DESC LIMIT 1
        )
        ORDER BY s.detected_at DESC, s.id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_signal_ledger(limit=1000):
    """Return recent setups with the latest user decision and modeled OHLC result."""
    return get_active_setups(limit)


def get_pending_setup_outcomes(limit=100):
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.id, s.symbol, s.signal_type, s.bias, s.direction, s.detected_at,
               s.entry, s.sl, s.tp1, s.tp2,
               mo.status AS modeled_status
        FROM setups s
        JOIN setup_modeled_outcomes mo ON mo.setup_id=s.id
        WHERE mo.status IN ('PENDING', 'WAITING_FOR_BARS', 'PENDING_ENTRY', 'MODELED_OPEN')
        ORDER BY COALESCE(mo.evaluated_at, '') ASC, s.detected_at ASC, s.id ASC
        LIMIT ?
    """, (max(1, int(limit)),)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def record_setup_decision(setup_id, action, reason=None):
    """Append a user decision. Trade-linked decisions are written by log_trade."""
    action = str(action or "").strip().upper()
    if action not in {"PAPER_TRACKED", "SKIPPED"}:
        raise ValueError("Decision must be PAPER_TRACKED or SKIPPED.")
    reason = str(reason or "").strip() or None
    if action == "SKIPPED" and not reason:
        raise ValueError("A reason is required when skipping a setup.")

    conn = get_connection()
    c = conn.cursor()
    if c.execute("SELECT 1 FROM setups WHERE id=?", (setup_id,)).fetchone() is None:
        conn.close()
        raise ValueError(f"Setup {setup_id} does not exist.")
    c.execute("""
        INSERT INTO setup_action_log (setup_id, action, reason, source)
        VALUES (?, ?, ?, 'dashboard')
    """, (setup_id, action, reason))
    if action == "SKIPPED":
        c.execute("""
            UPDATE setups
            SET reviewed_at=CURRENT_TIMESTAMP,
                lifecycle_state='REVIEWED',
                lifecycle_reason=?
            WHERE id=?
        """, (f"Skipped by user: {reason}", setup_id))
    conn.commit()
    conn.close()
    return True


def update_setup_modeled_outcome(setup_id, outcome):
    """Persist a hypothetical candle-based outcome without changing a trade journal."""
    allowed_statuses = {
        "PENDING", "WAITING_FOR_BARS", "PENDING_ENTRY", "MODELED_OPEN", "DATA_UNAVAILABLE",
        "UNFILLED", "TP1", "STOP_LOSS", "UNRESOLVED", "INVALID_SETUP",
    }
    status = str(outcome.get("status") or "").upper()
    if status not in allowed_statuses:
        raise ValueError(f"Unsupported modeled outcome status: {status}")
    conn = get_connection()
    c = conn.cursor()
    timestamps = {}
    for field in ("fill_time", "exit_time", "outcome_end_time", "evaluated_at"):
        value = outcome.get(field)
        if value is not None and hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            value = value.isoformat()
        timestamps[field] = value
    c.execute("""
        INSERT INTO setup_modeled_outcomes (
            setup_id, status, source, fill_status, outcome, fill_time, fill_price,
            exit_time, exit_price, outcome_end_time, gross_r_multiple, mfe_r, mae_r,
            bars_held, tp1_reached, tp2_reached, stop_reached, notes, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(setup_id) DO UPDATE SET
            status=excluded.status,
            source=excluded.source,
            fill_status=excluded.fill_status,
            outcome=excluded.outcome,
            fill_time=excluded.fill_time,
            fill_price=excluded.fill_price,
            exit_time=excluded.exit_time,
            exit_price=excluded.exit_price,
            outcome_end_time=excluded.outcome_end_time,
            gross_r_multiple=excluded.gross_r_multiple,
            mfe_r=excluded.mfe_r,
            mae_r=excluded.mae_r,
            bars_held=excluded.bars_held,
            tp1_reached=excluded.tp1_reached,
            tp2_reached=excluded.tp2_reached,
            stop_reached=excluded.stop_reached,
            notes=excluded.notes,
            evaluated_at=excluded.evaluated_at
    """, (
        setup_id, status, outcome.get("source"), outcome.get("fill_status"),
        outcome.get("outcome"), timestamps["fill_time"], outcome.get("fill_price"),
        timestamps["exit_time"], outcome.get("exit_price"), timestamps["outcome_end_time"],
        outcome.get("gross_r_multiple"), outcome.get("mfe_r"), outcome.get("mae_r"),
        outcome.get("bars_held"), outcome.get("tp1_reached"), outcome.get("tp2_reached"),
        outcome.get("stop_reached"), outcome.get("notes"), timestamps["evaluated_at"],
    ))
    conn.commit()
    conn.close()
    return True


def get_recent_symbol_setups(symbol, limit=10):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM setups WHERE symbol=? ORDER BY detected_at DESC, id DESC LIMIT ?",
        (symbol, limit),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_latest_symbol_setup(symbol):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM setups WHERE symbol=? ORDER BY detected_at DESC, id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def has_seen_setup_zone(symbol, direction, zone):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT 1
        FROM setups
        WHERE symbol=? AND UPPER(COALESCE(direction, ''))=? AND setup_zone=?
        LIMIT 1
        """,
        (symbol, str(direction or "").upper(), zone),
    ).fetchone()
    conn.close()
    return row is not None


def get_latest_market_bar(symbol, timeframe="M15", source="BIQUOTE"):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT bar_time, open, high, low, close
        FROM market_bars
        WHERE source=? AND symbol=? AND timeframe=?
        ORDER BY bar_time DESC LIMIT 1
    """, (source, symbol, timeframe))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_setup_lifecycle(setup_id, state, reason, entry_touched_at=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE setups
        SET lifecycle_state=?, lifecycle_reason=?, entry_touched_at=COALESCE(entry_touched_at, ?)
        WHERE id=? AND (
            lifecycle_state IS NOT ? OR lifecycle_reason IS NOT ?
            OR (entry_touched_at IS NULL AND ? IS NOT NULL)
        )
    """, (state, reason, entry_touched_at, setup_id, state, reason, entry_touched_at))
    updated = c.rowcount > 0
    if updated:
        conn.commit()
    conn.close()
    return updated


def record_setup_notification(setup_id, status, error=None):
    """Persist the Telegram delivery result without storing credentials or request URLs."""
    attempted_at = datetime.now(timezone.utc).isoformat()
    sent_at = attempted_at if status == "sent" else None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE setups
        SET telegram_status=?, telegram_error=?, telegram_attempted_at=?, telegram_sent_at=?
        WHERE id=?
    """, (status, str(error)[:500] if error else None, attempted_at, sent_at, setup_id))
    updated = cursor.rowcount > 0
    if updated:
        conn.commit()
    conn.close()
    return updated


def record_setup_lifecycle_notification(setup_id, status, error=None):
    attempted_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE setups
        SET lifecycle_telegram_status=?, lifecycle_telegram_error=?,
            lifecycle_telegram_attempted_at=?
        WHERE id=?
    """, (status, str(error)[:500] if error else None, attempted_at, setup_id))
    updated = cursor.rowcount > 0
    if updated:
        conn.commit()
    conn.close()
    return updated


def apply_setup_event(setup_id, event, reason):
    if setup_id is None:
        return False

    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        "SELECT lifecycle_state FROM setups WHERE id=?",
        (setup_id,),
    ).fetchone()
    if row is None:
        conn.close()
        return False

    current_state = str(row["lifecycle_state"] or "NO_SETUP").upper()
    next_state = transition_state(current_state, event)
    if next_state == current_state:
        conn.close()
        return False

    updated = update_setup_lifecycle(setup_id, next_state, reason)
    conn.close()
    return updated


def resolve_setup_outcome(setup_id, outcome, reason):
    if setup_id is None:
        return False

    outcome = str(outcome or "").upper()
    if not outcome:
        return False

    valid_outcomes = {"TP1_HIT", "BREAKEVEN", "TP2_HIT", "STOPPED_OUT", "INVALIDATED", "REVIEWED"}
    if outcome not in valid_outcomes:
        return False

    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        "SELECT lifecycle_state FROM setups WHERE id=?",
        (setup_id,),
    ).fetchone()
    if row is None:
        conn.close()
        return False

    current_state = str(row["lifecycle_state"] or "NO_SETUP").upper()
    if current_state == "ACTIVE":
        allowed = {"TP1_HIT", "BREAKEVEN", "TP2_HIT", "STOPPED_OUT", "INVALIDATED"}
    elif current_state in {"TP1_HIT", "BREAKEVEN", "TP2_HIT", "STOPPED_OUT", "INVALIDATED"}:
        allowed = {current_state, outcome}
    else:
        allowed = {outcome}

    if outcome not in allowed and current_state not in {"NO_SETUP"}:
        conn.close()
        return False

    updated = update_setup_lifecycle(setup_id, outcome, reason)
    conn.close()
    return updated


def mark_setup_reviewed(setup_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE setups
        SET reviewed_at=CURRENT_TIMESTAMP,
            lifecycle_state='REVIEWED',
            lifecycle_reason='Dismissed by the user; retained in history.'
        WHERE id=?
    """, (setup_id,))
    conn.commit()
    conn.close()


def get_trade_for_setup(setup_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE setup_id=? ORDER BY opened_at DESC LIMIT 1", (setup_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_trading_allowed():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT trading_allowed, logged_at FROM risk_log WHERE account_scope='SIMULATION' ORDER BY logged_at DESC, id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row is None or row["trading_allowed"] is None:
        return None
    try:
        logged_at = datetime.fromisoformat(str(row["logged_at"]).replace("Z", "+00:00"))
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - logged_at.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        return None
    if age_seconds < 0 or age_seconds > max(180, config.SCAN_INTERVAL * 3):
        return None
    return bool(row["trading_allowed"])


def get_journal_entries():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM journal_entries ORDER BY entry_date DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_risk_log(limit=100):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM risk_log WHERE account_scope='SIMULATION' ORDER BY logged_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
