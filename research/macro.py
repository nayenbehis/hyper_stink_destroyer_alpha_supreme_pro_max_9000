"""FRED macro data fetcher — free, just need a FRED_API_KEY in .env."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

_KEY = os.getenv("FRED_API_KEY", "")
_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Key FRED series
SERIES = {
    "fed_funds_rate":   {"id": "FEDFUNDS",    "label": "Fed Funds Rate",        "unit": "%"},
    "10y_yield":        {"id": "DGS10",        "label": "10Y Treasury Yield",    "unit": "%"},
    "2y_yield":         {"id": "DGS2",         "label": "2Y Treasury Yield",     "unit": "%"},
    "cpi_yoy":          {"id": "CPIAUCSL",     "label": "CPI (YoY %)",           "unit": "%", "transform": "pc1"},
    "core_pce":         {"id": "PCEPILFE",     "label": "Core PCE (YoY %)",      "unit": "%", "transform": "pc1"},
    "unemployment":     {"id": "UNRATE",       "label": "Unemployment Rate",     "unit": "%"},
    "gdp_growth":       {"id": "A191RL1Q225SBEA", "label": "Real GDP Growth",    "unit": "%"},
    "dollar_index":     {"id": "DTWEXBGS",     "label": "USD Trade-Weighted",    "unit": "index"},
    "vix":              {"id": "VIXCLS",       "label": "VIX",                   "unit": ""},
    "sp500":            {"id": "SP500",        "label": "S&P 500",               "unit": ""},
    "credit_spread":    {"id": "BAMLH0A0HYM2", "label": "HY Credit Spread",     "unit": "%"},
    "consumer_sentiment": {"id": "UMCSENT",   "label": "Consumer Sentiment",    "unit": "index"},
}

# Sector → most relevant overlays
SECTOR_SERIES = {
    "Technology":            ["10y_yield", "fed_funds_rate", "vix"],
    "Financial Services":    ["10y_yield", "2y_yield", "credit_spread"],
    "Real Estate":           ["10y_yield", "fed_funds_rate", "unemployment"],
    "Consumer Cyclical":     ["consumer_sentiment", "unemployment", "cpi_yoy"],
    "Consumer Defensive":    ["cpi_yoy", "consumer_sentiment", "dollar_index"],
    "Energy":                ["dollar_index", "cpi_yoy", "gdp_growth"],
    "Industrials":           ["gdp_growth", "dollar_index", "10y_yield"],
    "Healthcare":            ["cpi_yoy", "unemployment", "fed_funds_rate"],
    "Utilities":             ["10y_yield", "fed_funds_rate", "credit_spread"],
    "Basic Materials":       ["dollar_index", "gdp_growth", "cpi_yoy"],
    "Communication Services":["vix", "10y_yield", "consumer_sentiment"],
}
DEFAULT_SERIES = ["10y_yield", "fed_funds_rate", "cpi_yoy"]


def _fetch_series(series_id: str, transform: str = "", months: int = 24) -> pd.Series:
    """Fetch a FRED series as a pandas Series indexed by date."""
    start = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "observation_start": start,
        "file_type": "json",
        "sort_order": "asc",
    }
    if not _KEY:
        raise EnvironmentError("FRED_API_KEY not set — get a free key at fred.stlouisfed.org/docs/api/api_key.html")
    params["api_key"] = _KEY

    if transform:
        params["units"] = transform

    resp = requests.get(_BASE, params=params, timeout=10)
    obs = resp.json().get("observations", [])
    data = {o["date"]: float(o["value"]) for o in obs if o["value"] != "."}
    return pd.Series(data, name=series_id)


def get_snapshot() -> dict[str, float | None]:
    """Return the latest reading for all key macro indicators."""
    result = {}
    for key, meta in SERIES.items():
        try:
            transform = meta.get("transform", "")
            s = _fetch_series(meta["id"], transform=transform, months=3)
            result[key] = {
                "value": float(s.iloc[-1]) if len(s) else None,
                "prev": float(s.iloc[-2]) if len(s) > 1 else None,
                "label": meta["label"],
                "unit": meta["unit"],
            }
        except Exception:
            result[key] = {"value": None, "prev": None, "label": meta["label"], "unit": meta["unit"]}
    return result


def get_series_for_chart(series_key: str, months: int = 18) -> pd.Series:
    """Return a time series for chart overlay."""
    meta = SERIES.get(series_key)
    if not meta:
        return pd.Series()
    return _fetch_series(meta["id"], transform=meta.get("transform", ""), months=months)


def relevant_series(sector: str) -> list[str]:
    """Return the most relevant macro series keys for a given sector."""
    return SECTOR_SERIES.get(sector, DEFAULT_SERIES)
