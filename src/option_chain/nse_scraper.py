"""
nse_scraper.py
Live     : NSE option chain API (per-minute snapshots)
Fallback : nselib fno_bhav_copy (EOD)
Greeks   : py_vollib (Black-Scholes)
"""
import logging
import time
import requests
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_RISK_FREE = 0.065
_STRIKE_GAP: Dict[str, float] = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "FINNIFTY":   50,
    "MIDCPNIFTY": 25,
}
_SYM_MAP = {
    "NIFTY50":     "NIFTY",
    "BANKNIFTY":   "BANKNIFTY",
    "FINNIFTY":    "FINNIFTY",
    "MIDCAPNIFTY": "MIDCPNIFTY",
}
_NSE_LIVE_SYM = {
    "NIFTY50":     "NIFTY%2050",
    "BANKNIFTY":   "BANKNIFTY",
    "FINNIFTY":    "FINNIFTY",
    "MIDCAPNIFTY": "MIDCPNIFTY",
}
_MONTHLY_EXPIRY_SYMS = {"MIDCPNIFTY"}

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
}


def _nse_session() -> requests.Session:
    """Create a requests session with NSE cookies."""
    s = requests.Session()
    s.headers.update(_NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
        time.sleep(1)
    except Exception:
        pass
    return s


def _fetch_live_option_chain(symbol: str, spot: float) -> pd.DataFrame:
    """
    Fetch live option chain using nsepython (handles NSE cookies automatically).
    """
    nse_sym = _NSE_LIVE_SYM.get(symbol, "NIFTY")
    try:
        from nsepython import nse_optionchain_scrapper
        data = nse_optionchain_scrapper(nse_sym)
        records = data.get("records", {})
        spot    = records.get("underlyingValue", spot)
        raw     = records.get("data", [])
    except Exception as e:
        logger.warning("[%s] nsepython live fetch failed: %s", symbol, e)
        return pd.DataFrame()

    rows = []
    for item in raw:
        expiry = item.get("expiryDate", "")
        strike = float(item.get("strikePrice", 0))
        try:
            tte = max((datetime.strptime(expiry, "%d-%b-%Y").date() - date.today()).days, 1) / 365.0
        except Exception:
            tte = 0.1

        for otype, key in (("CE", "CE"), ("PE", "PE")):
            d = item.get(key, {})
            if not d:
                continue
            ltp    = float(d.get("lastPrice") or 0)
            oi     = float(d.get("openInterest") or 0)
            chg_oi = float(d.get("changeinOpenInterest") or 0)
            vol    = float(d.get("totalTradedVolume") or 0)
            iv_raw = float(d.get("impliedVolatility") or 0)
            iv     = iv_raw / 100 if iv_raw > 0 else 0.18
            flag   = "c" if otype == "CE" else "p"
            greeks = _greeks(flag, spot, strike, tte, iv) if spot > 0 and ltp > 0 else {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}

            rows.append({
                "expiry":           expiry,
                "strike":           strike,
                "option_type":      otype,
                "ltp":              ltp,
                "volume":           vol,
                "oi":               oi,
                "oi_chg":           chg_oi,
                "iv":               round(iv_raw, 2),
                "underlying_value": spot,
                **greeks,
            })

    df = pd.DataFrame(rows)
    logger.info("[%s] Live nsepython: %d rows (spot=%.2f)", symbol, len(df), spot)
    return df


# ── Greeks via py_vollib ──────────────────────────────────────────────────────

def _greeks(flag: str, S: float, K: float, t: float, iv: float) -> dict:
    """
    flag : 'c' for CE, 'p' for PE
    S    : spot, K : strike, t : time to expiry (years), iv : decimal (0.18 = 18%)
    """
    try:
        from vollib.black_scholes.greeks import analytical as ga
        return {
            "delta": round(ga.delta(flag, S, K, t, _RISK_FREE, iv), 4),
            "gamma": round(ga.gamma(flag, S, K, t, _RISK_FREE, iv), 6),
            "theta": round(ga.theta(flag, S, K, t, _RISK_FREE, iv), 4),
            "vega":  round(ga.vega( flag, S, K, t, _RISK_FREE, iv), 4),
            "rho":   round(ga.rho(  flag, S, K, t, _RISK_FREE, iv), 4),
        }
    except Exception:
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}


