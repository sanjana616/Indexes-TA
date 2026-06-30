"""readme_generator.py — Auto-generates README.md with market + option chain tables."""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import pytz

from src.signals import generate_signal

logger = logging.getLogger(__name__)
IST    = pytz.timezone("Asia/Kolkata")

_ICONS = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
_f     = lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else "-"
_fi    = lambda x: f"{int(x):,}" if pd.notna(x) and x is not None else "-"


# ---------------------------------------------------------------------------
# Market data tables
# ---------------------------------------------------------------------------

def build_rows(symbols: List[str], db: str) -> str:
    """Build HTML <tr> rows for market indexes / futures."""
    from src.database import latest_row

    html = ""
    for sym in symbols:
        row = latest_row(db, sym)
        if row is None:
            continue
        signal = generate_signal(row)
        vol    = int(row["volume"]) if pd.notna(row["volume"]) else 0
        html += (
            f"<tr>"
            f"<td><b>{sym}</b></td>"
            f"<td>{row['datetime']}</td>"
            f"<td>{_f(row['close'])}</td>"
            f"<td>{vol:,}</td>"
            f"<td>{_f(row['rsi_14'])}</td>"
            f"<td>{_f(row['ema_20'])}</td>"
            f"<td>{_f(row['macd'])}</td>"
            f"<td>{_f(row['atr'])}</td>"
            f"<td>{_f(row['adx'])}</td>"
            f"<td>{_ICONS[signal]}</td>"
            f"</tr>\n"
        )
    return html


def _market_table(title: str, rows_html: str) -> str:
    header = (
        "<tr>"
        "<th>Symbol</th><th>Time (IST)</th><th>Close</th><th>Volume</th>"
        "<th>RSI(14)</th><th>EMA20</th><th>MACD</th><th>ATR</th><th>ADX</th>"
        "<th>Signal</th>"
        "</tr>"
    )
    return f"## {title}\n\n<table>\n{header}\n{rows_html}</table>\n\n"


# ---------------------------------------------------------------------------
# Option chain tables
# ---------------------------------------------------------------------------

def _option_chain_table(symbol: str, df: pd.DataFrame, spot: float) -> str:
    """
    Build an HTML option chain table for one symbol.
    Shows CE side | Strike | PE side with OI, Volume, IV, LTP, Delta.
    Highlights ATM row.
    """
    if df.empty:
        return f"## 🔗 {symbol} Option Chain\n\n_No data available._\n\n"

    # Pick current expiry only
    expiries = df["expiry"].unique()
    expiry   = expiries[0] if len(expiries) > 0 else ""
    df       = df[df["expiry"] == expiry].copy()

    ce = df[df["option_type"] == "CE"].set_index("strike")
    pe = df[df["option_type"] == "PE"].set_index("strike")

    from src.option_chain.strike_selector import atm_strike
    atm = atm_strike(spot, _guess_gap(symbol))

    strikes = sorted(set(ce.index) | set(pe.index))

    header = (
        "<tr>"
        "<th>CE OI</th><th>CE Vol</th><th>CE IV</th><th>CE LTP</th><th>CE Δ</th>"
        "<th>Strike</th>"
        "<th>PE Δ</th><th>PE LTP</th><th>PE IV</th><th>PE Vol</th><th>PE OI</th>"
        "</tr>"
    )

    rows_html = ""
    for strike in strikes:
        is_atm = strike == atm
        style  = ' style="background:#fffde7;font-weight:bold;"' if is_atm else ""

        c = ce.loc[strike] if strike in ce.index else {}
        p = pe.loc[strike] if strike in pe.index else {}

        rows_html += (
            f"<tr{style}>"
            f"<td>{_fi(c.get('oi'))}</td>"
            f"<td>{_fi(c.get('volume'))}</td>"
            f"<td>{_f(c.get('iv'))}</td>"
            f"<td>{_f(c.get('close'))}</td>"
            f"<td>{_f(c.get('delta'))}</td>"
            f"<td><b>{int(strike)}</b>{'  ← ATM' if is_atm else ''}</td>"
            f"<td>{_f(p.get('delta'))}</td>"
            f"<td>{_f(p.get('close'))}</td>"
            f"<td>{_f(p.get('iv'))}</td>"
            f"<td>{_fi(p.get('volume'))}</td>"
            f"<td>{_fi(p.get('oi'))}</td>"
            f"</tr>\n"
        )

    return (
        f"## 🔗 {symbol} Option Chain &nbsp; `Expiry: {expiry}` &nbsp; `Spot: {spot:.2f}`\n\n"
        f"<table>\n{header}\n{rows_html}</table>\n\n"
    )


def _guess_gap(symbol: str) -> float:
    gaps = {"NIFTY50": 50, "BANKNIFTY": 100, "SENSEX": 100, "MIDCAPNIFTY": 25, "FINNIFTY": 50}
    return gaps.get(symbol, 50)


# ---------------------------------------------------------------------------
# Main update function
# ---------------------------------------------------------------------------

def update_readme(
    readme_path: str,
    market_db: str,
    index_symbols: List[str],
    option_data: Optional[Dict[str, tuple]] = None,
) -> None:
    """
    Overwrite README.md with market tables + option chain tables.

    Parameters
    ----------
    option_data : dict of {symbol: (DataFrame, spot_price)}
                  Pass None to skip option chain section.
    """
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    content = (
        f"<!-- Auto-generated — {ts} -->\n\n"
        f"**Last updated:** {ts}\n\n"
        + _market_table("📊 Market Indexes", build_rows(index_symbols, market_db))
    )

    if option_data:
        content += "---\n\n# 📋 Option Chain\n\n"
        for sym, (df, spot) in option_data.items():
            content += _option_chain_table(sym, df, spot)

    try:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("README updated: %s", readme_path)
    except OSError:
        logger.exception("Failed to write README: %s", readme_path)
