"""Insiders source: open-market trades from SEC Form 4 filings."""
from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET

from ._http import get, slug, table, emit

CODES = {
    "P": "open-market BUY",
    "S": "open-market SELL",
    "A": "grant/award",
    "M": "option exercise",
    "F": "tax withholding",
    "G": "gift",
    "D": "disposition to issuer",
    "C": "conversion",
    "X": "option exercise",
}


def cik_for(ticker: str) -> tuple[int, str]:
    r = get("https://www.sec.gov/files/company_tickers.json")
    for v in r.json().values():
        if v["ticker"].upper() == ticker.upper().replace(".", "-"):
            return int(v["cik_str"]), v["title"]
    raise SystemExit(f"ticker {ticker} not found in SEC list")


def parse_transactions(xml_bytes: bytes, filed_date: str) -> list[dict]:
    """Parse non-derivative transactions from Form 4 XML bytes.

    Returns a list of dicts with keys: filed, date, insider, title, code, type,
    acq_disp, shares, price, value_usd, filing (empty string — caller fills it).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName", "?")
    rel = root.find(".//reportingOwnerRelationship")
    title = ""
    if rel is not None:
        title = rel.findtext("officerTitle") or (
            "Director" if rel.findtext("isDirector") in ("1", "true") else ""
        )
    rows = []
    for t in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = t.findtext(".//transactionCoding/transactionCode", "")
        sh = float(t.findtext(".//transactionAmounts/transactionShares/value", "0") or 0)
        px = float(t.findtext(".//transactionAmounts/transactionPricePerShare/value", "0") or 0)
        ad = t.findtext(".//transactionAmounts/transactionAcquiredDisposedCode/value", "")
        rows.append({
            "filed": filed_date,
            "date": t.findtext(".//transactionDate/value", ""),
            "insider": owner,
            "title": title,
            "code": code,
            "type": CODES.get(code, code),
            "acq_disp": ad,
            "shares": int(sh),
            "price": round(px, 2),
            "value_usd": int(sh * px),
            "filing": "",
        })
    return rows


def build_insiders(a) -> tuple[str, list[dict]]:
    import re
    cik, name = cik_for(a.ticker)
    sub = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    rec = sub["filings"]["recent"]
    cutoff = dt.date.today() - dt.timedelta(days=a.days)
    rows = []
    for form, acc, fdate, doc in zip(
        rec["form"], rec["accessionNumber"], rec["filingDate"], rec["primaryDocument"]
    ):
        if form != "4" or dt.date.fromisoformat(fdate) < cutoff:
            continue
        xml_name = re.sub(r"^xsl[^/]*/", "", doc)
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{acc.replace('-', '')}/{xml_name}"
        )
        time.sleep(0.15)
        txns = parse_transactions(get(url).content, fdate)
        for txn in txns:
            txn["filing"] = url
        rows.extend(txns)

    buys = [r for r in rows if r["code"] == "P"]
    sells = [r for r in rows if r["code"] == "S"]
    md = (
        f"## Insider trades (SEC Form 4): {a.ticker.upper()} — {name}\n\n"
        f"Last {a.days} days: {len(rows)} transactions. "
        f"**Open-market buys: {len(buys)} (${sum(r['value_usd'] for r in buys):,})**, "
        f"open-market sells: {len(sells)} (${sum(r['value_usd'] for r in sells):,}).\n\n"
        "Open-market buys and sells (grants, exercises and tax withholding excluded):\n\n"
        + (
            table(
                sorted(buys + sells, key=lambda r: r["date"], reverse=True)[:25],
                ["date", "insider", "title", "type", "shares", "price", "value_usd"],
            )
            if buys or sells
            else "_none_"
        )
        + "\n\nWhy it matters: insiders sell for many reasons, but they buy with their own cash "
        "for one — they think the stock is cheap. Clusters of open-market buys are the signal."
    )
    return md, rows


def cmd_insiders(a) -> None:
    md, rows = build_insiders(a)
    emit(a, f"insiders_{a.ticker.lower()}", md, rows)


def add_subparser(sp) -> None:
    i = sp.add_parser("insiders", help="insider trades from SEC Form 4")
    i.add_argument("ticker")
    i.add_argument("--days", type=int, default=365)
    i.add_argument("--out", help="directory to save .md and .csv")
    i.set_defaults(fn=cmd_insiders)