def _iv_from_price(flag: str, S: float, K: float, t: float, price: float) -> Optional[float]:
    """Compute implied volatility from market price using py_vollib."""
    try:
        from vollib.black_scholes.implied_volatility import implied_volatility as iv_fn
        iv = iv_fn(price, S, K, t, _RISK_FREE, flag)
        return round(iv, 4) if iv and 0.001 < iv < 20 else None
    except Exception:
        return None


# ── Expiry helpers ────────────────────────────────────────────────────────────

def get_expiry_dates(symbol: str = "NIFTY50") -> List[str]:
    """
    Return expiry date strings for `symbol`.
    - NIFTY/BANKNIFTY/FINNIFTY : from nselib expiry_dates_option_index()
    - MIDCAPNIFTY               : extracted from bhav copy (monthly expiries)
    Format: ['23-Jun-2026', '30-Jun-2026', ...]
    """
    nse_sym = _SYM_MAP.get(symbol, "NIFTY")

    # MIDCPNIFTY — nselib returns [] so read from bhav
    if nse_sym in _MONTHLY_EXPIRY_SYMS:
        return _expiries_from_bhav(nse_sym)

    # All others via nselib
    try:
        from nselib import derivatives
        data     = derivatives.expiry_dates_option_index()
        expiries = data.get(nse_sym, [])
        if expiries:
            logger.info("[%s] nselib expiries: %s", symbol, expiries[:4])
            return expiries
    except Exception:
        logger.warning("[%s] nselib expiry fetch failed", symbol, exc_info=True)

    # Fallback: next 6 Thursdays
    result, cursor = [], _next_thursday(date.today())
    for _ in range(6):
        result.append(cursor.strftime("%d-%b-%Y"))
        cursor += timedelta(weeks=1)
    return result


def _expiries_from_bhav(nse_sym: str) -> List[str]:
    """Extract available expiry dates from bhav copy for symbols like MIDCPNIFTY."""
    try:
        from nselib import derivatives
        for i in range(5):
            d = date.today() - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            try:
                bhav = derivatives.fno_bhav_copy(d.strftime("%d-%m-%Y"))
            except Exception:
                continue
            if bhav is None or bhav.empty:
                continue
            sub = bhav[(bhav['TckrSymb'] == nse_sym) & (bhav['OptnTp'].notna())]
            if sub.empty:
                continue
            raw = sorted(sub['XpryDt'].astype(str).str[:10].unique())
            result = []
            for r in raw:
                try:
                    result.append(datetime.strptime(r, "%Y-%m-%d").strftime("%d-%b-%Y"))
                except Exception:
                    pass
            if result:
                logger.info("[%s] bhav expiries: %s", nse_sym, result)
                return result
    except Exception:
        logger.warning("bhav expiry fetch failed for %s", nse_sym, exc_info=True)
    return []


def _next_thursday(ref: date) -> date:
    days = (3 - ref.weekday()) % 7
    return ref + timedelta(days=max(days, 1))


def _get_last_trade_date() -> str:
    """Return the last trading weekday as DD-MM-YYYY string."""
    d = date.today()
    if d.weekday() >= 5:
        d -= timedelta(days=d.weekday() - 4)
    return d.strftime("%d-%m-%Y")


# ── Option chain fetch ────────────────────────────────────────────────────────

