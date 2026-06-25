"""tradingview_client.py — TvDatafeed session and candle fetching with retry."""
import logging
import os
import time
from datetime import datetime

import pandas as pd
import pytz
from tvDatafeed import TvDatafeed, Interval

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_BARS  = 500   # ~1.3 trading days; reduces TradingView load vs old 1875
RETRIES       = 5
RETRY_DELAY   = 5     # seconds between retries
STALE_MINUTES = 10    # warn if latest candle is older than this

_IST = pytz.timezone("Asia/Kolkata")


# ── TradingView Session ────────────────────────────────────────────────────────
def get_tv() -> TvDatafeed:
    """Return an authenticated (or anonymous) TvDatafeed session."""
    username = os.getenv("TV_USERNAME", "").strip()
    password = os.getenv("TV_PASSWORD", "").strip()
    if username and password:
        logger.info("TvDatafeed: using authenticated session for user '%s'", username)
        return TvDatafeed(username, password)
    logger.warning(
        "TvDatafeed: no credentials found — using anonymous session. "
        "Anonymous sessions may return delayed or incomplete data."
    )
    return TvDatafeed()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _check_stale(label: str, latest_ts: pd.Timestamp) -> None:
    """Warn if the latest candle timestamp is older than STALE_MINUTES."""
    try:
        now_ist = datetime.now(_IST).replace(tzinfo=None)
        if hasattr(latest_ts, "tzinfo") and latest_ts.tzinfo is not None:
            latest_ts = latest_ts.astimezone(_IST).replace(tzinfo=None)
        age_minutes = int((now_ist - latest_ts).total_seconds() // 60)
        if age_minutes > STALE_MINUTES:
            logger.warning(
                "[%s] STALE DATA detected. Latest candle is %d minutes old.", label, age_minutes
            )
    except Exception:
        logger.exception("[%s] Stale-data check failed", label)


# ── Fetch Candles ──────────────────────────────────────────────────────────────
def fetch_candles(
    tv: TvDatafeed,
    tv_symbol: str,
    exchange: str,
    label: str,
    n_bars: int = DEFAULT_BARS,
) -> pd.DataFrame:
    """
    Fetch 1-minute OHLCV candles from TradingView with retry.
    Returns DataFrame[datetime, open, high, low, close, volume] or empty DataFrame.
    """
    for attempt in range(1, RETRIES + 1):
        logger.info(
            "[%s] Fetching %d bars from %s:%s (attempt %d/%d)",
            label, n_bars, exchange, tv_symbol, attempt, RETRIES,
        )
        try:
            df = tv.get_hist(tv_symbol, exchange, interval=Interval.in_1_minute, n_bars=n_bars)
            if df is not None and not df.empty:
                df = df.reset_index()[["datetime", "open", "high", "low", "close", "volume"]].dropna()
                latest = df["datetime"].max()
                logger.info(
                    "[%s] Retrieved %d candles | latest=%s",
                    label, len(df), latest,
                )
                _check_stale(label, latest)
                return df
            logger.warning("[%s] TradingView returned empty data (attempt %d/%d)", label, attempt, RETRIES)
        except Exception:
            logger.exception("[%s] Fetch failed on attempt %d/%d", label, attempt, RETRIES)

        if attempt < RETRIES:
            logger.info("[%s] Retrying in %ds...", label, RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    logger.error("[%s] All %d fetch attempts exhausted. Returning empty DataFrame.", label, RETRIES)
    return pd.DataFrame()
