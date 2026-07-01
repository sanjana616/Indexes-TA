"""indicators.py — Technical indicators using the `ta` library."""
import logging

import pandas as pd
from ta.trend import (
    SMAIndicator, EMAIndicator, WMAIndicator, MACD, ADXIndicator,
    AroonIndicator, CCIIndicator, DPOIndicator, MassIndex,
    IchimokuIndicator, PSARIndicator, STCIndicator, TRIXIndicator,
    VortexIndicator,
)
from ta.volatility import (
    AverageTrueRange, BollingerBands, UlcerIndex, KeltnerChannel, DonchianChannel,
)
from ta.momentum import (
    RSIIndicator, StochasticOscillator, ROCIndicator, WilliamsRIndicator,
    AwesomeOscillatorIndicator, KAMAIndicator, PercentagePriceOscillator,
    TSIIndicator, UltimateOscillator,
)
from ta.volume import (
    OnBalanceVolumeIndicator, ChaikinMoneyFlowIndicator, AccDistIndexIndicator,
    MFIIndicator, ForceIndexIndicator, EaseOfMovementIndicator,
    VolumePriceTrendIndicator, NegativeVolumeIndexIndicator,
    VolumeWeightedAveragePrice,
)

logger = logging.getLogger(__name__)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def compute_rsi(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    df["rsi_7"]  = _safe(lambda: RSIIndicator(c, 7).rsi())
    df["rsi_14"] = _safe(lambda: RSIIndicator(c, 14).rsi())
    df["rsi_21"] = _safe(lambda: RSIIndicator(c, 21).rsi())
    return df


def compute_ema(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    for p in (5, 10, 20, 50, 100, 200):
        df[f"sma_{p}"] = _safe(lambda p=p: SMAIndicator(c, p).sma_indicator())
        df[f"ema_{p}"] = _safe(lambda p=p: EMAIndicator(c, p).ema_indicator())
    df["wma_10"] = _safe(lambda: WMAIndicator(c, 10).wma())
    df["wma_20"] = _safe(lambda: WMAIndicator(c, 20).wma())
    return df


def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    m = MACD(df["close"])
    df["macd"]        = _safe(lambda: m.macd())
    df["macd_signal"] = _safe(lambda: m.macd_signal())
    df["macd_diff"]   = _safe(lambda: m.macd_diff())
    return df


def compute_atr(df: pd.DataFrame) -> pd.DataFrame:
    df["atr"] = _safe(
        lambda: AverageTrueRange(df["high"], df["low"], df["close"], 14).average_true_range()
    )
    return df


def compute_adx(df: pd.DataFrame) -> pd.DataFrame:
    a = ADXIndicator(df["high"], df["low"], df["close"], 14)
    df["adx"]     = _safe(lambda: a.adx())
    df["adx_pos"] = _safe(lambda: a.adx_pos())
    df["adx_neg"] = _safe(lambda: a.adx_neg())
    return df


def compute_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    bb = BollingerBands(df["close"], 20, 2)
    df["bb_upper"]  = _safe(lambda: bb.bollinger_hband())
    df["bb_middle"] = _safe(lambda: bb.bollinger_mavg())
    df["bb_lower"]  = _safe(lambda: bb.bollinger_lband())
    df["bb_pband"]  = _safe(lambda: bb.bollinger_pband())
    df["bb_wband"]  = _safe(lambda: bb.bollinger_wband())
    return df


def compute_indicators(df: pd.DataFrame, db: str = "", symbol: str = "") -> pd.DataFrame:
    """Compute all indicators and return enriched DataFrame."""
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df = compute_ema(df)
    df = compute_macd(df)
    df = compute_atr(df)
    df = compute_adx(df)
    df = compute_rsi(df)
    df = compute_bollinger(df)

    ar = AroonIndicator(h, l, 25)
    df["aroon_up"]        = _safe(lambda: ar.aroon_up())
    df["aroon_down"]      = _safe(lambda: ar.aroon_down())
    df["aroon_indicator"] = _safe(lambda: ar.aroon_indicator())

    df["cci"]        = _safe(lambda: CCIIndicator(h, l, c, 20).cci())
    df["dpo"]        = _safe(lambda: DPOIndicator(c, 20).dpo())
    df["mass_index"] = _safe(lambda: MassIndex(h, l, 9, 25).mass_index())

    ichi = IchimokuIndicator(h, l, 9, 26, 52)
    df["ichimoku_a"]    = _safe(lambda: ichi.ichimoku_a())
    df["ichimoku_b"]    = _safe(lambda: ichi.ichimoku_b())
    df["ichimoku_base"] = _safe(lambda: ichi.ichimoku_base_line())
    df["ichimoku_conv"] = _safe(lambda: ichi.ichimoku_conversion_line())

    df["psar"] = _safe(lambda: PSARIndicator(h, l, c).psar())
    df["stc"]  = _safe(lambda: STCIndicator(c).stc())
    df["trix"] = _safe(lambda: TRIXIndicator(c, 15).trix())

    vx = VortexIndicator(h, l, c, 14)
    df["vortex_pos"] = _safe(lambda: vx.vortex_indicator_pos())
    df["vortex_neg"] = _safe(lambda: vx.vortex_indicator_neg())

    kc = KeltnerChannel(h, l, c, 20)
    df["kc_upper"]  = _safe(lambda: kc.keltner_channel_hband())
    df["kc_middle"] = _safe(lambda: kc.keltner_channel_mband())
    df["kc_lower"]  = _safe(lambda: kc.keltner_channel_lband())

    dc = DonchianChannel(h, l, c, 20)
    df["dc_upper"]  = _safe(lambda: dc.donchian_channel_hband())
    df["dc_middle"] = _safe(lambda: dc.donchian_channel_mband())
    df["dc_lower"]  = _safe(lambda: dc.donchian_channel_lband())

    df["ulcer_index"] = _safe(lambda: UlcerIndex(c, 14).ulcer_index())

    st = StochasticOscillator(h, l, c, 14, 3)
    df["stoch_k"]            = _safe(lambda: st.stoch())
    df["stoch_d"]            = _safe(lambda: st.stoch_signal())
    df["roc"]                = _safe(lambda: ROCIndicator(c, 12).roc())
    df["williams_r"]         = _safe(lambda: WilliamsRIndicator(h, l, c, 14).williams_r())
    df["awesome_oscillator"] = _safe(lambda: AwesomeOscillatorIndicator(h, l, 5, 34).awesome_oscillator())
    df["kama"]               = _safe(lambda: KAMAIndicator(c, 10, 2, 30).kama())
    df["ppo"]                = _safe(lambda: PercentagePriceOscillator(c, 26, 12, 9).ppo())
    df["tsi"]                = _safe(lambda: TSIIndicator(c, 25, 13).tsi())
    df["ultimate_oscillator"] = _safe(lambda: UltimateOscillator(h, l, c, 7, 14, 28).ultimate_oscillator())

    df["obv"]         = _safe(lambda: OnBalanceVolumeIndicator(c, v).on_balance_volume())
    df["cmf"]         = _safe(lambda: ChaikinMoneyFlowIndicator(h, l, c, v, 20).chaikin_money_flow())
    df["acc_dist"]    = _safe(lambda: AccDistIndexIndicator(h, l, c, v).acc_dist_index())
    df["mfi"]         = _safe(lambda: MFIIndicator(h, l, c, v, 14).money_flow_index())
    df["force_index"] = _safe(lambda: ForceIndexIndicator(c, v, 13).force_index())
    df["eom"]         = _safe(lambda: EaseOfMovementIndicator(h, l, v, 14).ease_of_movement())
    df["vpt"]         = _safe(lambda: VolumePriceTrendIndicator(c, v).volume_price_trend())
    df["nvi"]         = _safe(lambda: NegativeVolumeIndexIndicator(c, v).negative_volume_index())
    df["vwap"]        = _safe(lambda: VolumeWeightedAveragePrice(h, l, c, v).volume_weighted_average_price())

    df["price_change_pct"] = _safe(lambda: c.pct_change() * 100)

    df = compute_pivots(df, db=db, symbol=symbol)

    return df


def _prev_day_ohlc_from_db(db: str, symbol: str, before_date: str):
    """
    Query the DB for the most recent trading day's H/L/C strictly before before_date.
    Returns (high, low, close) or None if not found.
    """
    if not db or not symbol:
        return None
    try:
        import sqlite3
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                """
                SELECT MAX(high), MIN(low),
                       close
                FROM   indexes
                WHERE  stock_name = ?
                  AND  substr(datetime,1,10) = (
                           SELECT MAX(substr(datetime,1,10))
                           FROM   indexes
                           WHERE  stock_name = ?
                             AND  substr(datetime,1,10) < ?
                       )
                """,
                (symbol, symbol, before_date),
            ).fetchone()
        if row and row[0] is not None:
            # close = last candle of that day
            with sqlite3.connect(db) as conn:
                last = conn.execute(
                    """
                    SELECT close FROM indexes
                    WHERE  stock_name = ?
                      AND  substr(datetime,1,10) = (
                               SELECT MAX(substr(datetime,1,10))
                               FROM   indexes
                               WHERE  stock_name = ?
                                 AND  substr(datetime,1,10) < ?
                           )
                    ORDER  BY datetime DESC LIMIT 1
                    """,
                    (symbol, symbol, before_date),
                ).fetchone()
            return (row[0], row[1], last[0]) if last else None
    except Exception:
        logger.exception("_prev_day_ohlc_from_db failed for %s", symbol)
    return None


def compute_pivots(df: pd.DataFrame, db: str = "", symbol: str = "") -> pd.DataFrame:
    """
    Standard Pivot Point levels using the previous trading day's H, L, C.
    When the first date in the DataFrame has no prior day in the batch,
    falls back to querying the DB directly so no candle is left with NULL pivots.
    """
    try:
        df = df.copy()
        dt = pd.to_datetime(df["datetime"])
        if dt.dt.tz is not None:
            dt = dt.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
        df["_date"] = dt.dt.date

        daily = (
            df.groupby("_date")
            .agg(d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last"))
            .reset_index()
            .sort_values("_date")
        )

        daily["prev_high"]  = daily["d_high"].shift(1)
        daily["prev_low"]   = daily["d_low"].shift(1)
        daily["prev_close"] = daily["d_close"].shift(1)

        # Fill the first row's prev values from DB if available
        if daily["prev_high"].isna().iloc[0]:
            first_date = str(daily["_date"].iloc[0])
            prev = _prev_day_ohlc_from_db(db, symbol, first_date)
            if prev:
                daily.loc[daily.index[0], "prev_high"]  = prev[0]
                daily.loc[daily.index[0], "prev_low"]   = prev[1]
                daily.loc[daily.index[0], "prev_close"] = prev[2]
                logger.debug("[%s] Pivot seed from DB for first date %s", symbol, first_date)

        ph = daily["prev_high"]
        pl = daily["prev_low"]
        pc = daily["prev_close"]

        daily["pivot"]    = (ph + pl + pc) / 3
        daily["pivot_r1"] = 2 * daily["pivot"] - pl
        daily["pivot_r2"] = daily["pivot"] + (ph - pl)
        daily["pivot_r3"] = ph + 2 * (daily["pivot"] - pl)
        daily["pivot_s1"] = 2 * daily["pivot"] - ph
        daily["pivot_s2"] = daily["pivot"] - (ph - pl)
        daily["pivot_s3"] = pl - 2 * (ph - daily["pivot"])

        pivot_cols = ["_date", "pivot", "pivot_r1", "pivot_r2", "pivot_r3",
                      "pivot_s1", "pivot_s2", "pivot_s3"]
        df = df.merge(daily[pivot_cols], on="_date", how="left")
        df.drop(columns=["_date"], inplace=True)
        logger.debug("Pivot levels computed for %d candles", len(df))
    except Exception:
        logger.exception("compute_pivots failed — pivot columns will be None")
        for col in ("pivot", "pivot_r1", "pivot_r2", "pivot_r3",
                    "pivot_s1", "pivot_s2", "pivot_s3"):
            df[col] = None
    return df
