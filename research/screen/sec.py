"""SEC data: universe loading and XBRL frames-API fundamentals."""
from __future__ import annotations

import re
import sys
import time
from typing import Any

import pandas as pd
import requests

from . import cache

EDGAR_UA = "hyperstink-research/0.1 research@example.com"
_EDGAR_BASE = "https://data.sec.gov"
_FRAMES_BASE = f"{_EDGAR_BASE}/api/xbrl/frames"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": EDGAR_UA, "Accept-Encoding": "gzip, deflate"})

# Rate-limit: SEC fair-access policy ≤ 10 req/s; stay at ~8
_REQ_INTERVAL = 0.13  # seconds between requests
_last_req: float = 0.0


def _get(url: str, timeout: int = 30) -> requests.Response:
    global _last_req
    elapsed = time.monotonic() - _last_req
    if elapsed < _REQ_INTERVAL:
        time.sleep(_REQ_INTERVAL - elapsed)
    for attempt in range(4):
        try:
            r = _SESSION.get(url, timeout=timeout)
            _last_req = time.monotonic()
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  429 from SEC, waiting {wait}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            return r
        except requests.RequestException as e:
            time.sleep(2 ** attempt)
            if attempt == 3:
                raise SystemExit(f"SEC request failed: {url} ({e})")
    raise SystemExit(f"SEC repeated 429: {url}")


# ---------------------------------------------------------------------------
# Drop patterns for the universe
# ---------------------------------------------------------------------------
_DROP_SUFFIX = re.compile(
    r"\s+(ETF|FUND|TRUST|NOTES?|DEBENTURES?|WARRANTS?|UNITS?|RIGHTS?|"
    r"PREFERRED|PRF|PFD|BOND|NOTE|SPAC|ACQUISITION CORP\.?|BLANK CHECK)$",
    re.I,
)
_DROP_NAME = re.compile(
    r"\b(ETF|SPAC|blank\s+check|acquisition\s+corp|special\s+purpose\s+acquisition)\b",
    re.I,
)
_ADR_SUFFIX = re.compile(r"\s+(ADR|ADS)$", re.I)
_TICKER_SUFFIX = re.compile(r"[^A-Z]")  # clean tickers should be all alpha; skip if suffix chars

VALID_EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE MKT", "NASDAQ"}


def load_universe(refresh: bool = False) -> pd.DataFrame:
    """Return universe DataFrame: cik, ticker, name, exchange.

    Filters: NYSE/Nasdaq/NYSE American only, drops ETFs, SPACs, ADRs, warrant/unit tickers.
    Cached for 7 days.
    """
    key = "universe"
    if not refresh:
        cached = cache.load(key)
        if cached:
            return pd.DataFrame(cached)
    if refresh:
        cache.invalidate(key)

    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    r = _get(url, timeout=60)
    r.raise_for_status()
    raw = r.json()

    rows = []
    for entry in raw.get("data", []):
        cik, name, ticker, exchange = entry
        if exchange not in VALID_EXCHANGES:
            continue
        # Drop tickers with non-alpha suffixes (warrants: ACMRW, units: ACMRU, etc.)
        if not ticker.replace("-", "").isalpha():
            continue
        if len(ticker) > 5:
            continue
        if _DROP_SUFFIX.search(name) or _DROP_NAME.search(name) or _ADR_SUFFIX.search(name):
            continue
        rows.append({"cik": int(cik), "ticker": ticker.upper(), "name": name, "exchange": exchange})

    df = pd.DataFrame(rows).drop_duplicates("cik")
    cache.save(key, df.to_dict("records"))
    print(f"Universe: {len(df)} companies on NYSE/Nasdaq after filtering", file=sys.stderr)
    return df