def _parse_bhav(df: pd.DataFrame, nse_sym: str, expiry_str: str, spot: float) -> pd.DataFrame:
    """
    Parse nselib fno_bhav_copy DataFrame into standardised option chain format.
    expiry_str format: '23-Jun-2026'
    """
    try:
        exp_date = datetime.strptime(expiry_str, "%d-%b-%Y").date()
    except Exception:
        exp_date = _next_thursday(date.today())

    # Normalise expiry to match bhav XpryDt (YYYY-MM-DD)
    exp_iso = exp_date.strftime("%Y-%m-%d")

    # Filter symbol + expiry + options only
    mask = (
        (df["TckrSymb"] == nse_sym) &
        (df["XpryDt"].astype(str).str[:10] == exp_iso) &
        (df["OptnTp"].notna()) &
        (df["StrkPric"].notna())
    )
    sub = df[mask].copy()
    if sub.empty:
        logger.warning("[%s] No bhav rows for expiry %s", nse_sym, exp_iso)
        return pd.DataFrame()

    tte = max((exp_date - date.today()).days, 1) / 365.0
    rows = []

    for _, r in sub.iterrows():
        otype = str(r["OptnTp"]).upper()   # CE or PE
        flag  = "c" if otype == "CE" else "p"
        K     = float(r["StrkPric"])
        ltp   = float(r["LastPric"]) if r["LastPric"] else float(r["ClsPric"])
        oi    = float(r["OpnIntrst"])
        oi_chg= float(r["ChngInOpnIntrst"])
        vol   = float(r["TtlTradgVol"])

        iv = _iv_from_price(flag, spot, K, tte, ltp) if ltp > 0 else None
        if not iv:
            iv = 0.18  # default 18%

        greeks = _greeks(flag, spot, K, tte, iv)

        rows.append({
            "expiry":      expiry_str,
            "strike":      K,
            "option_type": otype,
            "open":        float(r["OpnPric"]) if r["OpnPric"] else None,
            "high":        float(r["HghPric"]) if r["HghPric"] else None,
            "low":         float(r["LwPric"])  if r["LwPric"]  else None,
            "close":       float(r["ClsPric"]) if r["ClsPric"] else None,
            "ltp":         ltp,
            "volume":      vol,
            "oi":          oi,
            "oi_chg":      oi_chg,
            "iv":          round(iv * 100, 2),   # store as %
            **greeks,
        })

    result = pd.DataFrame(rows)
    logger.info("[%s] Parsed %d rows for expiry %s (spot=%.2f)", nse_sym, len(result), expiry_str, spot)
    return result


def fetch_option_chain(
    symbol: str,
    expiry: str,
    spot: float,
    trade_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch option chain — live NSE API first, bhav copy fallback.
    If live succeeds, returns all expiries filtered to the requested one.
    """
    # ── Try live NSE API first ────────────────────────────────────────────────
    df_live = _fetch_live_option_chain(symbol, spot)
    if not df_live.empty:
        if expiry:
            df_exp = df_live[df_live["expiry"] == expiry].copy()
            if not df_exp.empty:
                return df_exp
        else:
            return df_live

    # ── Fallback: bhav copy (fetch once, parse for each expiry) ──────────────
    logger.info("[%s] Falling back to bhav copy", symbol)
    nse_sym = _SYM_MAP.get(symbol, "NIFTY")
    if not trade_date:
        d = date.today()
        if d.weekday() >= 5:
            d -= timedelta(days=d.weekday() - 4)
        for i in range(5):
            candidate = d - timedelta(days=i)
            if candidate.weekday() < 5:
                trade_date = candidate.strftime("%d-%m-%Y")
                break

    from nselib import derivatives
    bhav = None
    for i in range(5):
        try_date = (datetime.strptime(trade_date, "%d-%m-%Y").date() - timedelta(days=i))
        if try_date.weekday() >= 5:
            continue
        ds = try_date.strftime("%d-%m-%Y")
        try:
            logger.info("[%s] Trying bhav copy for %s", symbol, ds)
            b = derivatives.fno_bhav_copy(ds)
            if b is not None and not b.empty:
                bhav = b
                break
        except Exception:
            logger.warning("[%s] bhav failed for %s", symbol, ds, exc_info=True)

    if bhav is not None:
        df = _parse_bhav(bhav, nse_sym, expiry, spot)
        if not df.empty:
            return df

    logger.error("[%s] All option chain sources failed", symbol)
    return pd.DataFrame()


def get_spot(symbol: str, market_db: str = "data/market_data.db") -> Optional[float]:
    """Get latest spot price — tries nselib first, falls back to market_data.db."""
    try:
        from nselib import capital_market
        data = capital_market.index_data()
        if data is not None and not data.empty:
            sym_map_display = {
                "NIFTY50":     "NIFTY 50",
                "BANKNIFTY":   "NIFTY BANK",
                "FINNIFTY":    "NIFTY FIN SERVICE",
                "MIDCAPNIFTY": "NIFTY MIDCAP SELECT",
            }
            label = sym_map_display.get(symbol, "")
            row = data[data["indexSymbol"] == label] if "indexSymbol" in data.columns else pd.DataFrame()
            if not row.empty:
                return float(row.iloc[0]["last"])
    except Exception:
        pass

    # Fallback: read from market_data.db
    try:
        import sqlite3
        with sqlite3.connect(market_db) as conn:
            row = conn.execute(
                "SELECT close FROM indexes WHERE stock_name=? ORDER BY datetime DESC LIMIT 1",
                (symbol,)
            ).fetchone()
            if row:
                logger.info("[%s] spot from market_data.db: %.2f", symbol, row[0])
                return float(row[0])
    except Exception:
        pass
    return None
