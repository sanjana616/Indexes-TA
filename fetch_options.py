"""
fetch_options.py — Fetch option chain every minute during market hours.
Bhav copy is fetched ONCE per run and reused for all 4 symbols x 4 expiries.
Run: python fetch_options.py
"""
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

import pytz

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from src.database import init_db, insert_option_data
from src.option_chain.nse_scraper import (
    get_expiry_dates, get_spot, _fetch_live_option_chain, _parse_bhav, _SYM_MAP
)

OPTION_DB = os.getenv("OPTION_DB", "data/option_chain.db")
MARKET_DB = os.getenv("MARKET_DB", "data/market_data.db")
IST       = pytz.timezone("Asia/Kolkata")
_SYMBOLS  = ["NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCAPNIFTY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 915 <= hm <= 1530


def _load_bhav():
    """Download bhav copy once — tries last 5 trading days."""
    from nselib import derivatives
    d = date.today()
    if d.weekday() >= 5:
        d -= timedelta(days=d.weekday() - 4)
    for i in range(5):
        td = d - timedelta(days=i)
        if td.weekday() >= 5:
            continue
        try:
            b = derivatives.fno_bhav_copy(td.strftime("%d-%m-%Y"))
            if b is not None and not b.empty:
                logger.info("Bhav loaded for %s (%d rows)", td, len(b))
                return b
        except Exception:
            continue
    return None


def fetch_and_store():
    now = datetime.now(IST)
    logger.info("=== %s ===", now.strftime("%Y-%m-%d %H:%M IST"))
    init_db(MARKET_DB, OPTION_DB)

    # fetch bhav ONCE for all symbols
    bhav = _load_bhav()

    for sym in _SYMBOLS:
        try:
            spot     = get_spot(sym, MARKET_DB) or 0.0
            expiries = get_expiry_dates(sym)[:4]
            if not expiries:
                continue

            fetched = []

            # 1. try live nsepython
            df_all = _fetch_live_option_chain(sym, spot)
            if not df_all.empty:
                for exp in expiries:
                    df_exp = df_all[df_all["expiry"] == exp].copy()
                    if not df_exp.empty:
                        fetched.append((df_exp, exp, spot))

            # 2. fallback: parse from cached bhav
            if not fetched and bhav is not None:
                nse_sym = _SYM_MAP.get(sym, "NIFTY")
                for exp in expiries:
                    try:
                        df = _parse_bhav(bhav, nse_sym, exp, spot)
                        if not df.empty:
                            fetched.append((df, exp, spot))
                    except Exception:
                        logger.exception("[%s] bhav parse error for %s", sym, exp)

            for df, exp, sp in fetched:
                insert_option_data(OPTION_DB, sym, df, sp)

            if not fetched:
                logger.warning("[%s] no data", sym)

        except Exception:
            logger.exception("[%s] error", sym)


def main():
    logger.info("Started — market hours Mon-Fri 09:15-15:30 IST")
    while True:
        now = datetime.now(IST)
        if is_market_open():
            fetch_and_store()
            elapsed = datetime.now(IST).second
            time.sleep(max(60 - elapsed, 1))
        else:
            hm = now.hour * 100 + now.minute
            if hm < 915:
                logger.info("Waiting for market open (09:15). Now: %s", now.strftime("%H:%M"))
            else:
                logger.info("Market closed (15:30). Now: %s", now.strftime("%H:%M"))
            time.sleep(60)


if __name__ == "__main__":
    main()
