"""
status.py — Live bot status snapshot.
Run: python status.py

Shows: service state, instrument, mode, regime, ORB state,
open position (with current premium & P&L), and session summary.
Read-only — never modifies anything.
"""

import os
import sys
import sqlite3
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET  = ZoneInfo("US/Eastern")
UTC = timezone.utc

INSTALL_DIR  = os.path.expanduser("~/options-trader")
sys.path.insert(0, INSTALL_DIR)

try:
    from config import (
        DB_PATH, INSTRUMENT, PAPER_TRADING,
        SESSION_LOSS_LIMIT, BOT_NAME
    )
    SERVICE_NAME = "optionsbot"
except Exception:
    DB_PATH       = os.path.join(INSTALL_DIR, "trades.db")
    INSTRUMENT    = os.environ.get("OT_INSTRUMENT", "???")
    PAPER_TRADING = os.environ.get("OT_PAPER_TRADING", "True") != "False"
    SESSION_LOSS_LIMIT = 2
    BOT_NAME      = "OptionsTrader"
    SERVICE_NAME  = "optionsbot"


# ── Formatting helpers ────────────────────────────────────────

def now_et():
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")

def to_et(ts):
    if not ts:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        return ts[:16]

def sep(char="─", w=54):
    print(char * w)

def pct(val):
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1%}"

def usd(val):
    sign = "+" if val >= 0 else ""
    return f"{sign}${abs(val):,.2f}" if val < 0 else f"+${val:,.2f}"


# ── Data fetchers ─────────────────────────────────────────────

def check_service():
    try:
        r = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True
        )
        active = r.stdout.strip() == "active"
        return active, r.stdout.strip()
    except Exception:
        return False, "unknown"


