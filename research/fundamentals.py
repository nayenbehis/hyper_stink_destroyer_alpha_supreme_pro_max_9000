"""Fundamental data fetchers: yfinance (free), FMP, Alpha Vantage."""

from __future__ import annotations

import os
from typing import Any

import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

_FMP_KEY = os.getenv("FMP_API_KEY", "")
_AV_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
_FMP_BASE = "https://financialmodelingprep.com/api/v3"


# ---------------------------------------------------------------------------
# yfinance — no API key required
# ---------------------------------------------------------------------------

def get_snapshot(ticker: str) -> dict[str, Any]:
    """Price + key stats for a ticker via yfinance."""
    t = yf.Ticker(ticker)
    info = t.info
    return {
        "name": info.get("longName", ticker),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "prev_close": info.get("previousClose"),
        "open": info.get("open"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps": info.get("trailingEps"),
        "dividend_yield": info.get("dividendYield"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "description": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
    }


def get_price_history(ticker: str, period: str = "1y", interval: str = "1d"):
    """OHLCV history as a pandas DataFrame."""
    return yf.Ticker(ticker).history(period=period, interval=interval)


def get_financials(ticker: str) -> dict[str, Any]:
    """Annual income statement, balance sheet, and cash flow via yfinance."""
    t = yf.Ticker(ticker)
    return {
        "income_statement": t.financials,
        "balance_sheet": t.balance_sheet,
        "cash_flow": t.cashflow,
    }


def get_earnings_history(ticker: str):
    """Quarterly earnings history."""
    return yf.Ticker(ticker).earnings_history


def get_earnings_data(ticker: str) -> dict:
    """Next earnings date + recent quarterly EPS actuals."""
    t = yf.Ticker(ticker)
    result: dict = {"next_date": None, "history": []}

    # Next earnings date
    try:
        cal = t.calendar
        if isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            dl = list(dates) if hasattr(dates, "__iter__") and not isinstance(dates, str) else [dates]
            if dl:
                result["next_date"] = str(dl[0])[:10]
    except Exception:
        pass

    if not result["next_date"]:
        try:
            from datetime import datetime, timezone
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                now = datetime.now(tz=timezone.utc)
                future = ed[ed.index > now]
                if not future.empty:
                    result["next_date"] = str(future.index[-1])[:10]
        except Exception:
            pass

    # Quarterly EPS surprises
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            for idx, row in eh.tail(6).iterrows():
                actual = row.get("epsActual")
                estimate = row.get("epsEstimate")
                # index is a Timestamp — format as YYYY-MM-DD
                try:
                    period = str(idx)[:10]
                except Exception:
                    period = ""
                if actual is not None:
                    surprise_pct = ((actual - estimate) / abs(estimate) * 100) if estimate else None
                    result["history"].append({
                        "period": period,
                        "actual": float(actual),
                        "estimate": float(estimate) if estimate is not None else None,
                        "surprise_pct": round(surprise_pct, 1) if surprise_pct is not None else None,
                    })
    except Exception:
        pass

    return result


# Curated sector peer groups (top liquid names per sector) — fallback only
_SECTOR_PEERS: dict[str, list[str]] = {
    "Technology":             ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA"],
    "Financial Services":     ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK"],
    "Healthcare":             ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "ABT"],
    "Consumer Cyclical":      ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "TGT"],
    "Consumer Defensive":     ["WMT", "PG", "KO", "PEP", "COST", "CL", "GIS"],
    "Energy":                 ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO"],
    "Industrials":            ["HON", "GE", "CAT", "BA", "RTX", "LMT", "DE"],
    "Real Estate":            ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG"],
    "Utilities":              ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE"],
    "Basic Materials":        ["LIN", "APD", "ECL", "SHW", "FCX", "NEM", "NUE"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ"],
}

# Industry-level peers (more specific than sector)
_INDUSTRY_PEERS: dict[str, list[str]] = {
    "Other Industrial Metals & Mining": ["MP", "UUUU", "LTHM", "SLI", "NVMI"],
    "Specialty Chemicals":              ["ALB", "LTHM", "SQM", "LIVENT", "PGNY"],
    "Semiconductor Equipment & Materials": ["AMAT", "LRCX", "KLAC", "ONTO", "CAMT"],
    "Semiconductors":                   ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "MRVL"],
    "Software—Infrastructure":          ["MSFT", "ORCL", "IBM", "SNOW", "MDB", "DDOG"],
    "Software—Application":             ["ADBE", "CRM", "WDAY", "NOW", "INTU", "HUBS"],
    "Consumer Electronics":             ["AAPL", "SONO", "HEAR", "VZIO"],
    "Internet Content & Information":   ["GOOGL", "META", "SNAP", "PINS", "TWTR"],
    "Drug Manufacturers—General":       ["PFE", "JNJ", "MRK", "ABBV", "LLY", "BMY"],
    "Biotechnology":                    ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA"],
    "Oil & Gas E&P":                    ["COP", "EOG", "PXD", "DVN", "FANG", "OVV"],
    "Steel":                            ["NUE", "STLD", "CLF", "X", "CMC"],
    "Gold":                             ["NEM", "AEM", "GOLD", "KGC", "AG"],
    "Copper":                           ["FCX", "SCCO", "HBM"],
    "Lithium & Battery Tech":           ["ALB", "SQM", "LTHM", "PGNY", "AEHR"],
    "Rare Earth & Strategic Materials": ["MP", "UUUU", "REX", "NOVR"],
}

