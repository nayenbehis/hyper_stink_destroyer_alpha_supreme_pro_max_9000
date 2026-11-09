"""SEC EDGAR fetcher — free, no API key required."""

from __future__ import annotations

import requests

_HEADERS = {"User-Agent": "hyper-stink-destroyer nayen.ayala1@gmail.com"}
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms={form}"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _get_cik(ticker: str) -> str | None:
    """Look up the CIK number for a ticker."""
    resp = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=10)
    data = resp.json()
    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry["ticker"] == ticker_upper:
            return str(entry["cik_str"]).zfill(10)
    return None


def get_recent_filings(ticker: str, form_type: str = "10-K", limit: int = 5) -> list[dict]:
    """Return recent filings metadata for a ticker from EDGAR."""
    cik = _get_cik(ticker)
    if not cik:
        return []

    url = _SUBMISSIONS_URL.format(cik=cik)
    data = requests.get(url, headers=_HEADERS, timeout=10).json()

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    descriptions = filings.get("primaryDocument", [])

    results = []
    for form, date, acc, doc in zip(forms, dates, accessions, descriptions):
        if form == form_type:
            acc_clean = acc.replace("-", "")
            results.append({
                "form": form,
                "date": date,
                "accession": acc,
                "url": f"https://www.sec.gov/Archives/edgar/full-index/{acc_clean[:4]}/{acc_clean[4:6]}/{acc_clean[6:8]}/{acc}/{doc}",
                "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=10",
            })
            if len(results) >= limit:
                break

    return results


def _parse_form4(accession: str, cik: str) -> dict:
    """Fetch and parse a Form 4 XML to extract insider name and transaction details."""
    import xml.etree.ElementTree as ET
    acc_clean = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}"
    # First try known filenames, then fall back to parsing the filing index
    resp = None
    for fname in ("form4.xml", "primary_doc.xml", "doc4.xml", "xslF345X03/primary_doc.xml"):
        r = requests.get(f"{base}/{fname}", headers=_HEADERS, timeout=8)
        if r.status_code == 200 and b"<ownershipDocument" in r.content:
            resp = r
            break

    if resp is None:
        # Parse the filing index to find the actual XML filename
        try:
            idx = requests.get(f"{base}/", headers=_HEADERS, timeout=8)
            import re
            for fname in re.findall(r'href="([^"]+\.xml)"', idx.text):
                fname = fname.split("/")[-1]
                r = requests.get(f"{base}/{fname}", headers=_HEADERS, timeout=8)
                if r.status_code == 200 and b"<ownershipDocument" in r.content:
                    resp = r
                    break
        except Exception:
            pass
    try:
        if resp is None:
            return {}
        root = ET.fromstring(resp.content)
        name = ""
        owner = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
        if owner is not None:
            name = owner.text or ""
        title = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
        title_str = title.text if title is not None else ""
        is_director = root.find(".//reportingOwner/reportingOwnerRelationship/isDirector")
        is_officer = root.find(".//reportingOwner/reportingOwnerRelationship/isOfficer")
        role = title_str or ("Director" if is_director is not None and is_director.text == "1" else "Insider")

        transactions = []
        for tx in root.findall(".//nonDerivativeTransaction"):
            code_el = tx.find(".//transactionCoding/transactionCode")
            shares_el = tx.find(".//transactionAmounts/transactionShares/value")
            price_el = tx.find(".//transactionAmounts/transactionPricePerShare/value")
            code = code_el.text if code_el is not None else ""
            shares = shares_el.text if shares_el is not None else ""
            price = price_el.text if price_el is not None else ""
            if code not in ("P", "S"):
                continue
            action = "BUY" if code == "P" else "SELL"
            if shares and float(shares) > 0:
                transactions.append({"action": action, "shares": shares, "price": price})

        return {"name": name, "role": role, "transactions": transactions}
    except Exception:
        return {}