# ---------------------------------------------------------------------------
# XBRL concepts to fetch
# ---------------------------------------------------------------------------
# Format: (canonical_key, [fallback_concept_tags], period_type)
# period_type: "annual" = CY{year}, "instant" = CY{year}Q4I
CONCEPTS: list[tuple[str, list[str], str]] = [
    ("revenue",   ["Revenues",
                   "RevenueFromContractWithCustomerExcludingAssessedTax",
                   "SalesRevenueNet"],                            "annual"),
    ("op_income", ["OperatingIncomeLoss"],                        "annual"),
    ("net_income",["NetIncomeLoss"],                              "annual"),
    ("ocf",       ["NetCashProvidedByUsedInOperatingActivities"], "annual"),
    ("capex",     ["PaymentsToAcquirePropertyPlantAndEquipment"], "annual"),
    # Balance sheet — instant
    ("equity",    ["StockholdersEquity",
                   "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
                                                                  "instant"),
    ("cash",      ["CashAndCashEquivalentsAtCarryingValue",
                   "CashCashEquivalentsAndShortTermInvestments"], "instant"),
    # Debt pieces — combined later via compute_debt()
    ("lt_debt",   ["LongTermDebt"],                              "instant"),
    ("lt_debt_nc",["LongTermDebtNoncurrent"],                    "instant"),
    ("lt_debt_c", ["LongTermDebtCurrent"],                       "instant"),
    ("st_debt",   ["ShortTermBorrowings", "LineOfCredit",
                   "CommercialPaper"],                            "instant"),
    # Shares — dei taxonomy
    ("shares",    ["EntityCommonStockSharesOutstanding"],         "instant"),
]

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def _frames_url(tag: str, period: str) -> str:
    if tag.startswith("dei/"):
        return f"{_FRAMES_BASE}/{tag}/shares/{period}.json"
    return f"{_FRAMES_BASE}/us-gaap/{tag}/USD/{period}.json"


def parse_frames_response(data: dict) -> dict[int, float]:
    """Extract {cik: val} from a frames API JSON response."""
    return {int(row["cik"]): float(row["val"]) for row in data.get("data", []) or []}


def _fetch_frames(tag: str, period: str) -> dict[int, float]:
    url = _frames_url(tag, period)
    r = _get(url, timeout=45)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return parse_frames_response(r.json())


def _period_str(year: int, period_type: str) -> str:
    if period_type == "annual":
        return f"CY{year}"
    return f"CY{year}Q4I"


def build_fundamentals(
    target_ciks: set[int] | None = None,
    years: list[int] | None = None,
    refresh: bool = False,
) -> dict[str, dict[int, dict[int, float]]]:
    """Fetch all XBRL frames and return nested dict: key → year → {cik: val}.

    Results are cached per (key, year) for 7 days.
    target_ciks: if given, restrict to these CIKs (reduces memory).
    """
    if years is None:
        years = YEARS

    result: dict[str, dict[int, dict[int, float]]] = {}

    for key, tags, period_type in CONCEPTS:
        result[key] = {}
        for year in years:
            period = _period_str(year, period_type)
            cache_key = f"frames_{key}_{period}"
            if not refresh:
                cached = cache.load(cache_key)
                if cached is not None:
                    vals = {int(k): float(v) for k, v in cached.items()}
                    result[key][year] = vals
                    if target_ciks:
                        result[key][year] = {c: v for c, v in vals.items() if c in target_ciks}
                    continue
            if refresh:
                cache.invalidate(cache_key)

            # Merge all fallback tags: later tags fill gaps left by earlier ones.
            # This handles companies that report under different US-GAAP tag names.
            vals: dict[int, float] = {}
            for tag in tags:
                raw = _fetch_frames(
                    f"dei/{tag}" if tag == "EntityCommonStockSharesOutstanding" else tag,
                    period,
                )
                # Only fill gaps — first tag that reports a CIK wins for that CIK
                for cik_id, val in raw.items():
                    if cik_id not in vals:
                        vals[cik_id] = val

            # Cache the full universe values; store only target CIKs in memory
            cache.save(cache_key, {str(k): v for k, v in vals.items()})
            if target_ciks:
                vals = {c: v for c, v in vals.items() if c in target_ciks}
            result[key][year] = vals

    return result


def get_sic_codes(ciks: list[int], refresh: bool = False) -> dict[int, int]:
    """Fetch SIC code for each CIK from the submissions endpoint. Cached 7 days."""
    key = "sic_codes"
    if not refresh:
        cached = cache.load(key)
        if cached:
            return {int(k): int(v) for k, v in cached.items()}

    sic_map: dict[int, int] = {}
    for i, cik in enumerate(ciks):
        url = f"{_EDGAR_BASE}/submissions/CIK{cik:010d}.json"
        try:
            r = _get(url, timeout=20)
            if r.ok:
                sic_map[cik] = int(r.json().get("sic", 0) or 0)
        except Exception:
            pass
        if i % 100 == 0 and i:
            print(f"  SIC lookup: {i}/{len(ciks)}…", file=sys.stderr)

    cache.save(key, {str(k): v for k, v in sic_map.items()})
    return sic_map
