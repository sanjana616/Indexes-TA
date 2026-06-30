"""fetch_data.py — Fetch OHLCV for indexes (TV + yfinance fallback)."""
import logging
import time
from typing import Dict, List

import pandas as pd
import yfinance as yf
from tvDatafeed import TvDatafeed

from src.tradingview_client import fetch_candles

logger = logging.getLogger(__name__)


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


def fetch_index(tv: TvDatafeed, cfg: Dict) -> pd.DataFrame:
    label = cfg["label"]

    df = fetch_candles(tv, cfg["tv_symbol"], cfg["exchange"], label)

    if not df.empty:
        logger.info("[%s] Latest candle = %s", label, df["datetime"].max())

    if df.empty and cfg.get("yf_ticker"):
        logger.info("[%s] Falling back to yfinance", label)
        df = _yf_fallback(label, cfg["yf_ticker"], cfg.get("vol_etf", ""))

    if df.empty:
        logger.warning("[%s] No data from any source", label)

    return df


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
