"""database.py — SQLite helpers for market_data.db and option_chain.db."""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Market data ───────────────────────────────────────────────────────────────
_MARKET_COLS = [
    "datetime", "stock_name",
    "open", "high", "low", "close", "volume",
    "sma_5", "sma_10", "sma_20", "sma_50", "sma_100", "sma_200",
    "ema_5", "ema_10", "ema_20", "ema_50", "ema_100", "ema_200",
    "wma_10", "wma_20",
    "macd", "macd_signal", "macd_diff",
    "adx", "adx_pos", "adx_neg",
    "aroon_up", "aroon_down", "aroon_indicator",
    "cci", "dpo", "mass_index",
    "ichimoku_a", "ichimoku_b", "ichimoku_base", "ichimoku_conv",
    "psar", "stc", "trix",
    "vortex_pos", "vortex_neg",
    "kc_upper", "kc_middle", "kc_lower",
    "dc_upper", "dc_middle", "dc_lower",
    "atr",
    "bb_upper", "bb_middle", "bb_lower", "bb_pband", "bb_wband",
    "ulcer_index",
    "rsi_7", "rsi_14", "rsi_21",
    "stoch_k", "stoch_d",
    "roc", "williams_r",
    "awesome_oscillator", "kama",
    "ppo", "tsi", "ultimate_oscillator",
    "obv", "cmf", "acc_dist", "mfi",
    "force_index", "eom", "vpt", "nvi", "vwap",
    "price_change_pct",
    "signal", "updated_at",
]

_MARKET_DDL = """
CREATE TABLE IF NOT EXISTS indexes (
    datetime TEXT, stock_name TEXT,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    sma_5 REAL, sma_10 REAL, sma_20 REAL, sma_50 REAL, sma_100 REAL, sma_200 REAL,
    ema_5 REAL, ema_10 REAL, ema_20 REAL, ema_50 REAL, ema_100 REAL, ema_200 REAL,
    wma_10 REAL, wma_20 REAL,
    macd REAL, macd_signal REAL, macd_diff REAL,
    adx REAL, adx_pos REAL, adx_neg REAL,
    aroon_up REAL, aroon_down REAL, aroon_indicator REAL,
    cci REAL, dpo REAL, mass_index REAL,
    ichimoku_a REAL, ichimoku_b REAL, ichimoku_base REAL, ichimoku_conv REAL,
    psar REAL, stc REAL, trix REAL,
    vortex_pos REAL, vortex_neg REAL,
    kc_upper REAL, kc_middle REAL, kc_lower REAL,
    dc_upper REAL, dc_middle REAL, dc_lower REAL,
    atr REAL,
    bb_upper REAL, bb_middle REAL, bb_lower REAL, bb_pband REAL, bb_wband REAL,
    ulcer_index REAL,
    rsi_7 REAL, rsi_14 REAL, rsi_21 REAL,
    stoch_k REAL, stoch_d REAL,
    roc REAL, williams_r REAL,
    awesome_oscillator REAL, kama REAL,
    ppo REAL, tsi REAL, ultimate_oscillator REAL,
    obv REAL, cmf REAL, acc_dist REAL, mfi REAL,
    force_index REAL, eom REAL, vpt REAL, nvi REAL, vwap REAL,
    price_change_pct REAL,
    signal TEXT, updated_at TEXT,
    PRIMARY KEY (datetime, stock_name)
)
"""

# ── Option chain: 4 tables, one per index ─────────────────────────────────────
# Column order as requested:
#   index_name | timestamp(yyyyMMddHHmm) | option_type | expiry |
#   strike | spot | ltp | open | high | low | close |
#   volume | oi | oi_chg | iv | delta | gamma | theta | vega | rho

_OC_TABLES = {
    "NIFTY50":     "nifty50_option_chain",
    "BANKNIFTY":   "banknifty_option_chain",
    "MIDCAPNIFTY": "midcapnifty_option_chain",
    "FINNIFTY":    "finnifty_option_chain",
}

_INDEX_LABEL = {
    "NIFTY50":     "Nifty50",
    "BANKNIFTY":   "BankNifty",
    "MIDCAPNIFTY": "MidcapNifty",
    "FINNIFTY":    "FinNifty",
}

