"""yfinance batch price fetching for the screener."""
from __future__ import annotations

import sys
import time
from typing import Any

import pandas as pd
import yfinance as yf

from . import cache

_CHUNK    = 200
_5YR_PERIOD = "5y"
_INFO_RETRIES = 3


def _safe_info(tkr: str) -> dict[str, Any]:
    """Fetch .info with retry on 401/429 (Yahoo rate-limit / auth blips)."""
    for attempt in range(_INFO_RETRIES):
        try:
            obj  = yf.Ticker(tkr)
            info = obj.info or {}
            if info:
                return info
        except Exception as e:
            msg = str(e).lower()
            if "401" in msg or "429" in msg:
                time.sleep(5 * (attempt + 1))
                continue
            break
    return {}


def fetch_prices(tickers: list[str], refresh: bool = False) -> pd.DataFrame:
    """Batch-download 5-year OHLCV for all tickers.

    Returns DataFrame indexed by ticker with columns:
        price, adv (avg 90-day dollar volume), hi_5yr, lo_5yr
    Does NOT fetch .info here — market_cap and neglect metrics are added
    separately via fetch_neglect_info() for a targeted subset only.
    Cached for 7 days.
    """
    key = "prices"
    if not refresh:
        cached = cache.load(key)
        if cached:
            df = pd.DataFrame(cached)
            df.index = df["ticker"]
            return df.drop(columns="ticker")

    rows = []
    tickers = sorted(set(tickers))

    print(f"  Fetching 5-yr history for {len(tickers)} tickers…", file=sys.stderr)
    hist_all: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), _CHUNK):
        chunk = tickers[i : i + _CHUNK]
        try:
            raw = yf.download(
                chunk, period=_5YR_PERIOD, interval="1d",
                auto_adjust=True, progress=False, threads=True,
            )
            if isinstance(raw.columns, pd.MultiIndex):
                for tkr in chunk:
                    try:
                        hist_all[tkr] = raw.xs(tkr, axis=1, level=1)
                    except KeyError:
                        pass
            else:
                # single-ticker returned a flat DataFrame
                if chunk:
                    hist_all[chunk[0]] = raw
        except Exception as e:
            print(f"  history chunk error: {e}", file=sys.stderr)

    for tkr in tickers:
        hist  = hist_all.get(tkr)
        price = adv = hi_5yr = lo_5yr = None

        if hist is not None and not hist.empty and "Close" in hist.columns:
            close  = hist["Close"].dropna()
            volume = hist.get("Volume", pd.Series(dtype=float)).fillna(0)
            if not close.empty:
                price  = float(close.iloc[-1])
                hi_5yr = float(close.max())
                lo_5yr = float(close.min())
                dollar_vol = close * volume
                adv    = float(dollar_vol.tail(90).mean()) if len(dollar_vol) >= 20 else None

        rows.append({
            "ticker": tkr,
            "price":  price,
            "adv":    adv,
            "hi_5yr": hi_5yr,
            "lo_5yr": lo_5yr,
        })

    df = pd.DataFrame(rows).set_index("ticker")
    cache.save(key, df.reset_index().to_dict("records"))
    return df


def fetch_neglect_info(tickers: list[str], refresh: bool = False) -> pd.DataFrame:
    """Fetch per-ticker Yahoo info for a targeted subset (top scorers after phase-1).

    Returns DataFrame indexed by ticker with columns:
        market_cap_yf, shares_yf, analysts, inst_pct
    Cached separately for 7 days.
    """
    key = f"neglect_info_{len(tickers)}"
    if not refresh:
        cached = cache.load(key)
        if cached:
            df = pd.DataFrame(cached)
            df.index = df["ticker"]
            return df.drop(columns="ticker")

    rows = []
    print(f"  Fetching Yahoo info for {len(tickers)} tickers…", file=sys.stderr)
    for i, tkr in enumerate(tickers):
        info = _safe_info(tkr)
        rows.append({
            "ticker":      tkr,
            "market_cap_yf": info.get("marketCap"),
            "shares_yf":   info.get("sharesOutstanding"),
            "analysts":    info.get("numberOfAnalystOpinions"),
            "inst_pct":    info.get("heldPercentInstitutions"),
        })
        if i % 25 == 0 and i:
            print(f"  info: {i}/{len(tickers)}…", file=sys.stderr)

    df = pd.DataFrame(rows).set_index("ticker")
    cache.save(key, df.reset_index().to_dict("records"))
    return df
