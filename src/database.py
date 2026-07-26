"""database.py — SQLite helpers for option_chain.db."""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_OC_TABLES = {
    "NIFTY50":     "nifty50_option_chain",
    "BANKNIFTY":   "banknifty_option_chain",
    "MIDCAPNIFTY": "midcapnifty_option_chain",
    "FINNIFTY":    "finnifty_option_chain",
    "SENSEX":      "sensex_option_chain",
}

_INDEX_LABEL = {
    "NIFTY50":     "Nifty50",
    "BANKNIFTY":   "BankNifty",
    "MIDCAPNIFTY": "MidcapNifty",
    "FINNIFTY":    "FinNifty",
    "SENSEX":      "Sensex",
}

_OC_COLS = [
    "index_name", "timestamp", "option_type", "expiry",
    "strike", "spot", "ltp", "open", "high", "low", "close",
    "volume", "oi", "oi_chg", "iv",
    "delta", "gamma", "theta", "vega", "rho",
]

_OC_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    index_name   TEXT,
    timestamp    TEXT,
    option_type  TEXT,
    expiry       TEXT,
    strike       REAL,
    spot         REAL,
    ltp          REAL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,
    oi           REAL,
    oi_chg       REAL,
    iv           REAL,
    delta        REAL,
    gamma        REAL,
    theta        REAL,
    vega         REAL,
    rho          REAL,
    PRIMARY KEY (timestamp, option_type, expiry, strike)
)
"""

_MARKET_OPEN  = 915
_MARKET_CLOSE = 1530


def init_db(option_db: str) -> None:
    """Create all option chain tables if they don't exist."""
    with sqlite3.connect(option_db) as conn:
        for table in _OC_TABLES.values():
            conn.execute(_OC_DDL.format(table=table))
        conn.commit()
    logger.info("Option chain DB initialised: %s", option_db)


def _update_ohlc(conn: sqlite3.Connection, table: str, today: str) -> None:
    """
    Recompute OHLC for ALL rows of today.
    - open  = first ltp of the day for this contract
    - high  = max ltp up to and including this row's timestamp
    - low   = min ltp (>0) up to and including this row's timestamp
    - close = this row's own ltp
    """
    conn.execute(f"""
        UPDATE {table}
        SET
            close = ltp,
            open  = (
                SELECT s.ltp FROM {table} s
                WHERE s.option_type = {table}.option_type
                  AND s.expiry      = {table}.expiry
                  AND s.strike      = {table}.strike
                  AND substr(s.timestamp,1,8) = ?
                ORDER BY s.timestamp ASC LIMIT 1
            ),
            high  = (
                SELECT MAX(s.ltp) FROM {table} s
                WHERE s.option_type = {table}.option_type
                  AND s.expiry      = {table}.expiry
                  AND s.strike      = {table}.strike
                  AND substr(s.timestamp,1,8) = ?
                  AND s.timestamp  <= {table}.timestamp
            ),
            low   = (
                SELECT MIN(s.ltp) FROM {table} s
                WHERE s.option_type = {table}.option_type
                  AND s.expiry      = {table}.expiry
                  AND s.strike      = {table}.strike
                  AND substr(s.timestamp,1,8) = ?
                  AND s.timestamp  <= {table}.timestamp
                  AND s.ltp > 0
            )
        WHERE substr(timestamp,1,8) = ?
    """, (today, today, today, today))
    logger.debug("[%s] OHLC recomputed for %s", table, today)


def _calc_greeks(flag: str, S: float, K: float, t: float, iv_dec: float) -> dict:
    """Wrapper around greeks.compute_greeks — single source of truth."""
    try:
        from src.option_chain.greeks import compute_greeks
        otype = "CE" if flag == "c" else "PE"
        g = compute_greeks(S, K, t, 0.065, iv_dec, otype)
        return {
            "delta": round(g["delta"], 4)  if g["delta"] is not None else None,
            "gamma": round(g["gamma"], 6)  if g["gamma"] is not None else None,
            "theta": round(g["theta"], 4)  if g["theta"] is not None else None,
            "vega":  round(g["vega"],  4)  if g["vega"]  is not None else None,
            "rho":   round(g["rho"],   4)  if g["rho"]   is not None else None,
        }
    except Exception:
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}


def _bisect_iv(flag: str, spot: float, strike: float, tte: float, price: float,
               lo: float = 0.001, hi: float = 20.0, tol: float = 0.01) -> Optional[float]:
    """Bisection IV solver — works for deep ITM where vollib Newton method fails."""
    import math
    from scipy.stats import norm
    _r = 0.065

    def bs_price(iv):
        try:
            d1 = (math.log(spot / strike) + (_r + 0.5 * iv * iv) * tte) / (iv * math.sqrt(tte))
            d2 = d1 - iv * math.sqrt(tte)
            if flag == 'c':
                return spot * norm.cdf(d1) - strike * math.exp(-_r * tte) * norm.cdf(d2)
            else:
                return strike * math.exp(-_r * tte) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        except Exception:
            return None

    try:
        for _ in range(50):
            mid = (lo + hi) / 2
            p   = bs_price(mid)
            if p is None:
                return None
            if abs(p - price) < tol:
                return round(mid, 4)
            if p < price:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2, 4)
    except Exception:
        return None


