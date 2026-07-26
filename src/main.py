"""
main.py — Option chain pipeline orchestrator.
Run from project root: python -m src.main
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

OPTION_DB    = os.getenv("OPTION_DB", "data/option_chain.db")
LOG_DIR      = os.getenv("LOG_DIR",   "data/logs")

_OPTION_SYMBOLS     = ["NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCAPNIFTY"]
_BSE_OPTION_SYMBOLS = ["SENSEX"]

os.makedirs(LOG_DIR, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
_fh  = RotatingFileHandler(os.path.join(LOG_DIR, "app.log"), maxBytes=5*1024*1024, backupCount=5)
_fh.setFormatter(_fmt)
_ch  = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)

import pytz
from datetime import datetime as _dt
from src.database                 import init_db, insert_option_data, prune_old_option_data
from src.option_chain.nse_scraper import get_expiry_dates, get_spot, _fetch_live_option_chain
from src.option_chain.bse_scraper import get_sensex_expiry_dates, fetch_sensex_option_chain

_IST = pytz.timezone("Asia/Kolkata")


def _is_market_open() -> bool:
    now = _dt.now(_IST)
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 915 <= hm <= 1530  # NSE market: 9:15 AM - 3:30 PM IST


def _fetch_option_chains() -> dict:
    option_data = {}

    for sym in _OPTION_SYMBOLS:
        try:
            spot     = get_spot(sym) or 0.0
            expiries = get_expiry_dates(sym)[:4]
            if not expiries:
                logger.warning("[%s] No expiries found", sym)
                continue

            df_all  = _fetch_live_option_chain(sym, spot)
            fetched = []
            if not df_all.empty:
                for expiry in expiries:
                    df_exp = df_all[df_all["expiry"] == expiry].copy()
                    if df_exp.empty:
                        continue
                    # Use spot from API response if get_spot() returned 0
                    exp_spot = spot
                    if exp_spot <= 0 and "spot" in df_exp.columns:
                        api_spot = df_exp["spot"].dropna()
                        if not api_spot.empty:
                            exp_spot = float(api_spot.iloc[0])
                            logger.info("[%s] using spot from API response: %.2f", sym, exp_spot)
                    fetched.append((df_exp, expiry, exp_spot))
                    logger.info("[%s] %s — %d rows (spot=%.2f)", sym, expiry, len(df_exp), exp_spot)
            else:
                logger.warning("[%s] Live API returned empty", sym)

            if fetched:
                option_data[sym] = fetched
        except Exception:
            logger.exception("[%s] Option chain fetch error", sym)

    # BSE SENSEX
    try:
        spot     = get_spot("SENSEX") or 0.0
        expiries = get_sensex_expiry_dates()[:4]
        fetched  = []
        for expiry in expiries:
            try:
                df = fetch_sensex_option_chain(expiry, spot)
                if df.empty:
                    continue
                # Use spot from API response if get_spot() returned 0
                exp_spot = spot
                if exp_spot <= 0 and "spot" in df.columns:
                    api_spot = df["spot"].dropna()
                    if not api_spot.empty:
                        exp_spot = float(api_spot.iloc[0])
                        logger.info("[SENSEX] using spot from API response: %.2f", exp_spot)
                fetched.append((df, expiry, exp_spot))
            except Exception:
                logger.exception("[SENSEX] fetch error for expiry %s", expiry)
        if fetched:
            option_data["SENSEX"] = fetched
    except Exception:
        logger.exception("[SENSEX] Option chain fetch error")

    return option_data


def main() -> None:
    logger.info("=== option-chain pipeline starting ===")

    init_db(OPTION_DB)

    if not _is_market_open():
        now = _dt.now(_IST)
        logger.info("Skipping — %s %s IST (market closed)", now.strftime("%A"), now.strftime("%H:%M"))
        return

    option_data = _fetch_option_chains()

    for sym, fetched_list in option_data.items():
        for df, expiry, spot in fetched_list:
            try:
                insert_option_data(OPTION_DB, sym, df, spot)
            except Exception:
                logger.exception("[%s] insert_option_data failed for expiry %s", sym, expiry)

    prune_old_option_data(OPTION_DB, keep_days=14)
    logger.info("=== Cycle complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
