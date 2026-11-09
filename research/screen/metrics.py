"""Pure metric computation functions for the screener.

All functions are pure (no I/O) and testable with fixtures.
"""
from __future__ import annotations

import math
import warnings
from typing import NamedTuple

import pandas as pd

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
_MIN_REVENUE_JUMP = 10.0  # flag revenue that grows/drops 10x YoY as suspicious


# ---------------------------------------------------------------------------
# Debt without double-counting
# ---------------------------------------------------------------------------

def compute_debt(
    lt_debt: float | None,       # LongTermDebt (total, includes current portion)
    lt_debt_nc: float | None,    # LongTermDebtNoncurrent
    lt_debt_c: float | None,     # LongTermDebtCurrent
    st_debt: float | None,       # ShortTermBorrowings / LineOfCredit
) -> float:
    """Return total debt without double-counting LongTermDebt vs its components.

    Priority: use LongTermDebt (total) if available, otherwise sum Noncurrent + Current.
    Add ShortTermBorrowings separately — it is distinct from LongTermDebt*.
    """
    if lt_debt is not None:
        lt = lt_debt
    elif lt_debt_nc is not None or lt_debt_c is not None:
        lt = (lt_debt_nc or 0.0) + (lt_debt_c or 0.0)
    else:
        lt = 0.0
    return lt + (st_debt or 0.0)


# ---------------------------------------------------------------------------
# FCF helpers
# ---------------------------------------------------------------------------

def compute_fcf(ocf: float | None, capex: float | None) -> float | None:
    """FCF = OCF − CapEx. CapEx is usually reported as a positive PaymentsToAcquire…."""
    if ocf is None:
        return None
    return ocf - (capex or 0.0)


def fcf_consistency(
    ocf_by_year: dict[int, float],
    capex_by_year: dict[int, float],
) -> int:
    """Count years where FCF (OCF − CapEx) was positive."""
    count = 0
    for year, ocf in ocf_by_year.items():
        fcf = compute_fcf(ocf, capex_by_year.get(year))
        if fcf is not None and fcf > 0:
            count += 1
    return count


def ocf_positive_years(ocf_by_year: dict[int, float]) -> int:
    return sum(1 for v in ocf_by_year.values() if v > 0)


# ---------------------------------------------------------------------------
# Revenue quality check
# ---------------------------------------------------------------------------

def revenue_flag(rev_by_year: dict[int, float]) -> str | None:
    """Return a warning string if revenue looks broken, else None."""
    vals = [rev_by_year[y] for y in sorted(rev_by_year) if rev_by_year[y] > 0]
    if len(vals) < 2:
        return None
    for a, b in zip(vals, vals[1:]):
        if b > 0 and a > 0 and (b / a > _MIN_REVENUE_JUMP or a / b > _MIN_REVENUE_JUMP):
            return f"revenue jump {a/1e6:.0f}M→{b/1e6:.0f}M (10x+)"
    return None


def revenue_cagr(rev_by_year: dict[int, float]) -> float | None:
    """Annualised revenue growth between first and last available years."""
    years = sorted(y for y, v in rev_by_year.items() if v and v > 0)
    if len(years) < 2:
        return None
    n = years[-1] - years[0]
    if n == 0:
        return None
    return (rev_by_year[years[-1]] / rev_by_year[years[0]]) ** (1 / n) - 1


# ---------------------------------------------------------------------------
# Build the flat metrics DataFrame from frames data + prices
# ---------------------------------------------------------------------------

