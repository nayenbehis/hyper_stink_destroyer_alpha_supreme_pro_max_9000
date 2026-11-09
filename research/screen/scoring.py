"""Cheapness, quality, and neglect scoring (0–100 each, percentile-rank based)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _pct_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Percentile rank 0–100. NaNs score 50 (median) so they don't sink a company."""
    median = series.median()
    fill   = median if not pd.isna(median) else 0.0
    filled = series.fillna(fill)
    ranked = filled.rank(pct=True, ascending=ascending, method="average")
    return (ranked * 100).clip(0, 100)


def score_cheapness(df: pd.DataFrame) -> pd.Series:
    """Score cheapness 0–100.

    Components (equal weight, then averaged):
    - FCF yield (higher = cheaper)
    - EV/OpIncome (lower = cheaper)
    - Price-to-book (lower = cheaper)
    - % below 5-yr high (higher = cheaper)
    """
    components = []

    if "fcf_yield" in df.columns:
        components.append(_pct_rank(df["fcf_yield"], ascending=True))   # higher yield → higher rank
    if "ev_oi" in df.columns:
        components.append(_pct_rank(df["ev_oi"], ascending=False))       # lower EV/OI → higher rank
    if "pb" in df.columns:
        components.append(_pct_rank(df["pb"], ascending=False))          # lower P/B → higher rank
    if "pct_below_hi" in df.columns:
        components.append(_pct_rank(df["pct_below_hi"], ascending=True)) # more below high → higher rank

    if not components:
        return pd.Series(50.0, index=df.index)
    return pd.concat(components, axis=1).mean(axis=1).clip(0, 100)


def score_quality(df: pd.DataFrame) -> pd.Series:
    """Score quality 0–100.

    Components:
    - FCF consistency (higher = better)
    - Operating margin (higher = better)
    - Net debt / EBIT (lower = better; negative = net cash, scores 100)
    """
    components = []

    if "fcf_consistency" in df.columns:
        components.append(_pct_rank(df["fcf_consistency"], ascending=True))
    if "op_margin" in df.columns:
        components.append(_pct_rank(df["op_margin"], ascending=True))
    if "nd_ebit" in df.columns:
        # Flip: lower (less debt) → higher score; cap at ±5 so net-cash isn't wild outlier
        capped = df["nd_ebit"].clip(-5, 10)
        components.append(_pct_rank(capped, ascending=False))

    if not components:
        return pd.Series(50.0, index=df.index)
    return pd.concat(components, axis=1).mean(axis=1).clip(0, 100)


def score_neglect(df: pd.DataFrame) -> pd.Series:
    """Score neglect 0–100 (higher = more ignored).

    Components:
    - analyst count (fewer = more ignored) — missing fills with peer median
    - institutional ownership % (lower = more ignored) — missing fills with peer median
    - market cap (smaller = more ignored)

    Note: yfinance .news is unreliable and has been removed from this score.
    """
    components = []

    if "analysts" in df.columns:
        # Fill NaN with group median — a Yahoo outage shouldn't inflate neglect score
        med = df["analysts"].median()
        fill = med if not pd.isna(med) else 0.0
        components.append(_pct_rank(df["analysts"].fillna(fill), ascending=False))
    if "inst_pct" in df.columns:
        med = df["inst_pct"].median()
        fill = med if not pd.isna(med) else 0.5
        components.append(_pct_rank(df["inst_pct"].fillna(fill), ascending=False))
    if "market_cap" in df.columns:
        components.append(_pct_rank(df["market_cap"], ascending=False))

    if not components:
        return pd.Series(50.0, index=df.index)
    return pd.concat(components, axis=1).mean(axis=1).clip(0, 100)


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add score_cheapness and score_quality columns in place."""
    out = df.copy()
    out["score_cheap"] = score_cheapness(out)
    out["score_qual"]  = score_quality(out)
    out["score_cq"]    = (0.5 * out["score_cheap"] + 0.5 * out["score_qual"]).clip(0, 100)
    return out


def add_neglect_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["score_neglect"] = score_neglect(out)
    return out


def combine_scores(
    df: pd.DataFrame,
    w_cheap: float = 0.40,
    w_qual: float  = 0.30,
    w_neg: float   = 0.30,
) -> pd.DataFrame:
    out = df.copy()
    if "score_neglect" not in out.columns:
        out["score_neglect"] = 50.0
    out["score"] = (
        w_cheap * out["score_cheap"]
        + w_qual  * out["score_qual"]
        + w_neg   * out["score_neglect"]
    ).clip(0, 100)
    return out.sort_values("score", ascending=False)
