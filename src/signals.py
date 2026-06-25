"""signals.py — BUY / SELL / HOLD signal generation."""
import logging

import pandas as pd

logger = logging.getLogger(__name__)

_REQUIRED = ["close", "ema_20", "rsi_14", "macd", "macd_signal", "adx"]


def generate_signal(row: pd.Series) -> str:
    """
    Return 'BUY', 'SELL', or 'HOLD'.

    BUY  : close > EMA20, RSI > 55, MACD > signal line, ADX > 20
    SELL : close < EMA20, RSI < 45, MACD < signal line, ADX > 20
    """
    try:
        if any(pd.isna(row.get(col)) for col in _REQUIRED):
            return "HOLD"
        if (
            row["close"] > row["ema_20"]
            and row["rsi_14"] > 55
            and row["macd"] > row["macd_signal"]
            and row["adx"] > 20
        ):
            return "BUY"
        if (
            row["close"] < row["ema_20"]
            and row["rsi_14"] < 45
            and row["macd"] < row["macd_signal"]
            and row["adx"] > 20
        ):
            return "SELL"
    except Exception:
        logger.exception("generate_signal failed")
    return "HOLD"