_OC_COLS = [
    "index_name",   # Nifty50 / BankNifty / MidcapNifty / FinNifty
    "timestamp",    # yyyyMMddHHmm  e.g. 202606241415
    "option_type",  # CE or PE
    "expiry",       # 30-Jun-2026
    "strike",       # 24000.0
    "spot",         # underlying spot price
    "ltp",          # last traded price
    "open",
    "high",
    "low",
    "close",
    "volume",
    "oi",           # open interest
    "oi_chg",       # change in OI
    "iv",           # implied volatility %
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
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

# Market hours IST
_MARKET_OPEN  = "09:15"
_MARKET_CLOSE = "15:45"


def init_db(market_db: str, option_db: str) -> None:
    """Create all tables if they don't exist."""
    with sqlite3.connect(market_db) as conn:
        conn.execute(_MARKET_DDL)
        conn.commit()
    with sqlite3.connect(option_db) as conn:
        for table in _OC_TABLES.values():
            conn.execute(_OC_DDL.format(table=table))
        conn.commit()
    logger.info("Databases initialised: %s | %s", market_db, option_db)


def _to_ist_str(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series)
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize(IST)
    else:
        dt = dt.dt.tz_convert(IST)
    return dt.dt.strftime("%Y-%m-%d %H:%M")


def _is_market_hours(df: pd.DataFrame) -> pd.Series:
    """Return boolean mask for Mon-Fri 09:15-15:45 IST rows."""
    dt = pd.to_datetime(df["datetime"])
    return (
        (dt.dt.weekday < 5) &
        (dt.dt.strftime("%H:%M") >= _MARKET_OPEN) &
        (dt.dt.strftime("%H:%M") <= _MARKET_CLOSE)
    )


def insert_data(db: str, symbol: str, df: pd.DataFrame) -> None:
    """
    Compute indicators and store all Mon-Fri 09:15-15:45 candles.
    Uses INSERT OR REPLACE to upsert — re-fetched candles overwrite stale rows.
    """
    from src.indicators import compute_indicators
    from src.signals import generate_signal

    df = compute_indicators(df.copy())
    df["stock_name"] = symbol
    df["datetime"]   = _to_ist_str(df["datetime"])
    df["volume"]     = df["volume"].fillna(0)
    df["updated_at"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    df = df[_is_market_hours(df)].copy()
    if df.empty:
        logger.warning("[%s] No market-hours candles to store", symbol)
        return

    df["signal"] = df.apply(generate_signal, axis=1)

    for col in _MARKET_COLS:
        if col not in df.columns:
            df[col] = None

    sql = (
        f"INSERT OR REPLACE INTO indexes ({', '.join(_MARKET_COLS)}) "
        f"VALUES ({', '.join(['?'] * len(_MARKET_COLS))})"
    )
    with sqlite3.connect(db) as conn:
        conn.executemany(sql, df[_MARKET_COLS].values.tolist())
        conn.commit()
    logger.info("[%s] Stored %d candles", symbol, len(df))


def latest_row(db: str, symbol: str) -> Optional[pd.Series]:
    """Return the most recent row for a symbol (prefers rows with volume > 0)."""
    try:
        with sqlite3.connect(db) as conn:
            df = pd.read_sql_query(
                "SELECT * FROM indexes WHERE stock_name=? ORDER BY datetime DESC LIMIT 10",
                conn, params=(symbol,),
            )
        if df.empty:
            return None
        with_vol = df[df["volume"] > 0]
        return with_vol.iloc[0] if not with_vol.empty else df.iloc[0]
    except Exception:
        logger.exception("latest_row failed for %s", symbol)
        return None


def insert_option_data(db: str, symbol: str, df: pd.DataFrame, spot: float = 0.0, trade_date: Optional[str] = None) -> None:
    """
    Insert option chain snapshot. Run anytime — timestamp logic:

    - During market hours (Mon-Fri 09:15-15:45 IST): uses actual current IST time
      e.g. script runs at 10:32 → timestamp = yyyyMMdd1032
    - Outside market hours: uses last trading weekday at 15:30
      e.g. run on Sunday → timestamp = last_Friday_date + 1530

    INSERT OR IGNORE: same (timestamp, option_type, expiry, strike) never duplicated.
    """
    table = _OC_TABLES.get(symbol)
    if not table:
        logger.warning("No option chain table for symbol: %s", symbol)
        return

    now_ist = datetime.now(IST)
    hhmm    = now_ist.strftime("%H:%M")
    is_mkt  = (now_ist.weekday() < 5) and (_MARKET_OPEN <= hhmm <= _MARKET_CLOSE)

    if is_mkt:
        # Running during market hours — stamp with actual current time
        ts = now_ist.strftime("%Y%m%d%H%M")
    else:
        # Outside market hours — stamp with last trading day at 15:30
        d = now_ist.date()
        if d.weekday() >= 5:
            d -= timedelta(days=d.weekday() - 4)  # roll back to Friday
        ts = d.strftime("%Y%m%d") + "1530"

    label = _INDEX_LABEL.get(symbol, symbol)
    df    = df.copy()
    df["index_name"] = label
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
        conn.executemany(sql, df[_OC_COLS].values.tolist())
        conn.commit()
    logger.info("[%s] Option chain: %d rows at ts=%s into %s", symbol, len(df), ts, table)