def _update_greeks(conn: sqlite3.Connection, table: str, today: str) -> None:
    """
    Backfill NULL Greeks for rows on `today` AND yesterday (YYYYMMDD).
    - Uses stored IV if valid (> 1.0% to exclude NSE's fake 0.1 floor)
    - Falls back to vollib Newton solver, then bisection
    - Uses greeks.compute_greeks (scipy) — no vollib dependency for Greeks
    """
    from datetime import date as _date, timedelta as _td

    # Also cover yesterday in case a run spanned midnight
    yesterday = (datetime.strptime(today, "%Y%m%d").date() - _td(days=1)).strftime("%Y%m%d")
    dates_to_fix = [today, yesterday]

    for day in dates_to_fix:
        rows = conn.execute(f"""
            SELECT timestamp, option_type, expiry, strike, spot, ltp, iv
            FROM {table}
            WHERE substr(timestamp,1,8) = ?
              AND delta  IS NULL
              AND spot   IS NOT NULL AND spot   > 0
              AND strike IS NOT NULL AND strike > 0
              AND ltp    IS NOT NULL AND ltp    > 0
        """, (day,)).fetchall()

        if not rows:
            continue

        updated = 0
        skipped = 0
        for ts, otype, expiry, strike, spot, ltp, iv_pct in rows:
            try:
                exp_date = datetime.strptime(expiry, "%d-%b-%Y").date()
                tte = max((exp_date - _date.today()).days, 0.5) / 365.0
            except Exception:
                skipped += 1
                continue

            flag = "c" if otype == "CE" else "p"

            # 1. Use stored IV only if meaningful (> 1% — excludes NSE's 0.1 floor value)
            if iv_pct and iv_pct > 1.0:
                iv_dec = iv_pct / 100.0
            else:
                # 2. Vollib Newton solver (fast, accurate for near-ATM)
                iv_dec = None
                try:
                    from vollib.black_scholes.implied_volatility import implied_volatility as iv_fn
                    iv_raw = iv_fn(ltp, spot, strike, tte, 0.065, flag)
                    if iv_raw and 0.01 < iv_raw < 20:
                        iv_dec = round(iv_raw, 4)
                except Exception:
                    pass
                # 3. Bisection fallback — pure math, no external dependency
                if not iv_dec:
                    iv_dec = _bisect_iv(flag, spot, strike, tte, ltp)

            if not iv_dec:
                skipped += 1
                continue

            g = _calc_greeks(flag, spot, strike, tte, iv_dec)
            if g["delta"] is None:
                skipped += 1
                continue

            conn.execute(f"""
                UPDATE {table}
                SET delta=?, gamma=?, theta=?, vega=?, rho=?,
                    iv=COALESCE(NULLIF(iv, 0), ?)
                WHERE timestamp=? AND option_type=? AND expiry=? AND strike=?
            """, (
                g["delta"], g["gamma"], g["theta"], g["vega"], g["rho"],
                round(iv_dec * 100, 2),
                ts, otype, expiry, strike
            ))
            updated += 1

        if updated or skipped:
            logger.info("[%s] Greeks backfill %s: updated=%d skipped=%d",
                        table, day, updated, skipped)


def backfill_greeks_for_date(db: str, date_str: str) -> None:
    """
    Backfill NULL Greeks for ALL tables for a given date (YYYYMMDD).
    Call this manually to fix historical rows.
    """
    with sqlite3.connect(db) as conn:
        for symbol, table in _OC_TABLES.items():
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE substr(timestamp,1,8)=? AND delta IS NULL",
                (date_str,)
            ).fetchone()[0]
            if count == 0:
                logger.info("[%s] No NULL Greeks on %s — skipping", symbol, date_str)
                continue
            logger.info("[%s] Backfilling %d NULL-greek rows for %s", symbol, count, date_str)
            _update_greeks(conn, table, date_str)
        conn.commit()


def insert_option_data(db: str, symbol: str, df: pd.DataFrame, spot: float = 0.0, trade_date: Optional[str] = None) -> None:
    """Insert option chain snapshot and recompute intraday OHLC."""
    table = _OC_TABLES.get(symbol)
    if not table:
        logger.warning("No option chain table for symbol: %s", symbol)
        return

    if not spot or spot <= 0:
        logger.warning("[%s] spot=0 or missing — skipping insert to avoid bad data", symbol)
        return

    now = datetime.now(IST)
    if now.weekday() >= 5:
        logger.info("Weekend — skipping option chain insert for %s", symbol)
        return
    hm = now.hour * 100 + now.minute
    if not (_MARKET_OPEN <= hm <= _MARKET_CLOSE):
        logger.info("Outside market hours (%02d:%02d IST) skipping", now.hour, now.minute)
        return

    ts    = now.strftime("%Y%m%d%H%M")
    today = now.strftime("%Y%m%d")

    df = df.copy()
    df["index_name"] = _INDEX_LABEL.get(symbol, symbol)
    df["timestamp"]  = ts
    df["spot"]       = spot

    for col in _OC_COLS:
        if col not in df.columns:
            df[col] = None

    sql = (
        f"INSERT OR IGNORE INTO {table} ({', '.join(_OC_COLS)}) "
        f"VALUES ({', '.join(['?'] * len(_OC_COLS))})"
    )
    with sqlite3.connect(db) as conn:
        before = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE timestamp=?", (ts,)).fetchone()[0]
        conn.executemany(sql, df[_OC_COLS].values.tolist())
        after  = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE timestamp=?", (ts,)).fetchone()[0]
        _update_ohlc(conn, table, today)
        _update_greeks(conn, table, today)
        conn.commit()
    inserted = after - before
    logger.info("[%s] ts=%s inserted=%d duplicates=%d | OHLC updated",
                symbol, ts, inserted, len(df) - inserted)


def prune_old_option_data(db: str, keep_days: int = 14) -> None:
    """Delete option chain rows older than keep_days."""
    cutoff = (datetime.now(IST) - timedelta(days=keep_days)).strftime("%Y%m%d%H%M")
    with sqlite3.connect(db) as conn:
        for table in _OC_TABLES.values():
            conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        conn.commit()
    logger.info("Pruned option chain rows older than %d days", keep_days)
