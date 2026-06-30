"""
main.py — Pipeline orchestrator.
Run from project root: python -m src.main
"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MARKET_DB    = os.getenv("MARKET_DB",    "data/market_data.db")
OPTION_DB    = os.getenv("OPTION_DB",    "data/option_chain.db")
LOG_DIR      = os.getenv("LOG_DIR",      "data/logs")
SYMBOLS_FILE = os.getenv("SYMBOLS_FILE", "config/symbols.json")
README_FILE  = os.getenv("README_FILE",  "README.md")

# symbols that have NSE option chain support
_OPTION_SYMBOLS = ["NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCAPNIFTY"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

_fh = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"), maxBytes=5 * 1024 * 1024, backupCount=5
)
_fh.setFormatter(_fmt)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Src imports
# ---------------------------------------------------------------------------
from src.database                    import init_db, insert_data, insert_option_data
from src.tradingview_client          import get_tv
from src.fetch_data                  import fetch_all
from src.readme_generator            import update_readme
from src.option_chain.nse_scraper    import get_expiry_dates, get_spot, _fetch_live_option_chain, fetch_option_chain


def _load_symbols():
    with open(SYMBOLS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    indexes = data.get("Indexes", [])
    if not indexes:
        raise ValueError("'Indexes' list is empty in symbols.json")
    return indexes


def _fetch_option_chains(index_cfgs) -> dict:
    """
    Fetch live NSE option chain for all symbols.
    Returns {label: [(df_per_expiry, expiry, spot), ...]}
    """
    from src.option_chain.nse_scraper import fetch_option_chain, get_expiry_dates, get_spot, _fetch_live_option_chain
    option_data = {}
    labels      = {c["label"] for c in index_cfgs}

    for sym in _OPTION_SYMBOLS:
        if sym not in labels:
            continue
        try:
            spot     = get_spot(sym) or 0.0
            expiries = get_expiry_dates(sym)[:4]
            if not expiries:
                logger.warning("[%s] No expiries found", sym)
                continue

            # Try live API first — returns all expiries in one call
            df_all = _fetch_live_option_chain(sym, spot)
            fetched = []
            if not df_all.empty:
                for expiry in expiries:
                    df_exp = df_all[df_all["expiry"] == expiry].copy()
                    if not df_exp.empty:
                        fetched.append((df_exp, expiry, spot))
                        logger.info("[%s] %s — %d rows (live)", sym, expiry, len(df_exp))

            # Fallback to bhav per expiry if live failed
            if not fetched:
                for expiry in expiries:
                    try:
                        df = fetch_option_chain(sym, expiry, spot)
                        if not df.empty:
                            fetched.append((df, expiry, spot))
                            logger.info("[%s] %s — %d rows (bhav)", sym, expiry, len(df))
                    except Exception:
                        logger.exception("[%s] %s fetch error", sym, expiry)

            if fetched:
                option_data[sym] = fetched
            else:
                logger.warning("[%s] No option chain data fetched", sym)
        except Exception:
            logger.exception("[%s] Option chain fetch error", sym)

    return option_data


def main() -> None:
    logger.info("=== stock-data-cornjob starting ===")

    index_cfgs = _load_symbols()

    # 1. Init DBs
    init_db(MARKET_DB, OPTION_DB)

    # 2. Fetch OHLCV candles
    tv   = get_tv()
    data = fetch_all(tv, index_cfgs)

    # 3. Store latest candle per symbol
    for cfg in index_cfgs:
        label = cfg["label"]
        df    = data.get(label)
        if df is not None and not df.empty:
            try:
                insert_data(MARKET_DB, label, df)
            except Exception:
                logger.exception("[%s] insert_data failed", label)

    # 4. Fetch option chains from NSE (next 4 expiries per symbol)
    option_data = _fetch_option_chains(index_cfgs)

    # 5. Store option chain data into symbol-specific tables
    for sym, fetched_list in option_data.items():
        for df, expiry, spot in fetched_list:
            try:
                insert_option_data(OPTION_DB, sym, df, spot)
            except Exception:
                logger.exception("[%s] insert_option_data failed for expiry %s", sym, expiry)

    # 6. Update README
    # flatten option_data for readme_generator (just first expiry per symbol)
    readme_option = {sym: (fetched[0][0], fetched[0][2]) for sym, fetched in option_data.items()} if option_data else None
    update_readme(
        README_FILE,
        MARKET_DB,
        [c["label"] for c in index_cfgs],
        option_data=readme_option,
    )

    logger.info("=== Cycle complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
