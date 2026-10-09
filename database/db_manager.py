import sqlite3
import json
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
    if "lifecycle_state" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN lifecycle_state TEXT")
    if "lifecycle_reason" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN lifecycle_reason TEXT")
    if "reviewed_at" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN reviewed_at TIMESTAMP")
    if "simulation_plan" not in setup_columns:
        c.execute("ALTER TABLE setups ADD COLUMN simulation_plan TEXT")
    for name, definition in (
        ("ai_decision", "TEXT"),
        ("ai_quality_score", "INTEGER"),
        ("ai_confidence", "TEXT"),
        ("ai_summary", "TEXT"),
        ("ai_reasons", "TEXT"),
        ("ai_invalidations", "TEXT"),
        ("ai_risk_note", "TEXT"),
        ("ai_reviewed_at", "TIMESTAMP"),
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
            opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            session TEXT,
            grade TEXT,
            score INTEGER,
            entry REAL,
            sl REAL,
            tp REAL,
            exit_price REAL,
            outcome TEXT,
            rr_achieved REAL,
            notes TEXT,
            chart_path TEXT,
            FOREIGN KEY (setup_id) REFERENCES setups(id)
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
        ("simulation_risk_amount", "REAL"),
        ("simulation_entry_balance", "REAL"),
        ("simulation_pnl", "REAL"),
        ("simulation_position_size", "REAL"),
        ("simulation_sizing_status", "TEXT"),
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


def save_setup(symbol, timeframe, analysis, scoring, chart_path=None, simulation_plan=None, lifecycle_state="ACTIVE", lifecycle_reason="Signal fired and setup became active", ai_review=None):
    conn = get_connection()
    c = conn.cursor()
    levels = analysis.get("levels") or {}
    ai_review = ai_review or {}
    c.execute("""
        INSERT INTO setups (
            symbol, timeframe, signal_type, bias, grade, score, conditions,
            entry, sl, tp1, tp2, session, chart_path, simulation_plan,
            lifecycle_state, lifecycle_reason,
            ai_decision, ai_quality_score, ai_confidence, ai_summary,
            ai_reasons, ai_invalidations, ai_risk_note, ai_reviewed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, timeframe,
        (analysis.get("signal") or {}).get("type"),
        analysis.get("bias"),
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
        ai_review.get("decision"),
        ai_review.get("quality_score"),
        ai_review.get("confidence"),
        ai_review.get("summary"),
        json.dumps(ai_review.get("reasons", [])),
        json.dumps(ai_review.get("invalidations", [])),
        ai_review.get("risk_note"),
        datetime.now(timezone.utc).isoformat() if ai_review else None,
    ))
    setup_id = c.lastrowid
    conn.commit()
    conn.close()
    return setup_id


def log_trade(symbol, direction, entry, sl, tp, grade=None, score=None, session=None,
              setup_id=None, notes=None, simulation_plan=None):
    init_db()
    conn = get_connection()
    c = conn.cursor()
    account = _get_or_create_simulation_account(c)
    plan = simulation_plan or {}
    c.execute("""
        INSERT INTO trades (
            symbol, direction, setup_id, session, grade, score, entry, sl, tp, notes,
            simulation_risk_amount, simulation_entry_balance,
            simulation_position_size, simulation_sizing_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, direction, setup_id, session, grade, score, entry, sl, tp, notes,
        plan.get("risk_amount"), account["current_balance"],
        plan.get("position_size"), plan.get("sizing_status", "NOT_CALCULATED"),
    ))
    trade_id = c.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def close_trade(trade_id, exit_price, outcome, rr_achieved=None, notes=None):
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
    if outcome == "win" and (rr_achieved is None or float(rr_achieved) <= 0):
        risk_distance = abs(float(trade["entry"]) - float(trade["sl"]))
        is_buy = str(trade["direction"] or "").upper() in {"BUY", "LONG"}
        profit_distance = (
            float(exit_price) - float(trade["entry"])
            if is_buy else float(trade["entry"]) - float(exit_price)
        )
        if risk_distance <= 0 or profit_distance <= 0:
            conn.close()
            raise ValueError("A winning trade needs a profitable exit and a valid stop distance.")
        rr_achieved = profit_distance / risk_distance
    elif outcome == "loss":
        rr_achieved = -1.0
    elif outcome == "breakeven":
        rr_achieved = 0.0
    simulation_pnl = None
    if trade["simulation_risk_amount"] is not None:
        risk_amount = float(trade["simulation_risk_amount"])
        if outcome == "loss":
            simulation_pnl = -risk_amount
        elif outcome == "win":
            simulation_pnl = risk_amount * float(rr_achieved or 0.0)
        else:
            simulation_pnl = 0.0
    c.execute("""
        UPDATE trades
        SET exit_price=?, outcome=?, rr_achieved=?, notes=?, simulation_pnl=?, closed_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (exit_price, outcome, rr_achieved, notes, simulation_pnl, trade_id))
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
    c.execute("SELECT * FROM setups ORDER BY detected_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


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


def update_setup_lifecycle(setup_id, state, reason):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE setups SET lifecycle_state=?, lifecycle_reason=?
        WHERE id=? AND (lifecycle_state IS NOT ? OR lifecycle_reason IS NOT ?)
    """, (state, reason, setup_id, state, reason))
    updated = c.rowcount > 0
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
