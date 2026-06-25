"""
app.py — Flask backend for the Groww-style frontend.
Run: python app.py
"""
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import pytz
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
# ---------------------------------------------------------------------------

MARKET_DB = os.getenv("MARKET_DB", "data/market_data.db")
OPTION_DB = os.getenv("OPTION_DB", "data/option_chain.db")
IST       = pytz.timezone("Asia/Kolkata")

app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")

# ── NSE helpers ──────────────────────────────────────────────────────────────
_STRIKE_GAP = {"NIFTY50": 50, "BANKNIFTY": 100, "MIDCAPNIFTY": 25, "FINNIFTY": 50}

_DISPLAY_NAME = {
    "NIFTY50":     "NIFTY 50",
    "BANKNIFTY":   "BANK NIFTY",
    "FINNIFTY":    "FIN NIFTY",
    "MIDCAPNIFTY": "MIDCAP NIFTY",
}

_DB_TABLE = {
    "NIFTY50":     "nifty50_option_chain",
    "BANKNIFTY":   "banknifty_option_chain",
    "FINNIFTY":    "finnifty_option_chain",
    "MIDCAPNIFTY": "midcapnifty_option_chain",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return round(float(v), 2)


def _next_thursday(ref: date) -> date:
    days = (3 - ref.weekday()) % 7
    return ref + timedelta(days=days)


def _get_expiries_for_symbol(symbol: str) -> list:
    """Return expiry date list using nselib, capped at 25-Aug-2026."""
    from src.option_chain.nse_scraper import get_expiry_dates
    from datetime import datetime
    cutoff = datetime(2026, 8, 25)
    expiries = get_expiry_dates(symbol)
    return [
        e for e in expiries
        if datetime.strptime(e, "%d-%b-%Y") <= cutoff
    ]


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/symbols")
def api_symbols():
    """Return all available symbols from the market DB."""
    try:
        with sqlite3.connect(MARKET_DB) as conn:
            rows = conn.execute(
                "SELECT DISTINCT stock_name FROM indexes ORDER BY stock_name"
            ).fetchall()
        return jsonify([r[0] for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/expiries")
def api_expiries():
    """Return available expiry dates for a symbol from NSE."""
    symbol = request.args.get("symbol", "NIFTY50")
    expiries = _get_expiries_for_symbol(symbol)
    return jsonify(expiries)


@app.route("/api/option-chain")
def api_option_chain():
    """
    Fetch live option chain from NSE.
    Query params: symbol, expiry
    """
    symbol = request.args.get("symbol", "NIFTY50")
    expiry = request.args.get("expiry", "")

    # ── get spot from market DB ───────────────────────────────────────────────
    spot = 0.0
    try:
        with sqlite3.connect(MARKET_DB) as conn:
            row = conn.execute(
                "SELECT close FROM indexes WHERE stock_name=? ORDER BY datetime DESC LIMIT 1",
                (symbol,)
            ).fetchone()
            if row:
                spot = float(row[0])
    except Exception:
        pass

    if not expiry:
        expiries = _get_expiries_for_symbol(symbol)
        expiry   = expiries[0] if expiries else ""

    # ── fetch live from NSE ───────────────────────────────────────────────────
    from src.option_chain.nse_scraper import fetch_option_chain
    from src.database import insert_option_data
    try:
        df = fetch_option_chain(symbol, expiry, spot)
    except Exception as e:
        return jsonify({"error": f"Option chain fetch failed: {e}"}), 502

    if df.empty:
        return jsonify({"error": "No option chain data available for this expiry"}), 404

    # ── store into DB ─────────────────────────────────────────────────────────
    try:
        now_ist = datetime.now(IST)
        df_store = df.copy()
        df_store["symbol"]   = _DISPLAY_NAME.get(symbol, symbol)
        df_store["datetime"] = now_ist.strftime("%Y-%m-%d %H:%M")
        insert_option_data(OPTION_DB, df_store)
    except Exception:
        pass  # don't fail the response if storage fails

    gap = _STRIKE_GAP.get(symbol, 50)
    atm = round(spot / gap) * gap if spot else 0

    # ── build response ────────────────────────────────────────────────────────
    chain = {}
    for _, r in df.iterrows():
        s = float(r["strike"])
        if s not in chain:
            chain[s] = {"strike": s, "CE": {}, "PE": {}}
        otype = str(r["option_type"]).upper()
        chain[s][otype] = {
            "oi":     _fmt(r.get("oi")),
            "oiChg":  _fmt(r.get("oi_chg")),
            "volume": _fmt(r.get("volume")),
            "iv":     _fmt(r.get("iv")),
            "ltp":    _fmt(r.get("ltp")),
            "open":   _fmt(r.get("open")),
            "high":   _fmt(r.get("high")),
            "low":    _fmt(r.get("low")),
            "close":  _fmt(r.get("close")),
            "delta":  _fmt(r.get("delta")),
            "gamma":  _fmt(r.get("gamma")),
            "theta":  _fmt(r.get("theta")),
            "vega":   _fmt(r.get("vega")),
            "rho":    _fmt(r.get("rho")),
        }

    rows = sorted(chain.values(), key=lambda x: x["strike"])
    return jsonify({"spot": spot, "atm": atm, "rows": rows, "symbol": _DISPLAY_NAME.get(symbol, symbol), "expiry": expiry})


@app.route("/api/market-summary")
def api_market_summary():
    """Return latest candle for all symbols from market DB."""
    try:
        with sqlite3.connect(MARKET_DB) as conn:
            df = pd.read_sql_query(
                """
                SELECT i.*
                FROM indexes i
                INNER JOIN (
                    SELECT stock_name, MAX(datetime) AS max_dt
                    FROM indexes GROUP BY stock_name
                ) latest ON i.stock_name = latest.stock_name AND i.datetime = latest.max_dt
                """,
                conn,
            )
        result = []
        for _, row in df.iterrows():
            result.append({
                "symbol":   row["stock_name"],
                "datetime": row["datetime"],
                "open":     _fmt(row["open"]),
                "high":     _fmt(row["high"]),
                "low":      _fmt(row["low"]),
                "close":    _fmt(row["close"]),
                "volume":   _fmt(row["volume"]),
                "rsi_14":   _fmt(row["rsi_14"]),
                "ema_20":   _fmt(row["ema_20"]),
                "macd":     _fmt(row["macd"]),
                "atr":      _fmt(row["atr"]),
                "adx":      _fmt(row["adx"]),
                "signal":   row["signal"],
                "chg_pct":  _fmt(row["price_change_pct"]),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history")
def api_history():
    """
    Return OHLCV history for a symbol with optional date + interval filter.
    Query params: symbol, date (YYYY-MM-DD), interval (1 or 5 or 15 mins)
    """
    symbol   = request.args.get("symbol", "NIFTY50")
    filt_date = request.args.get("date", "")       # e.g. 2026-06-13
    interval = int(request.args.get("interval", 1))  # 1, 5, or 15

    try:
        with sqlite3.connect(MARKET_DB) as conn:
            if filt_date:
                df = pd.read_sql_query(
                    "SELECT * FROM indexes WHERE stock_name=? AND datetime LIKE ? ORDER BY datetime ASC",
                    conn, params=(symbol, f"{filt_date}%"),
                )
            else:
                df = pd.read_sql_query(
                    "SELECT * FROM indexes WHERE stock_name=? ORDER BY datetime ASC",
                    conn, params=(symbol,),
                )

        if df.empty:
            return jsonify([])

        df["datetime"] = pd.to_datetime(df["datetime"])

        # Resample if interval > 1
        if interval > 1:
            df = df.set_index("datetime")
            ohlcv = df[["open", "high", "low", "close", "volume"]].resample(f"{interval}min").agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna(subset=["close"]).reset_index()
            # Grab latest signal per bucket
            sig = df[["signal"]].resample(f"{interval}min").last().reset_index()
            ohlcv["signal"] = sig["signal"].values
            df = ohlcv

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "datetime": str(row["datetime"])[:16],
                "open":     _fmt(row.get("open")),
                "high":     _fmt(row.get("high")),
                "low":      _fmt(row.get("low")),
                "close":    _fmt(row.get("close")),
                "volume":   _fmt(row.get("volume")),
                "signal":   row.get("signal", "HOLD"),
            })
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dates")
def api_dates():
    """Return all distinct dates available in the DB for a symbol."""
    symbol = request.args.get("symbol", "NIFTY50")
    try:
        with sqlite3.connect(MARKET_DB) as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(datetime,1,10) AS d FROM indexes WHERE stock_name=? ORDER BY d DESC",
                (symbol,),
            ).fetchall()
        return jsonify([r[0] for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