# Manual peer overrides — add tickers here when auto-matching gives bad results
_MANUAL_PEERS: dict[str, list[str]] = {
    "MP":   ["UUUU", "LTHM", "ALB", "SQM", "PGNY"],
    "LTHM": ["ALB", "SQM", "MP", "UUUU", "PGNY"],
    "ALB":  ["SQM", "LTHM", "MP", "UUUU", "FMC"],
}


def get_peers(ticker: str, sector: str, limit: int = 5, industry: str = "") -> list[dict]:
    """Return peer metrics, matched by manual override > industry > sector.

    Sorted by closest market cap to `ticker`. Each result includes a 'match'
    field: 'manual', 'industry', or 'sector'.
    """
    t_upper = ticker.upper()

    # Determine candidate list and match type
    if t_upper in _MANUAL_PEERS:
        candidates_raw = [p for p in _MANUAL_PEERS[t_upper] if p != t_upper]
        match_type = "manual"
    elif industry and industry in _INDUSTRY_PEERS:
        candidates_raw = [p for p in _INDUSTRY_PEERS[industry] if p != t_upper]
        match_type = "industry"
    else:
        # Try partial industry match
        ind_lower = (industry or "").lower()
        matched_industry = next(
            (k for k in _INDUSTRY_PEERS if ind_lower and ind_lower in k.lower()), None
        )
        if matched_industry:
            candidates_raw = [p for p in _INDUSTRY_PEERS[matched_industry] if p != t_upper]
            match_type = "industry"
        else:
            candidates_raw = [p for p in _SECTOR_PEERS.get(sector, []) if p != t_upper]
            match_type = "sector"

    # Fetch target market cap for sorting
    target_mc = None
    try:
        target_mc = yf.Ticker(ticker).info.get("marketCap")
    except Exception:
        pass

    results = []
    for p in candidates_raw[:limit + 3]:  # fetch extras to allow sorting
        try:
            info = yf.Ticker(p).info
            results.append({
                "ticker": p,
                "name": info.get("shortName", p),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "eps": info.get("trailingEps"),
                "ytd_change": info.get("52WeekChange"),
                "match": match_type,
            })
        except Exception:
            pass

    # Sort by closest market cap when possible
    if target_mc:
        results.sort(key=lambda x: abs((x.get("market_cap") or 0) - target_mc))

    return results[:limit]


def get_analyst_ratings(ticker: str) -> dict[str, Any]:
    """Analyst recommendations and price targets."""
    t = yf.Ticker(ticker)
    return {
        "recommendations": t.recommendations,
        "target_mean": t.info.get("targetMeanPrice"),
        "target_high": t.info.get("targetHighPrice"),
        "target_low": t.info.get("targetLowPrice"),
        "num_analysts": t.info.get("numberOfAnalystOpinions"),
        "recommendation": t.info.get("recommendationKey"),
    }


# ---------------------------------------------------------------------------
# Financial Modeling Prep (free tier: 250 calls/day)
# ---------------------------------------------------------------------------

def fmp_income_statement(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    if not _FMP_KEY:
        raise EnvironmentError("FMP_API_KEY not set")
    url = f"{_FMP_BASE}/income-statement/{ticker}?limit={limit}&apikey={_FMP_KEY}"
    return requests.get(url, timeout=10).json()


def fmp_balance_sheet(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    if not _FMP_KEY:
        raise EnvironmentError("FMP_API_KEY not set")
    url = f"{_FMP_BASE}/balance-sheet-statement/{ticker}?limit={limit}&apikey={_FMP_KEY}"
    return requests.get(url, timeout=10).json()


def fmp_cash_flow(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    if not _FMP_KEY:
        raise EnvironmentError("FMP_API_KEY not set")
    url = f"{_FMP_BASE}/cash-flow-statement/{ticker}?limit={limit}&apikey={_FMP_KEY}"
    return requests.get(url, timeout=10).json()


# ---------------------------------------------------------------------------
# Alpha Vantage (free tier: 25 calls/day)
# ---------------------------------------------------------------------------

def av_overview(ticker: str) -> dict[str, Any]:
    if not _AV_KEY:
        raise EnvironmentError("ALPHA_VANTAGE_KEY not set")
    url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={_AV_KEY}"
    return requests.get(url, timeout=10).json()


def av_earnings(ticker: str) -> dict[str, Any]:
    if not _AV_KEY:
        raise EnvironmentError("ALPHA_VANTAGE_KEY not set")
    url = f"https://www.alphavantage.co/query?function=EARNINGS&symbol={ticker}&apikey={_AV_KEY}"
    return requests.get(url, timeout=10).json()