def get_insider_trades(ticker: str, limit: int = 10) -> list[dict]:
    """Return recent Form 4 insider trade filings with parsed details."""
    cik = _get_cik(ticker)
    if not cik:
        return []

    url = _SUBMISSIONS_URL.format(cik=cik)
    data = requests.get(url, headers=_HEADERS, timeout=10).json()
    filings = data.get("filings", {}).get("recent", {})

    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])

    results = []
    for form, date, acc in zip(forms, dates, accessions):
        if form == "4":
            details = _parse_form4(acc, cik)
            results.append({
                "form": "4",
                "date": date,
                "accession": acc,
                "name": details.get("name", "Unknown"),
                "role": details.get("role", ""),
                "transactions": details.get("transactions", []),
                "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10",
            })
            if len(results) >= limit:
                break

    return results


_ANNUAL_METRIC_TAGS: dict[str, dict] = {
    "revenue":            {"unit": "USD",        "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet", "NetRevenues", "TotalRevenues", "SalesRevenueServicesNet"]},
    "gross_profit":       {"unit": "USD",        "tags": ["GrossProfit"]},
    "operating_income":   {"unit": "USD",        "tags": ["OperatingIncomeLoss"]},
    "net_income":         {"unit": "USD",        "tags": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]},
    "diluted_eps":        {"unit": "USD/shares", "tags": ["EarningsPerShareDiluted"]},
    "diluted_shares":     {"unit": "shares",     "tags": ["WeightedAverageNumberOfDilutedSharesOutstanding"]},
    "basic_shares":       {"unit": "shares",     "tags": ["WeightedAverageNumberOfSharesOutstandingBasic"]},
    "operating_cash_flow":{"unit": "USD",        "tags": ["NetCashProvidedByUsedInOperatingActivities"]},
    "capex":              {"unit": "USD",        "tags": ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpendituresIncurringObligation", "PaymentsForCapitalImprovements"]},
    "sbc":                {"unit": "USD",        "tags": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]},
    # Cash only — short_term_investments tracked separately to avoid confusion
    "cash":               {"unit": "USD",        "tags": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"]},
    "short_term_investments": {"unit": "USD",   "tags": ["ShortTermInvestments", "AvailableForSaleSecuritiesCurrent", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]},
    # Prefer noncurrent-only tag first to avoid including the current portion twice
    "long_term_debt":     {"unit": "USD",        "tags": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligation"]},
    "short_term_debt":    {"unit": "USD",        "tags": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "NotesAndLoansPayableCurrent"]},
    "preferred_stock":    {"unit": "USD",        "tags": ["TemporaryEquityCarryingAmountAttributableToParent", "TemporaryEquityCarryingAmount", "PreferredStockValue", "RedeemableNoncontrollingInterestEquityCarryingAmount"]},
    "dividends_paid":     {"unit": "USD",        "tags": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]},
    "buybacks":           {"unit": "USD",        "tags": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"]},
}

