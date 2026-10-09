import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone

from database.db_manager import (
    init_db, get_all_trades, get_active_setups,
    get_daily_stats, get_weekly_stats, get_risk_log,
    get_journal_entries, save_journal_entry, log_trade, close_trade,
    get_latest_market_bar, get_latest_trading_allowed,
    get_trade_for_setup, update_setup_lifecycle, mark_setup_reviewed,
    get_simulation_performance, get_saved_broker_account_snapshot,
)
from risk.risk_manager import RiskManager
from scanner.data_provider import get_symbol_info
from scanner.news_filter import get_upcoming_events, get_next_high_impact, is_news_blackout
from dashboard.signal_lifecycle import evaluate_setup
from dashboard.setup_table import build_active_setups_table
import config

st.set_page_config(
    page_title="Trading OS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
 :root {
    color-scheme: dark;
    --void: #0A0A0A;
    --metal: #121212;
    --edge: #1A1A1A;
    --gold: #D4AF37;
    --red: #D32F2F;
    --white: #FFFFFF;
    --muted: #8B8580;
}
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    background: var(--void) !important;
    color: var(--white) !important;
}
[data-testid="stHeader"] { background: rgba(10, 10, 10, 0.92); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #10100E 0%, #080808 100%);
    border-right: 1px solid rgba(212, 175, 55, 0.22);
    box-shadow: 12px 0 36px rgba(0, 0, 0, 0.55), inset -1px 0 0 rgba(255,255,255,0.025);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #C7B878;
    text-transform: uppercase;
    font-size: 0.78rem;
}
[data-testid="stSidebar"] [role="radiogroup"] label {
    border-left: 2px solid transparent;
    padding: 0.55rem 0.7rem;
    transition: all 160ms ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    border-left-color: var(--gold);
    color: var(--white);
    background: linear-gradient(90deg, rgba(212,175,55,0.12), transparent 78%);
    box-shadow: inset 8px 0 18px -16px var(--gold);
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    display: inline-block;
    margin: 0.2rem 0.15rem;
    padding: 0.35rem 0.55rem;
    color: var(--gold);
    background: #12110D;
    border: 1px solid rgba(212,175,55,0.3);
    border-radius: 3px;
}
[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(28,27,23,0.96), rgba(13,13,13,0.98));
    border: 1px solid rgba(212,175,55,0.25);
    border-radius: 5px;
    padding: 0.85rem 1rem;
    box-shadow: 0 14px 30px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.035), 0 0 20px rgba(212,175,55,0.045);
    transform: perspective(900px) translateZ(0);
    transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}