def build_metrics_df(
    frames: dict[str, dict[int, dict[int, float]]],
    universe: pd.DataFrame,       # cik, ticker, name, exchange
    price_df: pd.DataFrame,       # indexed by ticker
) -> pd.DataFrame:
    """Merge frames data with price data into one flat DataFrame per company.

    Skips companies with:
    - fewer than 5 years of revenue data
    - suspicious revenue jumps (flags them in 'warnings' column but keeps them)
    - missing price or market cap
    """
    cik_to_ticker = dict(zip(universe["cik"], universe["ticker"]))
    cik_to_name   = dict(zip(universe["cik"], universe["name"]))
    all_ciks = set(universe["cik"])

    # Collect all CIKs that appear in revenue data
    rev_frames = frames.get("revenue", {})
    ciks_with_rev: dict[int, dict[int, float]] = {}
    for year, cik_vals in rev_frames.items():
        for cik, val in cik_vals.items():
            if cik in all_ciks:
                ciks_with_rev.setdefault(cik, {})[year] = val

    rows = []
    for cik, rev_by_year in ciks_with_rev.items():
        ticker = cik_to_ticker.get(cik)
        if not ticker:
            continue

        price_row = price_df.loc[ticker] if ticker in price_df.index else None
        price     = float(price_row["price"]) if price_row is not None and pd.notna(price_row.get("price")) else None

        # market_cap: prefer price_df column; fall back to price × SEC share count
        mkt_cap: float | None = None
        if price_row is not None and pd.notna(price_row.get("market_cap")):
            mkt_cap = float(price_row["market_cap"])

        if price is None:
            continue

        def _get(key: str, year: int) -> float | None:
            v = frames.get(key, {}).get(year, {}).get(cik)
            return float(v) if v is not None else None

        # Latest year with data
        years_with_rev = sorted(rev_by_year)
        if len(years_with_rev) < 5:
            continue

        latest_yr = years_with_rev[-1]

        # 5-year windows for consistency checks
        last5 = years_with_rev[-5:]
        ocf_by_year = {y: v for y in last5 if (v := _get("ocf", y)) is not None}
        cap_by_year = {y: v for y in last5 if (v := _get("capex", y)) is not None}

        # OCF + FCF consistency
        ocf_pos  = ocf_positive_years(ocf_by_year)
        fcf_cons = fcf_consistency(ocf_by_year, cap_by_year)

        # Revenue CAGR
        rev_cagr = revenue_cagr({y: rev_by_year[y] for y in last5 if y in rev_by_year})
        warn = revenue_flag(rev_by_year) or ""

        # Averages over last 3 years for ratios
        last3  = years_with_rev[-3:]
        avg_fcf = None
        fcf_vals = []
        for y in last3:
            ocf = _get("ocf", y)
            cpx = _get("capex", y)
            f = compute_fcf(ocf, cpx)
            if f is not None:
                fcf_vals.append(f)
        if fcf_vals:
            avg_fcf = sum(fcf_vals) / len(fcf_vals)

        avg_oi = None
        oi_vals = [v for y in last3 if (v := _get("op_income", y)) is not None]
        if oi_vals:
            avg_oi = sum(oi_vals) / len(oi_vals)

        # Latest balance-sheet items
        equity  = _get("equity", latest_yr)
        cash    = _get("cash", latest_yr)
        lt_d    = _get("lt_debt", latest_yr)
        lt_d_nc = _get("lt_debt_nc", latest_yr)
        lt_d_c  = _get("lt_debt_c", latest_yr)
        st_d    = _get("st_debt", latest_yr)
        total_debt = compute_debt(lt_d, lt_d_nc, lt_d_c, st_d)
        net_debt   = total_debt - (cash or 0.0)

        # Shares: prefer frames (more current), fall back to yfinance
        shares_xbrl = _get("shares", latest_yr)
        shares = shares_xbrl

        # Compute market_cap from SEC shares × price if Yahoo didn't provide it
        if mkt_cap is None and shares and price:
            mkt_cap = shares * price
        if mkt_cap is None or mkt_cap <= 0:
            continue

        # EV
        ev = mkt_cap + net_debt

        # Key ratios
        fcf_yield    = avg_fcf / mkt_cap if avg_fcf is not None and mkt_cap > 0 else None
        ev_oi        = ev / avg_oi if avg_oi and avg_oi > 0 and ev > 0 else None
        pb           = mkt_cap / equity if equity and equity > 0 else None
        hi_5yr       = float(price_row["hi_5yr"]) if price_row is not None and pd.notna(price_row.get("hi_5yr")) else None
        pct_below_hi = 1.0 - price / hi_5yr if hi_5yr and hi_5yr > 0 and price else None
        nd_ebit      = net_debt / avg_oi if avg_oi and avg_oi > 0 else None

        # Latest revenue
        latest_rev = rev_by_year.get(latest_yr)
        op_margin  = avg_oi / (latest_rev or 1) if avg_oi and latest_rev else None

        rows.append({
            "cik": cik, "ticker": ticker, "name": cik_to_name.get(cik, ""),
            "market_cap": mkt_cap, "price": price, "ev": ev,
            "shares": shares, "equity": equity, "cash": cash,
            "total_debt": total_debt, "net_debt": net_debt,
            "latest_rev": latest_rev, "avg_fcf": avg_fcf, "avg_oi": avg_oi,
            "fcf_yield": fcf_yield, "ev_oi": ev_oi, "pb": pb,
            "pct_below_hi": pct_below_hi, "nd_ebit": nd_ebit,
            "op_margin": op_margin,
            "ocf_pos_years": ocf_pos, "fcf_consistency": fcf_cons,
            "rev_cagr": rev_cagr, "data_years": len(years_with_rev),
            "adv": float(price_row["adv"]) if price_row is not None and pd.notna(price_row.get("adv")) else None,
            "warnings": warn,
        })

    return pd.DataFrame(rows).set_index("ticker")