def get_regime_and_orb():
    """Scrape the most recent regime and ORB state from bot.log."""
    log_path = os.path.join(INSTALL_DIR, "bot.log")
    regime = "UNKNOWN"
    strategy = "UNKNOWN"
    orb_state = "UNKNOWN"

    if not os.path.exists(log_path):
        return regime, strategy, orb_state

    try:
        # Read last 500 lines — recent enough, cheap enough
        result = subprocess.run(
            ["tail", "-500", log_path],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().split("\n")

        for line in reversed(lines):
            if "REGIME:" in line and regime == "UNKNOWN":
                # Format: "REGIME: TRENDING_BULL conviction=..."
                parts = line.split("REGIME:")
                if len(parts) > 1:
                    regime = parts[1].strip().split()[0]

            if "STRATEGY TRANSITION:" in line and strategy == "UNKNOWN":
                parts = line.split("→")
                if len(parts) > 1:
                    strategy = parts[1].strip().split()[0].rstrip(")")

            if "ORB:" in line and orb_state == "UNKNOWN":
                # Format: "ORB CONFIRMED LONG" / "ORB BREAK LONG" / "ORB range set" etc
                if "CONFIRMED LONG"  in line: orb_state = "CONFIRMED LONG"
                elif "CONFIRMED SHORT" in line: orb_state = "CONFIRMED SHORT"
                elif "BREAK LONG"    in line: orb_state = "BREAK → watching for retest"
                elif "BREAK SHORT"   in line: orb_state = "BREAK → watching for retest"
                elif "range set"     in line: orb_state = "Range set — watching for break"
                elif "INVALIDATED"   in line: orb_state = "Invalidated"
                elif "TRIGGERED"     in line: orb_state = "Triggered (signal fired)"
                elif "EXPIRED"       in line: orb_state = "Expired (past 2PM)"
                elif "reset"         in line: orb_state = "Waiting for 9:35 ET"

            if regime != "UNKNOWN" and strategy != "UNKNOWN" and orb_state != "UNKNOWN":
                break

    except Exception:
        pass

    return regime, strategy, orb_state


def get_open_trade():
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trades WHERE status='open' ORDER BY entry_time DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_session_summary():
    if not os.path.exists(DB_PATH):
        return None
    today = datetime.now(ET).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(pnl_usd), 0)                     as net_pnl,
                COALESCE(MAX(pnl_usd), 0)                     as best,
                COALESCE(MIN(pnl_usd), 0)                     as worst
            FROM trades
            WHERE status='closed' AND date(entry_time) = ?
        """, (today,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# ── Main display ──────────────────────────────────────────────

def main():
    print()
    sep("═")
    mode_label = "PAPER" if PAPER_TRADING else "LIVE"
    print(f"  {BOT_NAME} — STATUS")
    print(f"  {now_et()}")
    sep("═")
    print()

    # ── Service & mode ────────────────────────────────────────
    running, svc_status = check_service()
    svc_icon = "🟢" if running else "🔴"
    print(f"  {svc_icon} Service:      {svc_status.upper()}")
    print(f"  📍 Instrument:  {INSTRUMENT}")
    mode_icon = "📄" if PAPER_TRADING else "🔴"
    print(f"  {mode_icon} Mode:         {mode_label}")
    print()
    sep()

    # ── Regime & ORB ─────────────────────────────────────────
    regime, strategy, orb_state = get_regime_and_orb()
    print(f"  📊 Regime:      {regime}")
    print(f"  🎯 Strategy:    {strategy}")
    print(f"  ⏱  ORB state:   {orb_state}")
    print()
    sep()

    # ── Open position ─────────────────────────────────────────
    trade = get_open_trade()
    if trade:
        is_butterfly = bool(trade.get("is_butterfly", 0))
        entry_prem   = trade.get("entry_premium", 0) or 0
        stop_prem    = trade.get("stop_premium",  0) or 0
        target_prem  = trade.get("target_premium", 0) or 0
        trail_prem   = trade.get("trail_activation", 0) or 0
        contracts    = trade.get("contracts", 0) or 0
        total_cost   = trade.get("total_cost", 0) or 0
        direction    = trade.get("direction", "").upper()
        strategy_name = trade.get("strategy", "")
        grade        = trade.get("setup_grade", "?")
        option_side  = trade.get("option_side", "").upper()
        strike       = trade.get("strike", 0) or 0
        expiry       = trade.get("expiry", "")

        # Current premium from DB stop (updated by position manager)
        # For display we show entry vs current stop as proxy
        # Real current premium requires live API — show what we have
        current_prem  = entry_prem   # best available without live call
        pnl_pct_entry = 0.0
        pnl_usd       = 0.0

        pnl_icon = "📈" if pnl_usd >= 0 else "📉"

        if is_butterfly:
            net_debit  = trade.get("net_debit", 0) or 0
            max_profit = trade.get("max_profit", 0) or 0
            lower_s    = trade.get("lower_strike", 0) or 0
            center_s   = trade.get("center_strike", 0) or 0
            upper_s    = trade.get("upper_strike", 0) or 0
            print(f"  🦋 OPEN BUTTERFLY — {option_side}")
            print(f"     Strikes:    {lower_s:.0f} / {center_s:.0f} / {upper_s:.0f}")
            print(f"     Net debit:  ${net_debit:.2f}/share")
            print(f"     Max profit: ${max_profit:.2f}/share  (TP @ 25%: ${max_profit*0.25:.2f})")
            print(f"     Contracts:  {contracts}")
            print(f"     Total cost: ${total_cost:.2f}")
            print(f"     Stop:       < ${stop_prem:.2f}/share  (25% loss)")
        else:
            print(f"  {pnl_icon} OPEN {direction}  —  {option_side} {strike:.0f}")
            print(f"     Expiry:     {expiry}")
            print(f"     Entry:      ${entry_prem:.2f}/share")
            print(f"     Stop:       ${stop_prem:.2f}/share  (25% loss)")
            print(f"     Trail at:   ${trail_prem:.2f}/share  (50% TP)")
            print(f"     Target:     ${target_prem:.2f}/share  (100% TP)")
            print(f"     Contracts:  {contracts}  ×  $100  =  ${total_cost:.2f} at risk")

        print(f"     Grade:      {grade}  |  {strategy_name}")
        print(f"     Entered:    {to_et(trade.get('entry_time', ''))}")
        print(f"     Regime:     {trade.get('regime', '')}")
    else:
        print("  ⏳ No open position")

    print()
    sep()

    # ── Session summary ───────────────────────────────────────
    s = get_session_summary()
    today_label = datetime.now(ET).strftime("%Y-%m-%d")
    print(f"  TODAY'S SESSION  ({today_label} ET)")
    print()
    if s and s["total"] > 0:
        wins   = s["wins"]   or 0
        losses = s["losses"] or 0
        total  = s["total"]  or 0
        pnl    = s["net_pnl"] or 0
        best   = s["best"]   or 0
        worst  = s["worst"]  or 0
        wr     = wins / total * 100 if total else 0

        cb_warning = ""
        if losses >= SESSION_LOSS_LIMIT:
            cb_warning = "  ⚠  CIRCUIT BREAKER FIRED"

        print(f"  Trades:       {total}  ({wins}W / {losses}L)")
        print(f"  Win rate:     {wr:.0f}%")
        print(f"  Net P&L:      {usd(pnl)}")
        print(f"  Best trade:   {usd(best)}")
        print(f"  Worst trade:  {usd(worst)}")
        if cb_warning:
            print()
            print(f"  {cb_warning}")
    else:
        print("  No closed trades yet today.")

    print()
    sep("═")
    print()


if __name__ == "__main__":
    main()
