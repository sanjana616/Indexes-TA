"""fetch_data.py — Fetch OHLCV for indexes (TV + yfinance fallback)."""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytz
import yfinance as yf
from tvDatafeed import TvDatafeed

from src.tradingview_client import fetch_candles

logger = logging.getLogger(__name__)

_IST           = pytz.timezone("Asia/Kolkata")
_MARKET_OPEN   = "09:15"
_MARKET_CLOSE  = "15:45"
_STALE_MINUTES = 10   # discard TV data older than this during market hours


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True if current IST time is Mon-Fri 09:15–15:45."""
    now  = datetime.now(_IST)
    hhmm = now.strftime("%H:%M")
    return now.weekday() < 5 and _MARKET_OPEN <= hhmm <= _MARKET_CLOSE


def _candle_age_minutes(df: pd.DataFrame) -> Optional[int]:
    """
    Return age of the latest candle in minutes using fully tz-aware comparison.
    Returns None if the timestamp cannot be parsed.
    """
    try:
        latest = pd.to_datetime(df["datetime"].max())
        if latest.tzinfo is None:
            latest = latest.tz_localize(_IST)
        else:
            latest = latest.tz_convert(_IST)
        age = (datetime.now(_IST) - latest).total_seconds() / 60
        return int(age)
    except Exception:
        return None


def _tv_candle_is_stale(df: pd.DataFrame, label: str) -> Tuple[bool, int]:
    """
    Check whether TradingView data should be discarded due to staleness.

    Rules:
    - Outside market hours: never stale — returns (False, 0).
    - During market hours: stale if latest candle is older than _STALE_MINUTES.

    Returns (is_stale, age_in_minutes).
    """
    if not _is_market_hours():
        return False, 0

    age = _candle_age_minutes(df)
    if age is None:
        logger.warning("[%s] Could not determine candle age — keeping TV data", label)
        return False, 0

    latest_str = pd.to_datetime(df["datetime"].max()).strftime("%Y-%m-%d %H:%M")
    logger.info("[%s] Latest TV candle = %s IST", label, latest_str)

    if age > _STALE_MINUTES:
        return True, age

    return False, age


# ── yfinance ───────────────────────────────────────────────────────────────────

def _yf_download(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period="5d", interval="1m", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df = df.reset_index()
    df.rename(columns={df.columns[0]: "datetime"}, inplace=True)
    return df[["datetime", "open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def _yf_fallback(label: str, yf_ticker: str, vol_etf: str = "") -> pd.DataFrame:
    try:
        df = _yf_download(yf_ticker)
        if df.empty:
            return pd.DataFrame()
        if vol_etf:
            etf = _yf_download(vol_etf)
            if not etf.empty:
                etf["datetime"] = pd.to_datetime(etf["datetime"]).dt.floor("min")
                df["datetime"]  = pd.to_datetime(df["datetime"]).dt.floor("min")
                merged = df[["datetime"]].merge(
                    etf[["datetime", "volume"]].rename(columns={"volume": "etf_vol"}),
                    on="datetime", how="left",
                )
                df["volume"] = merged["etf_vol"].ffill().fillna(0).astype(int).values
                logger.info("[%s] ETF volume merged from %s", label, vol_etf)
        logger.info("[%s] yfinance fetched %d rows", label, len(df))
        return df
    except Exception:
        logger.exception("[%s] yfinance fallback failed", label)
        return pd.DataFrame()


# ── Fetch index ────────────────────────────────────────────────────────────────

def fetch_index(tv: TvDatafeed, cfg: Dict) -> pd.DataFrame:
    label     = cfg["label"]
    yf_ticker = cfg.get("yf_ticker", "")
    vol_etf   = cfg.get("vol_etf", "")

    df = fetch_candles(tv, cfg["tv_symbol"], cfg["exchange"], label)

    if not df.empty:
        stale, age = _tv_candle_is_stale(df, label)
        if stale:
            logger.warning(
                "[%s] TradingView data is %d minutes old. Falling back to yfinance.",
                label, age,
            )
            df = pd.DataFrame()

    if df.empty:
        if yf_ticker:
            df = _yf_fallback(label, yf_ticker, vol_etf)
        else:
            logger.warning("[%s] No data from any source", label)

    return df


# ── Fetch all ──────────────────────────────────────────────────────────────────

def fetch_all(
    tv: TvDatafeed,
    index_cfgs: List[Dict],
    sleep: float = 0.5,
) -> Dict[str, pd.DataFrame]:
    """Fetch all indexes; returns {label: DataFrame}."""
    results: Dict[str, pd.DataFrame] = {}
    for cfg in index_cfgs:
        results[cfg["label"]] = fetch_index(tv, cfg)
        time.sleep(sleep)
    return results