# Tags used for quarterly balance sheet snapshot (instant values)
_BALANCE_SHEET_TAGS: dict[str, dict] = {
    "cash":                   {"unit": "USD",    "tags": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"]},
    "short_term_investments":  {"unit": "USD",   "tags": ["ShortTermInvestments", "AvailableForSaleSecuritiesCurrent", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]},
    "long_term_debt":          {"unit": "USD",   "tags": ["LongTermDebtNoncurrent", "LongTermDebt"]},
    "short_term_debt":         {"unit": "USD",   "tags": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"]},
    "preferred_stock":         {"unit": "USD",   "tags": ["TemporaryEquityCarryingAmountAttributableToParent", "TemporaryEquityCarryingAmount", "PreferredStockValue"]},
}

# P&L tags for quarterly history (YTD subtraction method)
_QUARTERLY_PL_TAGS: dict[str, dict] = {
    "revenue":             {"unit": "USD", "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]},
    "operating_income":    {"unit": "USD", "tags": ["OperatingIncomeLoss"]},
    "net_income":          {"unit": "USD", "tags": ["NetIncomeLoss"]},
    "operating_cash_flow": {"unit": "USD", "tags": ["NetCashProvidedByUsedInOperatingActivities"]},
    "capex":               {"unit": "USD", "tags": ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpendituresIncurringObligation"]},
}


def get_annual_history(ticker: str, years: int = 5) -> dict:
    """Multi-year annual financials from SEC EDGAR XBRL with yfinance fallback.

    Returns:
        years:        sorted list of FY integers
        data:         {year: {metric: {value, tag, filed, end, source}}}
        latest_fy_end: ISO date of most recent FY end found
        warnings:     list of human-readable warning strings
    """
    import pandas as pd
    import yfinance as yf

    result: dict = {"years": [], "data": {}, "latest_fy_end": "", "warnings": [], "current_shares_outstanding": None}

    # ── XBRL fetch ──────────────────────────────────────────────────────────
    us_gaap: dict = {}
    dei: dict = {}
    try:
        facts = get_company_facts(ticker)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        dei = facts.get("facts", {}).get("dei", {})
        if not us_gaap:
            result["warnings"].append("SEC XBRL: no us-gaap facts found")
    except Exception as e:
        result["warnings"].append(f"SEC XBRL fetch failed: {e}")

    def _xbrl_annual(tag_name: str, unit_key: str) -> dict:
        """Extract FY annual values for one tag, keeping most-recent filing per year.

        Accepts fp=='FY' entries, plus 10-K entries where fp is absent or empty
        (some filers omit fp on income-statement line items).
        """
        obs = us_gaap.get(tag_name, {}).get("units", {}).get(unit_key, [])
        by_fy: dict = {}
        for o in obs:
            if o.get("form") not in ("10-K", "20-F"):
                continue
            fp = o.get("fp") or ""
            # Accept explicit FY, or blank fp (some companies omit it on 10-Ks)
            if fp and fp != "FY":
                continue
            val = o.get("val")
            if val is None or str(val) == ".":
                continue
            # Use the end-date year as the bucket key — the fy field in EDGAR
            # marks comparative rows with the filing year, not their actual year.
            end = o.get("end", "")
            fy = int(end[:4]) if end else None
            if fy is None:
                continue
            existing = by_fy.get(fy)
            if existing is None or o.get("filed", "") > existing.get("filed", ""):
                by_fy[fy] = {
                    "value": float(val),
                    "tag": tag_name,
                    "filed": o.get("filed", ""),
                    "end": end,
                    "source": "sec",
                }
        return by_fy

    all_fys: set = set()
    for metric, cfg in _ANNUAL_METRIC_TAGS.items():
        merged: dict = {}
        for tag in cfg["tags"]:
            data = _xbrl_annual(tag, cfg["unit"])
            for fy, val in data.items():
                # prefer the entry with the most recent filing date
                if fy not in merged or val.get("filed", "") > merged[fy].get("filed", ""):
                    merged[fy] = val
        if merged:
            for fy, val in merged.items():
                result["data"].setdefault(fy, {})[metric] = val
            all_fys.update(merged.keys())

    # ── yfinance fallback for metrics still missing ──────────────────────────
    _YF_MAP = {
        "revenue":             ("financials",    "Total Revenue"),
        "gross_profit":        ("financials",    "Gross Profit"),
        "operating_income":    ("financials",    "Operating Income"),
        "net_income":          ("financials",    "Net Income"),
        "diluted_eps":         ("financials",    "Diluted EPS"),
        "operating_cash_flow": ("cashflow",      "Operating Cash Flow"),
        "capex":               ("cashflow",      "Capital Expenditure"),
        "sbc":                 ("cashflow",      "Stock Based Compensation"),
        "cash":                ("balance_sheet", "Cash And Cash Equivalents"),
        "long_term_debt":      ("balance_sheet", "Long Term Debt"),
        "short_term_debt":     ("balance_sheet", "Current Debt"),
    }
    missing = {m for m in _ANNUAL_METRIC_TAGS if not any(m in result["data"].get(fy, {}) for fy in all_fys)}
    if missing:
        try:
            t = yf.Ticker(ticker)
            stmts = {
                "financials":    t.financials,
                "cashflow":      t.cashflow,
                "balance_sheet": t.balance_sheet,
            }
            for metric in missing:
                if metric not in _YF_MAP:
                    continue
                stmt_key, row_name = _YF_MAP[metric]
                df = stmts.get(stmt_key)
                if df is None or df.empty or row_name not in df.index:
                    continue
                row = df.loc[row_name]
                for col in row.index:
                    try:
                        fy = col.year
                        val = float(row[col])
                        if pd.notna(val) and metric not in result["data"].get(fy, {}):
                            result["data"].setdefault(fy, {})[metric] = {
                                "value": val,
                                "tag": row_name,
                                "filed": "",
                                "end": str(col)[:10],
                                "source": "yfinance",
                            }
                            all_fys.add(fy)
                    except Exception:
                        pass
        except Exception as e:
            result["warnings"].append(f"yfinance fallback failed: {e}")

    # ── Finalise years ───────────────────────────────────────────────────────
    sorted_fys = sorted(all_fys)[-years:]
    result["years"] = sorted_fys

    # Latest FY end date
    ends = [
        result["data"][fy][m]["end"]
        for fy in sorted_fys
        for m in result["data"].get(fy, {})
        if result["data"][fy][m].get("end")
    ]
    result["latest_fy_end"] = max(ends) if ends else ""

    # ── Current shares outstanding from dei namespace ────────────────────────
    sh_obs = dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if sh_obs:
        recent = max(sh_obs, key=lambda x: x.get("filed", ""))
        result["current_shares_outstanding"] = int(recent.get("val", 0))

    return result


def get_quarterly_history(ticker: str) -> dict:
    """Last 4 fiscal quarters of P&L + TTM + latest balance sheet from EDGAR XBRL.

    Returns:
        quarters:      list of period_end ISO dates (sorted ascending, up to 4)
        data:          {period_end: {metric: value}}
        ttm:           {metric: ttm_value} — sum of last 4 quarters
        balance_sheet: {metric: {value, tag, end}, "period_end": str}
        current_shares: int | None  (dei:EntityCommonStockSharesOutstanding)
        warnings:      list[str]
    """
    result: dict = {
        "quarters": [],
        "data": {},
        "ttm": {},
        "balance_sheet": {},
        "current_shares": None,
        "warnings": [],
    }

    try:
        facts = get_company_facts(ticker)
    except Exception as e:
        result["warnings"].append(f"XBRL fetch failed: {e}")
        return result

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei     = facts.get("facts", {}).get("dei", {})

    # Current shares from dei
    sh_obs = dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if sh_obs:
        result["current_shares"] = int(max(sh_obs, key=lambda x: x.get("filed", "")).get("val", 0))

    # ── YTD observations keyed by (fy, fp) ──────────────────────────────────
    def _ytd(tag_name: str, unit_key: str) -> dict:
        obs = us_gaap.get(tag_name, {}).get("units", {}).get(unit_key, [])
        out: dict = {}
        for o in obs:
            if o.get("form") not in ("10-Q", "10-K", "20-F"):
                continue
            fp = o.get("fp") or ""
            if fp not in ("Q1", "Q2", "Q3", "FY"):
                continue
            val = o.get("val")
            if val is None:
                continue
            fy = o.get("fy")
            if fy is None:
                continue
            filed = o.get("filed", "")
            end = o.get("end", "")
            key = (fy, fp)
            # Within same (fy, fp), a 10-Q includes the current period AND a comparative
            # prior period. Sort by (filed, end) to always pick the current-period row.
            existing = out.get(key)
            if existing is None or (filed, end) > (existing["filed"], existing["end"]):
                out[key] = {"value": float(val), "end": end, "filed": filed}
        return out

    # ── Compute individual quarter values via YTD subtraction ───────────────
    all_ends: set = set()

    for metric, cfg in _QUARTERLY_PL_TAGS.items():
        merged: dict = {}
        for tag in cfg["tags"]:
            for k, v in _ytd(tag, cfg["unit"]).items():
                if k not in merged or v["filed"] > merged[k]["filed"]:
                    merged[k] = v
        if not merged:
            continue
        for fy in {k[0] for k in merged}:
            q1 = merged.get((fy, "Q1"))
            q2 = merged.get((fy, "Q2"))
            q3 = merged.get((fy, "Q3"))
            fy_v = merged.get((fy, "FY"))
            if q1:
                pe = q1["end"]
                result["data"].setdefault(pe, {})[metric] = q1["value"]
                all_ends.add(pe)
            if q2 and q1:
                pe = q2["end"]
                result["data"].setdefault(pe, {})[metric] = q2["value"] - q1["value"]
                all_ends.add(pe)
            if q3 and q2:
                pe = q3["end"]
                result["data"].setdefault(pe, {})[metric] = q3["value"] - q2["value"]
                all_ends.add(pe)
            if fy_v and q3:
                pe = fy_v["end"]
                result["data"].setdefault(pe, {})[metric] = fy_v["value"] - q3["value"]
                all_ends.add(pe)

    # Take last 4 periods that have at least 2 metrics populated
    valid = sorted(p for p in all_ends if len(result["data"].get(p, {})) >= 2)
    result["quarters"] = valid[-4:] if len(valid) >= 4 else valid

    # TTM = sum of last 4 quarters
    if len(result["quarters"]) == 4:
        for metric in _QUARTERLY_PL_TAGS:
            vals = [result["data"].get(p, {}).get(metric) for p in result["quarters"]]
            if all(v is not None for v in vals):
                result["ttm"][metric] = sum(vals)

    # ── Latest balance sheet (most-recent filing for each instant metric) ───
    def _latest_instant(tag_name: str, unit_key: str):
        obs = us_gaap.get(tag_name, {}).get("units", {}).get(unit_key, [])
        candidates = [o for o in obs if o.get("form") in ("10-Q", "10-K", "20-F")]
        if not candidates:
            return None, None
        # Sort by (filed, end) so that within a multi-period filing (comparative BS rows)
        # we pick the most recent period end, not a prior-year comparative row.
        best = max(candidates, key=lambda x: (x.get("filed", ""), x.get("end", "")))
        return best.get("val"), best.get("end"), best.get("form"), best.get("filed")

    bs_period = ""
    for metric, cfg in _BALANCE_SHEET_TAGS.items():
        for tag in cfg["tags"]:
            ret = _latest_instant(tag, cfg["unit"])
            val, end = ret[0], ret[1]
            if val is not None:
                result["balance_sheet"][metric] = {"value": float(val), "tag": tag, "end": end or ""}
                if end and end > bs_period:
                    bs_period = end
                break

    result["balance_sheet"]["period_end"] = bs_period
    return result


def get_company_facts(ticker: str) -> dict:
    """Return raw XBRL company facts (revenue, net income, etc.) from EDGAR."""
    cik = _get_cik(ticker)
    if not cik:
        return {}
    url = _COMPANY_FACTS_URL.format(cik=cik)
    return requests.get(url, headers=_HEADERS, timeout=15).json()


def get_key_metrics(ticker: str) -> dict:
    """Extract key financial metrics from XBRL facts: revenue, net income, assets."""
    facts = get_company_facts(ticker)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    def latest_annual(concept: str) -> float | None:
        entries = us_gaap.get(concept, {}).get("units", {}).get("USD", [])
        annual = [e for e in entries if e.get("form") in ("10-K", "20-F") and e.get("val")]
        if not annual:
            return None
        return sorted(annual, key=lambda x: x["end"])[-1]["val"]

    return {
        "revenue": latest_annual("Revenues") or latest_annual("RevenueFromContractWithCustomerExcludingAssessedTax"),
        "net_income": latest_annual("NetIncomeLoss"),
        "total_assets": latest_annual("Assets"),
        "total_liabilities": latest_annual("Liabilities"),
        "stockholders_equity": latest_annual("StockholdersEquity"),
        "operating_cash_flow": latest_annual("NetCashProvidedByUsedInOperatingActivities"),
    }
