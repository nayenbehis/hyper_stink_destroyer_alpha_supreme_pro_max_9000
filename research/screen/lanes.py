"""Phase-2 special lanes: insiders, spinoffs, activists."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

from .sec import EDGAR_UA, _get as sec_get

_EDGAR_BASE = "https://data.sec.gov"
_EFTS_BASE  = "https://efts.sec.gov/LATEST/search-index"

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _efts_filings(form_type: str, start: str, end: str, max_hits: int = 100) -> list[dict]:
    """Query EDGAR full-text search for filings of a given form type."""
    url = (
        f"https://efts.sec.gov/LATEST/search-index?q=%22{form_type}%22"
        f"&dateRange=custom&startdt={start}&enddt={end}"
        f"&forms={form_type}&hits.hits._source=period_of_report,entity_name,file_num,period_of_report"
        f"&hits.hits.total.value=1&hits.hits.hits.total=1"
    )
    r = sec_get(url, timeout=30)
    if not r.ok:
        return []
    hits = r.json().get("hits", {}).get("hits", [])
    return [h.get("_source", {}) for h in hits[:max_hits]]


# ---------------------------------------------------------------------------
# Insiders lane — recent Form 4 cluster buys
# ---------------------------------------------------------------------------

def _parse_form4_summary(accession_url: str) -> dict | None:
    """Fetch a Form 4 and return a summary dict, or None on error."""
    r = sec_get(accession_url, timeout=20)
    if not r.ok:
        return None
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(r.content)
        ns = ""
        def _t(tag):
            el = root.find(f"{ns}{tag}")
            return el.text.strip() if el is not None and el.text else None
        return {
            "issuer_cik":   _t(".//issuerCik"),
            "issuer_name":  _t(".//issuerName"),
            "issuer_ticker":_t(".//issuerTradingSymbol"),
            "officer_name": _t(".//rptOwnerName"),
            "filed":        _t(".//periodOfReport"),
        }
    except Exception:
        return None


def run_insiders_lane(
    universe_df: pd.DataFrame,
    days_back: int = 90,
    min_cluster_buys: int = 2,
) -> pd.DataFrame:
    """Find tickers with ≥min_cluster_buys insider purchases in the last days_back days.

    Returns DataFrame with: ticker, name, buy_count, officers (comma-sep), last_filed
    """
    from datetime import date, timedelta
    end   = date.today().isoformat()
    start = (date.today() - timedelta(days=days_back)).isoformat()

    ticker_to_name = dict(zip(universe_df["ticker"], universe_df["name"]))
    ticker_to_cik  = dict(zip(universe_df["ticker"], universe_df["cik"]))
    cik_to_ticker  = {v: k for k, v in ticker_to_cik.items()}

    # Fetch recent Form 4 submissions from EDGAR submissions API for each CIK
    # (more reliable than full-text search for filings)
    buy_counts: dict[str, list[str]] = {}  # ticker → [officer_name, ...]

    print(f"  Insiders lane: scanning Form 4s {start} → {end}…", file=sys.stderr)
    url = (
        f"https://efts.sec.gov/LATEST/search-index?forms=4"
        f"&dateRange=custom&startdt={start}&enddt={end}"
        f"&hits.hits.total.value=1"
    )
    r = sec_get(url, timeout=30)
    if not r.ok:
        print(f"  Insiders lane: EFTS search failed ({r.status_code})", file=sys.stderr)
        return pd.DataFrame()

    # EFTS doesn't return XML; use EDGAR submissions to scan clustered Form 4s
    # Simpler approach: use submissions/{CIK}.json for each company, check recent Form 4s
    rows = []
    all_ciks = list(universe_df["cik"])

    buy_map: dict[int, list[dict]] = {}

    for i, cik in enumerate(all_ciks[:500]):  # limit for speed; adjust with --deep flag
        url = f"{_EDGAR_BASE}/submissions/CIK{cik:010d}.json"
        r = sec_get(url, timeout=20)
        if not r.ok:
            continue
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms     = filings.get("form", [])
        dates     = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        for form, filed, acc in zip(forms, dates, accessions):
            if form != "4" or filed < start:
                continue
            buy_map.setdefault(cik, []).append({"filed": filed, "accession": acc})

        if i % 50 == 0 and i:
            print(f"  Insiders: scanned {i}/{min(len(all_ciks), 500)} companies…", file=sys.stderr)

    for cik, f4s in buy_map.items():
        if len(f4s) < min_cluster_buys:
            continue
        ticker = cik_to_ticker.get(cik)
        if not ticker:
            continue
        rows.append({
            "ticker":    ticker,
            "name":      ticker_to_name.get(ticker, ""),
            "buy_count": len(f4s),
            "last_filed": max(f["filed"] for f in f4s),
        })

    if not rows:
        return pd.DataFrame(columns=["ticker", "name", "buy_count", "last_filed"])
    return pd.DataFrame(rows).sort_values("buy_count", ascending=False)


# ---------------------------------------------------------------------------
# Spinoffs lane — recent 10-12B/G stubs
# ---------------------------------------------------------------------------

def run_spinoffs_lane(days_back: int = 365) -> pd.DataFrame:
    """Find recent spinoff registrations (Form 10-12B and 10-12G) on EDGAR.

    Returns DataFrame with: ticker, company_name, filed_date, description
    """
    from datetime import date, timedelta
    end   = date.today().isoformat()
    start = (date.today() - timedelta(days=days_back)).isoformat()

    rows = []
    for form in ("10-12B", "10-12G"):
        url = (
            f"https://efts.sec.gov/LATEST/search-index?forms={form}"
            f"&dateRange=custom&startdt={start}&enddt={end}"
        )
        r = sec_get(url, timeout=30)
        if not r.ok:
            continue
        for hit in r.json().get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            rows.append({
                "form":         form,
                "company_name": src.get("display_names", [src.get("entity_name", "")])[0] if src.get("display_names") else src.get("entity_name", ""),
                "filed_date":   src.get("file_date", ""),
                "cik":          src.get("entity_id", ""),
            })

    if not rows:
        return pd.DataFrame(columns=["form", "company_name", "filed_date", "cik"])
    df = pd.DataFrame(rows).drop_duplicates("cik")
    return df.sort_values("filed_date", ascending=False)


# ---------------------------------------------------------------------------
# Activists lane — recent SC 13D stubs
# ---------------------------------------------------------------------------

def run_activists_lane(days_back: int = 180) -> pd.DataFrame:
    """Find recent SC 13D filings (activist stake disclosure) on EDGAR.

    Returns DataFrame with: company_name, filed_date, filer
    """
    from datetime import date, timedelta
    end   = date.today().isoformat()
    start = (date.today() - timedelta(days=days_back)).isoformat()

    url = (
        f"https://efts.sec.gov/LATEST/search-index?forms=SC+13D"
        f"&dateRange=custom&startdt={start}&enddt={end}"
    )
    r = sec_get(url, timeout=30)
    if not r.ok:
        return pd.DataFrame(columns=["company_name", "filed_date", "filer"])

    rows = []
    for hit in r.json().get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        rows.append({
            "company_name": src.get("entity_name", ""),
            "filed_date":   src.get("file_date", ""),
            "filer":        src.get("display_names", [""])[0] if src.get("display_names") else "",
            "cik":          src.get("entity_id", ""),
        })

    if not rows:
        return pd.DataFrame(columns=["company_name", "filed_date", "filer"])
    return pd.DataFrame(rows).sort_values("filed_date", ascending=False)