[data-testid="stMetric"]:hover {
    transform: perspective(900px) translateY(-3px) rotateX(1deg);
    border-color: rgba(212,175,55,0.65);
    box-shadow: 0 20px 34px rgba(0,0,0,0.65), 0 0 24px rgba(212,175,55,0.12);
}
[data-testid="stMetricLabel"] p { color: var(--muted) !important; text-transform: uppercase; font-size: 0.68rem; }
[data-testid="stMetricValue"] { color: var(--white); font-size: 1.55rem; }
[data-testid="stMetricDelta"] { color: var(--gold) !important; }
h1, h2, h3 { color: var(--white); }
[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"] p { color: #C7C2B8; }
hr { border-color: rgba(212,175,55,0.18) !important; }
button[kind="secondary"], [data-testid="stButton"] button {
    color: var(--gold);
    background: linear-gradient(145deg, #17150F, #0B0B0A);
    border: 1px solid rgba(212,175,55,0.72);
    border-radius: 4px;
    box-shadow: 0 5px 14px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06);
    transition: transform 120ms ease, box-shadow 120ms ease;
}
[data-testid="stButton"] button:hover { border-color: var(--gold); box-shadow: 0 0 18px rgba(212,175,55,0.2); }
[data-testid="stButton"] button:active { transform: translateY(2px); box-shadow: inset 0 3px 8px rgba(0,0,0,0.8); }
[data-testid="stExpander"] {
    background: #0D0D0D;
    border: 1px solid rgba(212,175,55,0.24);
    border-radius: 4px;
}
[data-testid="stExpander"] summary { color: var(--gold); text-transform: uppercase; font-size: 0.78rem; }
[data-testid="stExpander"] details[open] { border-color: rgba(212,175,55,0.45); }
.impact-high { color: #D32F2F; font-weight: 700; }
.impact-medium { color: #D4AF37; font-weight: 700; }
.impact-low { color: #D4AF37; }
.countdown-box {
    background: linear-gradient(90deg, rgba(211,47,47,0.08), #0A0A0A 45%);
    border: 1px solid #D32F2F;
    border-left: 4px solid #D32F2F;
    border-radius: 2px;
    padding: 11px 16px;
    margin-bottom: 12px;
    color: #D4AF37;
    box-shadow: 0 0 22px rgba(211,47,47,0.08), inset 0 0 18px rgba(211,47,47,0.035);
    text-transform: uppercase;
    font-size: 0.82rem;
}
.signal-card {
    position: relative;
    background: linear-gradient(150deg, #191815 0%, #121212 40%, #0C0C0C 100%);
    border: 1px solid #1A1A1A;
    border-top-color: rgba(212,175,55,0.5);
    border-radius: 5px;
    padding: 12px 13px 11px;
    min-height: 300px;
    box-shadow: 0 22px 38px rgba(0,0,0,0.72), 0 7px 12px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.045), 0 0 24px rgba(212,175,55,0.055);
    transform: perspective(1100px) translateY(0) rotateX(0deg);
    transform-style: preserve-3d;
    transition: transform 220ms ease, border-color 220ms ease, box-shadow 220ms ease;
}
.signal-card:hover {
    transform: perspective(1100px) translateY(-7px) rotateX(1.2deg);
    border-color: rgba(212,175,55,0.82);
    box-shadow: 0 30px 48px rgba(0,0,0,0.78), 0 0 30px rgba(212,175,55,0.18), inset 0 1px 0 rgba(255,255,255,0.07);
}
.signal-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1px 0 9px;
    border-bottom: 1px solid rgba(212,175,55,0.22);
    margin-bottom: 8px;
    color: #D4AF37;
    font-weight: 700;
}
.signal-card-title {
    font-size: 0.78rem;
    font-weight: 800;
    text-transform: uppercase;
}
.signal-card-score {
    color: #D4AF37;
    font-size: 0.66rem;
    padding: 3px 6px;
    border-radius: 3px;
    background: rgba(212,175,55,0.07);
    border: 1px solid rgba(212,175,55,0.26);
}
.signal-card-body {
    font-size: 0.82rem;
    color: #FFFFFF;
}
.signal-direction { font-size: 1.45rem; font-weight: 900; line-height: 1.05; margin: 2px 0 8px; text-shadow: 0 0 15px currentColor; }
.signal-direction.sell { color: #D32F2F; }
.signal-direction.buy { color: #D4AF37; }
.signal-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 6px;
    padding: 5px 2px;
    border-bottom: 1px solid rgba(255,255,255,0.055);
}
.signal-row:last-child {
    border-bottom: none;
}
.signal-label {
    color: #8B8580;
    font-size: 0.63rem;
    font-weight: 700;
    text-transform: uppercase;
}
.signal-value {
    font-weight: 700;
    color: #FFFFFF;
    text-align: right;
    overflow-wrap: anywhere;
}
.signal-row.rr .signal-value { color: #D4AF37; font-size: 0.95rem; }
.signal-row.status .signal-value { color: #D4AF37; }
.signal-row.status.expired .signal-value { color: #D32F2F; }
.status-badge {
    display: inline-block;
    padding: 2px 7px;
    border: 1px solid rgba(212,175,55,0.62);
    border-radius: 999px;
    background: linear-gradient(145deg, rgba(212,175,55,0.18), rgba(35,29,12,0.78));
    color: #D4AF37;
    box-shadow: 0 3px 7px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255,255,255,0.1), 0 0 10px rgba(212,175,55,0.1);
    font-size: 0.62rem;
    text-transform: uppercase;
}
.status-badge.expired {
    color: #D32F2F;
    border-color: rgba(211,47,47,0.7);
    background: linear-gradient(145deg, rgba(211,47,47,0.18), rgba(35,12,12,0.8));
    box-shadow: 0 3px 7px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255,255,255,0.08), 0 0 10px rgba(211,47,47,0.1);
}
.signal-reason {
    margin-top: 8px;
    padding-top: 7px;
    border-top: 1px solid rgba(212,175,55,0.16);
    color: #A7A198;
    font-size: 0.69rem;
    line-height: 1.4;
}
[data-testid="stCheckbox"] label {
    color: #D4AF37 !important;
    font-size: 0.73rem;
    text-transform: uppercase;
}
[data-testid="stCheckbox"] [role="checkbox"] {
    border: 1px solid #D4AF37 !important;
    background: #121212 !important;
    box-shadow: inset 0 1px 4px rgba(0,0,0,0.85), 0 0 9px rgba(212,175,55,0.12);
}
[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] {
    background: #D4AF37 !important;
    box-shadow: 0 0 14px rgba(212,175,55,0.45);
}
@media (max-width: 900px) {
    .signal-card { min-height: 0; }
    .signal-direction { font-size: 1.2rem; }
}
/* Phase 2: quiet, readable dashboard palette. */
:root { color-scheme: light; }
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    background: #F7F7F5 !important;
    color: #111827 !important;
    font-family: Inter, Roboto, sans-serif;
}
[data-testid="stHeader"] { background: rgba(247,247,245,0.94); }
[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
    box-shadow: 2px 0 10px rgba(17,24,39,0.035);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #4B5563;
    text-transform: none;
    font-size: 0.84rem;
}
[data-testid="stSidebar"] [role="radiogroup"] label { border-left: 2px solid transparent; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    color: #111827;
    border-left-color: #D4AF37;
    background: #FAF7EB;
    box-shadow: none;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    color: #6B7280;
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
}
h1, h2, h3 { color: #111827; }
[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"] p { color: #4B5563; }
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(17,24,39,0.04);
    transform: none;
}
[data-testid="stMetric"]:hover {
    transform: none;
    border-color: #D1D5DB;
    box-shadow: 0 3px 10px rgba(17,24,39,0.06);
}
[data-testid="stMetricLabel"] p { color: #6B7280 !important; }
[data-testid="stMetricValue"] { color: #111827; }
[data-testid="stMetricDelta"] { color: #6B7280 !important; }
hr { border-color: #E5E7EB !important; }
[data-testid="stButton"] button {
    color: #374151;
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 5px;
    box-shadow: 0 1px 2px rgba(17,24,39,0.04);
}
[data-testid="stButton"] button:hover { color: #111827; border-color: #9CA3AF; box-shadow: 0 2px 5px rgba(17,24,39,0.07); }
[data-testid="stButton"] button:active { transform: translateY(1px); }
[data-testid="stExpander"] { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px; }
[data-testid="stExpander"] summary { color: #374151; text-transform: none; font-size: 0.86rem; }
[data-testid="stExpander"] details[open] { border-color: #D1D5DB; }
.action-indicator {
    margin: 0 0 1rem;
    padding: 1rem 1.15rem;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-left: 4px solid #D4AF37;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(17,24,39,0.035);
}
.action-indicator h2 { margin: 0; color: #111827; font-size: 1.25rem; }
.action-indicator p { margin: 0.3rem 0; color: #4B5563; }
.action-indicator small { color: #6B7280; }
.action-indicator.stand-down { border-left-color: #9CA3AF; }
.action-indicator.stand-down h2 { color: #374151; }
.stand-down {
    width: 100%;
    margin: 0.5rem 0 1rem;
    padding: 1.25rem;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-left: 4px solid #9CA3AF;
    border-radius: 6px;
    color: #111827;
}
.stand-down strong { font-size: 1.15rem; }
.stand-down p { margin: 0.35rem 0; color: #4B5563; }
.stand-down small { color: #6B7280; }
.signal-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-top: 3px solid #D4AF37;
    border-radius: 8px;
    min-height: 0;
    box-shadow: 0 3px 12px rgba(17,24,39,0.055);
    transform: none;
    transition: box-shadow 160ms ease, border-color 160ms ease;
}
.signal-card:hover {
    transform: none;
    border-color: #D1D5DB;
    border-top-color: #D4AF37;
    box-shadow: 0 5px 16px rgba(17,24,39,0.085);
}
.signal-card-header { color: #374151; border-bottom-color: #E5E7EB; }
.signal-card-title { color: #374151; }
.signal-card-score { color: #6B7280; background: #F9FAFB; border-color: #E5E7EB; }
.signal-card-body { color: #111827; }
.signal-direction { text-shadow: none; }
.signal-direction.sell { color: #B91C1C; }
.signal-direction.buy { color: #374151; }
.signal-row { border-bottom-color: #F3F4F6; }
.signal-label { color: #6B7280; }
.signal-value { color: #111827; }
.signal-row.rr .signal-value { color: #8A6D16; }
.signal-reason { border-top-color: #E5E7EB; color: #6B7280; }
.status-badge {
    color: #166534;
    border-color: #BBF7D0;
    background: #F0FDF4;
    box-shadow: none;
}
.status-badge.ready { color: #166534; border-color: #BBF7D0; background: #F0FDF4; }
.status-badge.news-blocked { color: #92400E; border-color: #FDE68A; background: #FFFBEB; }
.status-badge.stale, .status-badge.invalidated, .status-badge.price-unknown { color: #6B7280; border-color: #E5E7EB; background: #F3F4F6; }
.status-badge.reviewed { color: #8A6D16; border-color: #E9DCA6; background: #FBF8EA; }
.status-badge.trade-logged { color: #374151; border-color: #D1D5DB; background: #F9FAFB; }
[data-testid="stCheckbox"] label { color: #374151 !important; text-transform: none; }
[data-testid="stCheckbox"] [role="checkbox"] { border-color: #9CA3AF !important; background: #FFFFFF !important; box-shadow: none; }
[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] { background: #D4AF37 !important; box-shadow: none; }
input[type="radio"], input[type="checkbox"] { accent-color: #D4AF37 !important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { background: #FFFFFF; }
.countdown-box { background: #FFFFFF; border-color: #E5E7EB; border-left-color: #D4AF37; color: #374151; box-shadow: none; text-transform: none; }
</style>
""", unsafe_allow_html=True)

GRADE_EMOJI = {"ELITE": "💎", "A+": "🥇", "A": "🥈", "Standard": "🥉"}
BIAS_ICON = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
IMPACT_COLOR = {"High": "#ef5350", "Medium": "#ffd54f", "Low": "#69f0ae"}


def fmt_countdown(minutes: int) -> str:
    if minutes < 0:
        return f"{abs(minutes)}m ago"
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m"


def human_age(age_minutes):
    if age_minutes is None:
        return "age unavailable"
    if age_minutes < 60:
        return f"{age_minutes}m ago"
    hours, minutes = divmod(age_minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m ago"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h ago"


def render_account_separation():
    simulation = get_simulation_performance()
    broker = get_saved_broker_account_snapshot()
    st.subheader("Simulation Account")
    cols = st.columns(8)
    cols[0].metric("Starting balance", f"${simulation['starting_balance']:.2f}")
    cols[1].metric("Current equity", f"${simulation['equity']:.2f}")
    cols[2].metric("Realized P/L", f"${simulation['realized_pnl']:+.2f}")
    cols[3].metric("Wins / losses", f"{simulation['wins']} / {simulation['losses']}")
    cols[4].metric("Daily drawdown", f"{simulation['daily_drawdown']:.2f}%")
    cols[5].metric("Weekly drawdown", f"{simulation['weekly_drawdown']:.2f}%")
    cols[6].metric("Max drawdown", f"{simulation['max_drawdown']:.2f}%")
    currency = f" {broker['currency']}" if broker.get("currency") else ""
    broker_balance = (
        f"${broker['balance']:,.2f}{currency}"
        if broker.get("balance") is not None else "Unavailable"
    )
    cols[7].metric("Broker account", broker_balance)
    broker_type = str(broker.get("account_type") or "unavailable").upper()
    st.caption(
        f"Strategy simulation is independent. Broker metadata: "
        f"{broker['provider']} / {broker_type}; broker balance is not used for simulation risk."
    )


def build_simulation_trade_plan(symbol, entry, sl):
    account = get_simulation_performance()
    symbol_info = {}
    if config.MARKET_DATA_PROVIDER != "DERIV_DEMO":
        try:
            symbol_info = get_symbol_info(symbol) or {}
        except Exception:
            symbol_info = {}
    return RiskManager().calculate_trade_plan(
        account_balance=account["current_balance"],
        entry=entry,
        sl=sl,
        contract_size=symbol_info.get("contract_size"),
        broker_min_volume=symbol_info.get("volume_min"),
        broker_volume_step=symbol_info.get("volume_step"),
        broker_max_volume=symbol_info.get("volume_max"),
    )


def render_signal_card(setup, lifecycle, rank):
    signal_type = (setup.get("signal_type") or "SETUP").upper()
    grade = setup.get("grade") or "Standard"
    score = setup.get("score") or 0
    bias = (setup.get("bias") or "neutral").lower()
    entry = setup.get("entry")
    sl = setup.get("sl")
    tp1 = setup.get("tp1")
    planned_rr = lifecycle["planned_rr"]
    rr = f"{planned_rr:.1f}R" if planned_rr is not None else "—"
    remaining_rr = lifecycle["remaining_rr"]
    remaining_rr_text = f"{remaining_rr:.1f}R" if remaining_rr is not None else "—"

    conditions = []
    if isinstance(setup.get("conditions"), str):
        try:
            conditions = json.loads(setup.get("conditions") or "[]")
        except Exception:
            conditions = []
    elif isinstance(setup.get("conditions"), list):
        conditions = setup.get("conditions")

    direction_class = "sell" if bias == "bearish" or "SELL" in signal_type else "buy"
    state_class = lifecycle["state"].lower().replace(" ", "-")
    detected = setup.get("detected_at") or ""
    try:
        timestamp = datetime.fromisoformat(detected.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        exact_time = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        exact_time = "UTC time unavailable"

    with st.container():
        st.markdown(
            f"""
            <div class="signal-card">
                <div class="signal-direction {direction_class}">{'SELL' if direction_class == 'sell' else 'BUY'}</div>
                <div class="signal-card-header">
                    <div class="signal-card-title">#{rank} {signal_type}</div>
                    <div class="signal-card-score">{grade} · {score}</div>
                </div>
                <div class="signal-card-body">
                    <div class="signal-row"><div class="signal-label">Pair</div><div class="signal-value">{setup.get('symbol','XAUUSD')}</div></div>
                    <div class="signal-row"><div class="signal-label">Entry</div><div class="signal-value">{entry if entry is not None else '—'}</div></div>
                    <div class="signal-row"><div class="signal-label">SL</div><div class="signal-value">{sl if sl is not None else '—'}</div></div>
                    <div class="signal-row"><div class="signal-label">TP</div><div class="signal-value">{tp1 if tp1 is not None else '—'}</div></div>
                    <div class="signal-row rr"><div class="signal-label">RR</div><div class="signal-value">{rr}</div></div>
                    <div class="signal-row"><div class="signal-label">Remaining RR</div><div class="signal-value">{remaining_rr_text}</div></div>
                    <div class="signal-row"><div class="signal-label">Given</div><div class="signal-value">{human_age(lifecycle['age_minutes'])}</div></div>
                    <div class="signal-row"><div class="signal-label">UTC</div><div class="signal-value">{exact_time}</div></div>
                    <div class="signal-row status"><div class="signal-label">State</div><div class="signal-value"><span class="status-badge {state_class}">{lifecycle['state']}</span></div></div>
                    <div class="signal-reason">{lifecycle['reason']}</div>
                    <div class="signal-reason"><b>Trigger:</b> {', '.join(conditions) if conditions else 'Structure in focus'}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        try:
            simulation_plan = json.loads(setup.get("simulation_plan") or "{}")
        except (TypeError, ValueError):
            simulation_plan = {}
        if simulation_plan:
            size = simulation_plan.get("position_size")
            size_text = f"{size:g}" if size is not None else "not executable"
            st.caption(
                f"Simulation risk ${simulation_plan.get('risk_amount', 0):.2f} · "
                f"planned reward ${simulation_plan.get('expected_profit', 0):.2f} · "
                f"volume {size_text} · {simulation_plan.get('sizing_status', 'unknown')}"
            )

        action_cols = st.columns(2)
        if action_cols[0].button("Reviewed / Dismiss", key=f"review_setup_{setup['id']}"):
            mark_setup_reviewed(setup["id"])
            st.rerun()
        if action_cols[1].button("Log Trade From Setup", key=f"log_setup_{setup['id']}"):
            st.session_state["trade_setup_id"] = setup["id"]
            st.rerun()


def get_dashboard_setups():
    setups = get_active_setups(500)
    evaluated = []
    market_bars = {}
    news_states = {
        symbol: is_news_blackout(symbol) if config.NEWS_FILTER_ENABLED else (False, None)
        for symbol in config.SYMBOLS
    }
    for setup in setups:
        symbol = setup.get("symbol", "")
        if symbol not in market_bars:
            market_bars[symbol] = get_latest_market_bar(
                symbol, "M15", config.MARKET_DATA_SOURCE_LABEL
            )
        if symbol not in news_states:
            news_states[symbol] = is_news_blackout(symbol) if config.NEWS_FILTER_ENABLED else (False, None)
        news_blocked, news_reason = news_states[symbol]
        trade = get_trade_for_setup(setup["id"])
        lifecycle = evaluate_setup(
            setup,
            market_bars[symbol],
            max_age_minutes=config.MAX_SETUP_AGE_MINUTES,
            max_market_age_minutes=config.MAX_MARKET_BAR_AGE_MINUTES,
            news_blocked=news_blocked,
            news_reason=news_reason,
            reviewed=bool(setup.get("reviewed_at")),
            trade_logged=trade is not None,
        )
        update_setup_lifecycle(setup["id"], lifecycle["state"], lifecycle["reason"])
        evaluated.append((setup, lifecycle))

    ready = [(setup, state) for setup, state in evaluated if state["state"] == "READY"]
    ready.sort(key=lambda item: (
        item[1]["age_minutes"],
        -(item[1]["remaining_rr"] or 0),
        -(item[0].get("score") or 0),
    ))
    history = [(setup, state) for setup, state in evaluated if state["state"] != "READY"]
    return ready, history, news_states


def render_setup_trade_form(setups_by_id):
    setup_id = st.session_state.get("trade_setup_id")
    setup = setups_by_id.get(setup_id)
    if setup is None:
        return
    st.subheader(f"Trade journal entry from setup #{setup_id}")
    with st.form(f"trade_from_setup_{setup_id}"):
        col1, col2 = st.columns(2)
        direction = col1.selectbox("Direction", ["Buy", "Sell"], index=0 if setup["bias"] == "bullish" else 1)
        entry = col2.number_input("Entry", value=float(setup["entry"] or 0), format="%.5f")
        col3, col4 = st.columns(2)
        stop = col3.number_input("Stop Loss", value=float(setup["sl"] or 0), format="%.5f")
        target = col4.number_input("Take Profit", value=float(setup["tp1"] or 0), format="%.5f")
        notes = st.text_input("Notes")
        save_trade = st.form_submit_button("Save to Trade Journal", type="primary")
    if save_trade:
        simulation_plan = build_simulation_trade_plan(
            setup["symbol"], entry, stop,
        )
        log_trade(
            setup["symbol"], direction, entry, stop, target,
            grade=setup.get("grade"), score=setup.get("score"),
            session=setup.get("session"), setup_id=setup_id, notes=notes,
            simulation_plan=simulation_plan,
        )
        st.session_state.pop("trade_setup_id", None)
        st.success("Trade linked to setup. Record the outcome from Trade Journal when it closes.")
        st.rerun()


def main():
    init_db()

    with st.sidebar:
        st.title("📊 Trading OS")
        st.caption(datetime.now().strftime("%Y-%m-%d %H:%M UTC"))
        st.divider()
        page = st.radio(
            "Navigation",
            ["Dashboard", "Economic Calendar", "Active Setups",
             "Trade Journal", "Analytics", "Daily Review", "Risk Status"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"Pairs: {', '.join(config.SYMBOLS)}")
        st.caption(f"TF: {config.HTF} → {config.MTF} → {config.LTF}")
        news_state = "✅ ON" if config.NEWS_FILTER_ENABLED else "❌ OFF"
        st.caption(f"News filter: {news_state}")
        if st.button("🔄 Refresh", width="stretch"):
            st.rerun()

    if page == "Dashboard":
        show_dashboard()
    elif page == "Economic Calendar":
        show_calendar()
    elif page == "Active Setups":
        show_active_setups()
    elif page == "Trade Journal":
        show_journal()
    elif page == "Analytics":
        show_analytics()
    elif page == "Daily Review":
        show_daily_review()
    elif page == "Risk Status":
        show_risk_status()


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────
@st.fragment(run_every=f"{config.DASHBOARD_REFRESH_SECONDS}s")
def show_dashboard():
    render_account_separation()
    ready, history, news_states = get_dashboard_setups()
    latest_news_lock = next((state for state in news_states.values() if state[0]), (False, None))
    trading_allowed = get_latest_trading_allowed()
    setups_by_id = {setup["id"]: setup for setup, _ in ready + history}

    if ready:
        action_text = "1 VIABLE SETUP — REVIEW" if len(ready) == 1 else f"{len(ready)} VIABLE SETUPS — REVIEW"
        action_reason = "Eligible setups passed age, live-price, RR, score, and news checks."
    else:
        action_text = "NO TRADE — STAND DOWN"
        counts = {}
        for _, state in history:
            counts[state["state"]] = counts.get(state["state"], 0) + 1
        if not history:
            action_reason = "No setups have been recorded. Wait for a confirmed setup; do not force a trade."
        else:
            reasons = ", ".join(f"{count} {state.lower()}" for state, count in sorted(counts.items()))
            action_reason = f"No viable setups — {reasons}. Do not force a trade."

    action_ready = ready if trading_allowed is not False else []
    if trading_allowed is False:
        action_text = "NO TRADE — STAND DOWN"
        action_reason = "Risk manager has suspended trading. Resolve the risk restriction before acting."
    next_ev = get_next_high_impact()
    next_news = (
        f"Next high-impact news: {next_ev['currency']} {fmt_countdown(next_ev['minutes_away'])}"
        if next_ev else "No upcoming high-impact event in the next 48h."
    )
    action_class = "action-indicator" if action_ready else "action-indicator stand-down"
    st.markdown(
        f"<section class='{action_class}'><h2>{action_text}</h2>"
        f"<p>{action_reason}</p><small>{next_news}</small></section>",
        unsafe_allow_html=True,
    )

    if "trade_setup_id" in st.session_state:
        render_setup_trade_form(setups_by_id)

    if action_ready:
        st.subheader("Best eligible setup")
        render_signal_card(action_ready[0][0], action_ready[0][1], 1)
        if len(action_ready) > 1:
            with st.expander(f"View all other viable setups ({len(action_ready) - 1})", expanded=False):
                for idx, (setup, lifecycle) in enumerate(action_ready[1:], start=2):
                    render_signal_card(setup, lifecycle, idx)
    risk_col, news_col = st.columns(2)
    risk_text = "UNKNOWN — awaiting scanner risk check" if trading_allowed is None else (
        "ALLOWED" if trading_allowed else "BLOCKED"
    )
    news_text = "LOCKED" if latest_news_lock[0] else "CLEAR"
    risk_col.metric("Risk manager", risk_text)
    news_col.metric("High-impact news", news_text, latest_news_lock[1] if latest_news_lock[1] else None)

    daily = get_daily_stats()
    weekly = get_weekly_stats()

    d_total = daily["total"] or 0
    d_wins = daily["wins"] or 0
    w_total = weekly["total"] or 0
    w_wins = weekly["wins"] or 0

    with st.expander("Performance summary", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Today Trades", d_total)
        c2.metric("Today Win Rate", f"{d_wins/d_total*100:.0f}%" if d_total else "—")
        c3.metric("Today Avg RR", f"{daily['avg_rr']:.2f}" if daily["avg_rr"] else "—")
        c4.metric("Week Trades", w_total)
        c5.metric("Week Win Rate", f"{w_wins/w_total*100:.0f}%" if w_total else "—")

    with st.expander(f"Setup history ({len(history)})", expanded=True):
        if history:
            for setup, lifecycle in history:
                age = human_age(lifecycle["age_minutes"])
                st.write(
                    f"**{lifecycle['state']}** · {setup.get('symbol')} · "
                    f"{setup.get('signal_type')} · {age} · {lifecycle['reason']}"
                )
        else:
            st.caption("No historical setups.")

    with st.expander("Constitution", expanded=True):
        st.write(f"Max risk/trade: **{config.MAX_RISK_PER_TRADE}%**")
        st.write(f"Daily DD limit: **{config.MAX_DAILY_DRAWDOWN}%**")
        st.write(f"Weekly DD limit: **{config.MAX_WEEKLY_DRAWDOWN}%**")
        st.write(f"Max consec. losses: **{config.MAX_CONSECUTIVE_LOSSES}**")
        st.write(f"News block pre: **{config.NEWS_BLOCK_MINUTES_BEFORE}m**")
        st.write(f"News block post: **{config.NEWS_BLOCK_MINUTES_AFTER}m**")

    risk_log = get_risk_log(50)
    if risk_log:
        with st.expander("Equity / Drawdown", expanded=True):
            df_r = pd.DataFrame(risk_log).sort_values("logged_at")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_r["logged_at"], y=df_r["equity"],
                                      name="Equity", line=dict(color="#26a69a")))
            fig.add_trace(go.Scatter(x=df_r["logged_at"], y=df_r["daily_dd"],
                                      name="Daily DD %", yaxis="y2",
                                      line=dict(color="#ef5350", dash="dash")))
            fig.update_layout(
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF",
                font=dict(color="#111827"),
                yaxis2=dict(overlaying="y", side="right", title="DD %", tickfont=dict(color="#6B7280")),
                xaxis=dict(gridcolor="#E5E7EB", tickfont=dict(color="#6B7280")),
                yaxis=dict(gridcolor="#E5E7EB", tickfont=dict(color="#6B7280")),
                title_font_color="#111827",
                height=280, margin=dict(l=0, r=0, t=20, b=0),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, width="stretch")


# ─────────────────────────────────────────────
# Economic Calendar
# ─────────────────────────────────────────────
def show_calendar():
    st.header("Economic Calendar")
    st.caption("Source: ForexFactory — refreshed hourly. High-impact events trigger news blackout in the scanner.")

    col1, col2, col3 = st.columns(3)
    hours = col1.slider("Look-ahead (hours)", 6, 72, 24, step=6)
    impact_sel = col2.multiselect("Impact", ["High", "Medium", "Low"], default=["High", "Medium"])
    tracked = col3.multiselect(
        "Currency filter",
        ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"],
        default=["USD", "EUR", "GBP", "JPY"],
    )

    events = get_upcoming_events(hours=hours, impacts=tuple(impact_sel))
    if tracked:
        events = [e for e in events if e["currency"].upper() in tracked]

    if not events:
        st.info("No events found for the selected filters.")
        return

    # Next high-impact countdown card
    high_events = [e for e in events if e["impact"] == "High" and e["minutes_away"] > 0]
    if high_events:
        nxt = high_events[0]
        mins = nxt["minutes_away"]
        urgency = "#ef5350" if mins <= 30 else "#ffd54f" if mins <= 60 else "#4fc3f7"
        st.markdown(
            f"<div class='countdown-box'>"
            f"⏰ <b>Next HIGH-IMPACT</b>: "
            f"<span style='color:{urgency}'>{nxt['currency']} — {nxt['title']}</span>"
            f"&nbsp;&nbsp;<b style='color:{urgency}; font-size:1.3rem'>{fmt_countdown(mins)}</b>"
            f"<br><small style='color:#787b86'>Forecast: {nxt['forecast']} &nbsp;|&nbsp; "
            f"Previous: {nxt['previous']}</small>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Build display table
    rows = []
    now_utc = datetime.now(timezone.utc)
    for ev in events:
        local_str = ev["datetime_utc"].strftime("%a %d %b  %H:%M UTC")
        mins = ev["minutes_away"]
        if mins < 0:
            cd = f"{abs(mins)}m ago"
        elif mins == 0:
            cd = "🔴 NOW"
        else:
            cd = fmt_countdown(mins)

        blackout = (
            ev["impact"] == "High"
            and -config.NEWS_BLOCK_MINUTES_AFTER <= mins <= config.NEWS_BLOCK_MINUTES_BEFORE
        )
        rows.append({
            "Time (UTC)": local_str,
            "Countdown": cd,
            "Currency": ev["currency"],
            "Impact": ev["impact"],
            "Event": ev["title"],
            "Forecast": ev["forecast"],
            "Previous": ev["previous"],
            "Actual": ev["actual"],
            "Scanner": "🚫 BLOCKED" if blackout else "✅ clear",
        })

    df = pd.DataFrame(rows)

    def color_impact(val):
        colors = {"High": "color: #ef5350; font-weight:700",
                  "Medium": "color: #ffd54f; font-weight:600",
                  "Low": "color: #69f0ae"}
        return colors.get(val, "")

    def color_scanner(val):
        return "color: #ef5350; font-weight:700" if "BLOCKED" in str(val) else "color: #69f0ae"

    styled = df.style.applymap(color_impact, subset=["Impact"]) \
                     .applymap(color_scanner, subset=["Scanner"])
    st.dataframe(styled, width="stretch", hide_index=True)

    # Timeline chart
    st.divider()
    st.subheader("Timeline")
    if rows:
        df_chart = pd.DataFrame([
            {
                "Event": f"{r['Currency']} — {r['Event'][:40]}",
                "Time": events[i]["datetime_utc"],
                "Impact": r["Impact"],
            }
            for i, r in enumerate(rows)
        ])
        color_map = {"High": "#ef5350", "Medium": "#ffd54f", "Low": "#69f0ae"}
        fig = px.scatter(
            df_chart, x="Time", y="Event", color="Impact",
            color_discrete_map=color_map,
            title="Upcoming Events Timeline",
        )
        fig.add_vline(x=now_utc, line_dash="dash", line_color="#4fc3f7",
                      annotation_text="Now", annotation_position="top right")
        fig.update_layout(height=max(300, len(rows) * 30 + 80),
                          margin=dict(l=0, r=0, t=40, b=0),
                          yaxis=dict(tickfont=dict(size=10)))
        st.plotly_chart(fig, width="stretch")


# ─────────────────────────────────────────────
# Active Setups
# ─────────────────────────────────────────────
def show_active_setups():
    st.header("Active Setups")
    setups = get_active_setups(50)
    if not setups:
        st.info("No setups in database yet.")
        return

    df = pd.DataFrame(setups)
    grades = df["grade"].dropna().unique().tolist()
    selected = st.multiselect("Grade filter", ["ELITE", "A+", "A", "Standard"], default=grades)
    df = df[df["grade"].isin(selected)]

    if df.empty:
        st.info("No setups match the filter.")
        return

    st.dataframe(
        build_active_setups_table(df.to_dict("records")),
        width="stretch",
    )

    if st.checkbox("Show chart screenshots"):
        for s in setups[:5]:
            cp = s.get("chart_path")
            if cp and os.path.exists(cp):
                st.image(cp, caption=f"{s['symbol']} — {s['grade']} (Score {s['score']})",
                         width="stretch")


# ─────────────────────────────────────────────
# Trade Journal
# ─────────────────────────────────────────────
def show_journal():
    st.header("Trade Journal")
    render_account_separation()
    tab1, tab2 = st.tabs(["Log Trade", "View Trades"])

    with tab1:
        with st.form("log_trade_form"):
            c1, c2 = st.columns(2)
            symbol = c1.selectbox("Symbol", config.SYMBOLS)
            direction = c2.radio("Direction", ["Buy", "Sell"], horizontal=True)
            c3, c4, c5 = st.columns(3)
            entry = c3.number_input("Entry", format="%.5f", value=0.0)
            sl = c4.number_input("Stop Loss", format="%.5f", value=0.0)
            tp = c5.number_input("Take Profit", format="%.5f", value=0.0)
            grade = st.selectbox("Setup Grade", ["Standard", "A", "A+", "ELITE"])
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Log Trade", type="primary"):
                simulation_plan = build_simulation_trade_plan(symbol, entry, sl)
                tid = log_trade(
                    symbol, direction, entry, sl, tp, grade=grade, notes=notes,
                    simulation_plan=simulation_plan,
                )
                st.success(f"Trade #{tid} logged.")
                st.caption(
                    f"Simulation risk ${simulation_plan['risk_amount']:.2f}; "
                    f"2R reward ${simulation_plan['expected_profit']:.2f}; "
                    f"volume status: {simulation_plan['sizing_status']}"
                )
                if simulation_plan["sizing_status"] != "OK":
                    st.warning(
                        "Simulation risk was recorded, but broker volume is not executable: "
                        f"{simulation_plan['sizing_status']}. No size was rounded up."
                    )

    with tab2:
        trades = get_all_trades()
        if trades:
            df = pd.DataFrame(trades)
            st.dataframe(df, width="stretch")
            st.divider()
            st.subheader("Close a Trade")
            with st.form("close_trade_form"):
                open_ids = [t["id"] for t in trades if not t.get("outcome")]
                if open_ids:
                    tid = st.selectbox("Trade ID", open_ids)
                    exit_p = st.number_input("Exit Price", format="%.5f")
                    outcome = st.radio("Outcome", ["win", "loss", "breakeven"], horizontal=True)
                    rr = st.number_input("RR Achieved", value=0.0, step=0.1)
                    close_notes = st.text_input("Notes")
                    if st.form_submit_button("Close Trade"):
                        try:
                            close_trade(tid, exit_p, outcome, rr, close_notes)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success(f"Trade #{tid} closed as {outcome}.")
                            st.rerun()
                else:
                    st.info("No open trades to close.")
        else:
            st.info("No trades logged yet.")


# ─────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────
def show_analytics():
    st.header("Performance Analytics")
    trades = get_all_trades()
    if not trades:
        st.info("No trade data yet.")
        return

    df = pd.DataFrame(trades)
    df["opened_at"] = pd.to_datetime(df["opened_at"])

    c1, c2 = st.columns(2)
    with c1:
        if df["outcome"].notna().any():
            oc = df["outcome"].value_counts()
            fig = px.pie(values=oc.values, names=oc.index, title="Win / Loss / Breakeven",
                         color_discrete_map={"win": "#26a69a", "loss": "#ef5350", "breakeven": "#ffd54f"})
            st.plotly_chart(fig, width="stretch")
    with c2:
        if df["outcome"].notna().any() and "grade" in df.columns:
            g_df = df[df["outcome"].notna()].groupby(["grade", "outcome"]).size().reset_index(name="count")
            fig = px.bar(g_df, x="grade", y="count", color="outcome", title="Outcomes by Grade",
                         color_discrete_map={"win": "#26a69a", "loss": "#ef5350", "breakeven": "#ffd54f"})
            st.plotly_chart(fig, width="stretch")

    if df["rr_achieved"].notna().any():
        fig = px.histogram(df[df["rr_achieved"].notna()], x="rr_achieved",
                           title="RR Distribution", nbins=20,
                           color_discrete_sequence=["#2196F3"])
        st.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        if df["outcome"].notna().any():
            sym_df = df[df["outcome"].notna()].groupby(["symbol", "outcome"]).size().reset_index(name="count")
            fig = px.bar(sym_df, x="symbol", y="count", color="outcome", title="By Symbol",
                         color_discrete_map={"win": "#26a69a", "loss": "#ef5350", "breakeven": "#ffd54f"})
            st.plotly_chart(fig, width="stretch")
    with c4:
        if "session" in df.columns and df["outcome"].notna().any():
            ses_df = df[df["outcome"].notna()].groupby(["session", "outcome"]).size().reset_index(name="count")
            fig = px.bar(ses_df, x="session", y="count", color="outcome", title="By Session",
                         color_discrete_map={"win": "#26a69a", "loss": "#ef5350", "breakeven": "#ffd54f"})
            st.plotly_chart(fig, width="stretch")

    # Equity curve from trades
    if df["rr_achieved"].notna().any():
        df_sorted = df[df["rr_achieved"].notna()].sort_values("opened_at")
        df_sorted["cumulative_rr"] = df_sorted["rr_achieved"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_sorted["opened_at"], y=df_sorted["cumulative_rr"],
            fill="tozeroy", name="Cumulative RR",
            line=dict(color="#26a69a"),
        ))
        fig.update_layout(title="Cumulative RR Curve", height=300,
                          margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, width="stretch")


# ─────────────────────────────────────────────
# Daily Review
# ─────────────────────────────────────────────
def show_daily_review():
    st.header("Daily Trading Review")
    st.caption("End-of-day reflection — stored for future AI coaching analysis.")

    trades = get_all_trades()
    closed = [t for t in trades if t.get("outcome")]

    with st.form("daily_review_form"):
        trade_id = None
        if closed:
            options = {f"#{t['id']} — {t['symbol']} {t['direction']} ({t['outcome']})": t["id"]
                       for t in closed[:20]}
            sel = st.selectbox("Link to trade (optional)", ["None"] + list(options.keys()))
            trade_id = options.get(sel)

        followed_plan = st.radio(
            "Did you follow your trading plan?",
            ["Yes — fully", "Yes — mostly", "No — deviated", "No trades today"],
            horizontal=True,
        )
        outcome = st.radio(
            "Overall outcome today?",
            ["Profitable", "Breakeven", "Loss", "No trades"],
            horizontal=True,
        )
        moved_stop = st.radio(
            "Did you move your stop loss?",
            ["No — held discipline", "Yes — to breakeven", "Yes — widened (bad)", "N/A"],
            horizontal=True,
        )
        better_entry = st.radio(
            "Was there a better entry available?",
            ["No — entry was optimal", "Yes — could have waited", "Yes — entered too early", "N/A"],
            horizontal=True,
        )
        emotions = st.multiselect(
            "Emotions during the session:",
            ["Calm & focused", "FOMO", "Revenge trading urge", "Overconfident",
             "Anxious", "Hesitant", "Impatient", "Disciplined", "Frustrated"],
        )
        notes = st.text_area("Lessons learned / notes:", height=120)

        if st.form_submit_button("Submit Review", type="primary"):
            save_journal_entry(trade_id, followed_plan, outcome, moved_stop,
                               better_entry, emotions, notes)
            st.success("Review saved.")
            st.balloons()

    st.divider()
    st.subheader("Past Reviews")
    entries = get_journal_entries()
    if entries:
        st.dataframe(pd.DataFrame(entries), width="stretch")
    else:
        st.info("No reviews yet.")


# ─────────────────────────────────────────────
# Risk Status
# ─────────────────────────────────────────────
def show_risk_status():
    st.header("Risk Management Status")
    render_account_separation()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max Risk / Trade", f"{config.MAX_RISK_PER_TRADE}%")
    c2.metric("Daily DD Limit", f"{config.MAX_DAILY_DRAWDOWN}%")
    c3.metric("Weekly DD Limit", f"{config.MAX_WEEKLY_DRAWDOWN}%")
    c4.metric("Max Consec. Losses", config.MAX_CONSECUTIVE_LOSSES)

    st.divider()
    risk_log = get_risk_log(200)
    if risk_log:
        df = pd.DataFrame(risk_log).sort_values("logged_at")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["logged_at"], y=df["daily_dd"],
                                  name="Daily DD %", line=dict(color="#ef5350")))
        fig.add_trace(go.Scatter(x=df["logged_at"], y=df["weekly_dd"],
                                  name="Weekly DD %", line=dict(color="#ffd54f")))
        fig.add_hline(y=config.MAX_DAILY_DRAWDOWN, line_dash="dash",
                      line_color="#ef5350", annotation_text="Daily Limit")
        fig.add_hline(y=config.MAX_WEEKLY_DRAWDOWN, line_dash="dash",
                      line_color="#ffd54f", annotation_text="Weekly Limit")
        fig.update_layout(title="Drawdown History", height=320,
                          margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, width="stretch")

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["logged_at"], y=df["consecutive_losses"],
                                   fill="tozeroy", name="Consec. Losses",
                                   line=dict(color="#b39ddb")))
        fig2.add_hline(y=config.MAX_CONSECUTIVE_LOSSES, line_dash="dash",
                       line_color="#ef5350", annotation_text="Limit")
        fig2.update_layout(title="Consecutive Loss Tracker", height=240,
                           margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig2, width="stretch")
    else:
        st.info("No risk log data yet.")

    st.divider()
    st.subheader("Constitution Rules")
    rules = [
        f"Max risk per trade: **{config.MAX_RISK_PER_TRADE}%** of balance",
        f"Daily drawdown limit: **{config.MAX_DAILY_DRAWDOWN}%** — alerts suspended if breached",
        f"Weekly drawdown limit: **{config.MAX_WEEKLY_DRAWDOWN}%** — alerts suspended if breached",
        f"Max **{config.MAX_CONSECUTIVE_LOSSES}** consecutive losses before trading is paused",
        "Elite trades: only when score ≥ 12 and daily DD < 50% of limit",
        f"News blackout: **{config.NEWS_BLOCK_MINUTES_BEFORE}m before** / **{config.NEWS_BLOCK_MINUTES_AFTER}m after** HIGH-impact events",
    ]
    for r in rules:
        st.write(f"• {r}")


if __name__ == "__main__":
    main()
