"""Quality, size, and tradability filters for the screener."""
from __future__ import annotations

import re

import pandas as pd

# SIC 6000–6999: Finance, Insurance, Real Estate
_FIN_SIC_RANGE = range(6000, 7000)

# Name-based heuristic for financial companies when SIC not available
_FINANCIAL_NAME = re.compile(
    r"\b(bank|bancorp|banc|bancshares|financial\s+corp|financial\s+group|"
    r"insurance|insurer|insur(?:ance|ers)|reit|mortgage|savings\s+bank|"
    r"thrift|federal\s+savings|asset\s+management|investment\s+trust|"
    r"capital\s+corp|mutual\s+savings|credit\s+corp)\b",
    re.I,
)

# SIC descriptions for major sectors (used when SIC map is populated)
_SIC_SECTORS: dict[tuple[int, int], str] = {
    (100,  999):  "Mining",
    (1000, 1499): "Mining",
    (1500, 1799): "Construction",
    (2000, 3999): "Manufacturing",
    (4000, 4999): "Transportation/Utilities",
    (5000, 5199): "Wholesale",
    (5200, 5999): "Retail",
    (6000, 6499): "Finance/Insurance",
    (6500, 6799): "Real Estate",
    (7000, 7399): "Services",
    (7400, 8099): "Services",
    (8100, 8999): "Services",
    (9000, 9999): "Public Admin",
}


def is_financial_sic(sic: int | None) -> bool:
    """Return True if the SIC code falls in the 6000-6999 Finance/Insurance/RE range."""
    if sic is None:
        return False
    return 6000 <= sic < 7000


def is_financial_name(name: str) -> bool:
    """Heuristic: flag likely financial companies by name when SIC is unavailable."""
    return bool(_FINANCIAL_NAME.search(name))


def sic_to_sector(sic: int | None) -> str:
    if sic is None:
        return "Unknown"
    for (lo, hi), sector in _SIC_SECTORS.items():
        if lo <= sic <= hi:
            return sector
    return "Other"


def apply_all(
    df: pd.DataFrame,
    min_cap: float = 200e6,
    max_cap: float = 5e9,
    min_adv: float = 500e3,
    min_data_years: int = 5,
    max_nd_ebit: float = 3.0,
    min_ocf_pos: int = 4,
    min_fcf_pos: int = 3,
    max_rev_decline: float = -0.05,   # CAGR must be > this
    include_financials: bool = False,
    sic_map: dict[int, int] | None = None,
) -> pd.DataFrame:
    """Apply all quality, size, and tradability filters. Returns the surviving subset."""
    out = df.copy()

    # Tag financials
    if sic_map:
        out["_is_fin"] = out["cik"].map(lambda c: is_financial_sic(sic_map.get(c)))
    else:
        out["_is_fin"] = out["name"].apply(is_financial_name)

    if not include_financials:
        before = len(out)
        out = out[~out["_is_fin"]]
        _log(f"Financial exclusion: {before - len(out)} dropped, {len(out)} remain")

    # Size
    out = _filter(out, out["market_cap"].between(min_cap, max_cap), "market cap")

    # Tradability
    out = _filter(out, out["adv"].fillna(0) >= min_adv, "avg daily volume")

    # Data completeness
    out = _filter(out, out["data_years"] >= min_data_years, f"≥{min_data_years} yr data")

    # OCF positivity
    out = _filter(out, out["ocf_pos_years"] >= min_ocf_pos, f"OCF+ ≥{min_ocf_pos}/5 yrs")

    # FCF consistency
    out = _filter(out, out["fcf_consistency"] >= min_fcf_pos, f"FCF+ ≥{min_fcf_pos}/5 yrs")

    # Revenue trend
    out = _filter(
        out,
        out["rev_cagr"].isna() | (out["rev_cagr"] > max_rev_decline),
        "revenue trend",
    )

    # Balance sheet: (debt−cash)/avg_oi < 3, or if net_debt <= 0 (net cash), always passes
    if "nd_ebit" in out.columns:
        passes_debt = out["nd_ebit"].isna() | (out["nd_ebit"] <= max_nd_ebit) | (out["net_debt"] <= 0)
        out = _filter(out, passes_debt, "debt/EBIT ≤ 3")

    out = out.drop(columns=["_is_fin"], errors="ignore")
    return out


# ---------------------------------------------------------------------------
# Cyclical industry flagging (SIC-based and name-based)
# ---------------------------------------------------------------------------

# SIC ranges for sectors known for peak-earnings risk
_CYCLICAL_SIC: list[tuple[int, int, str]] = [
    (1040, 1049, "gold/silver mining"),
    (1090, 1099, "metal mining"),
    (1200, 1299, "coal mining"),
    (1311, 1311, "crude oil & gas exploration"),
    (1381, 1389, "oil & gas field services"),
    (2870, 2879, "fertilizers/agriculture chemicals"),
    (4400, 4499, "water transportation / shipping"),
    (4412, 4412, "deep-sea shipping"),
    (5171, 5172, "petroleum wholesale"),
]

_CYCLICAL_NAME = re.compile(
    r"\b(coal|fertilizer|potash|nitrogen|ammonia|phosphate|"
    r"shipping|drybulk|dry\s+bulk|tanker|containership|"
    r"crude\s+oil|oil\s+&\s+gas|oil\s+and\s+gas|"
    r"egg|poultry|broiler|hog|pork)\b",
    re.I,
)


def flag_cyclicals(df: pd.DataFrame, sic_map: dict[int, int] | None = None) -> pd.DataFrame:
    """Add a 'cyclical' bool column and append a warning to the warnings column."""
    out = df.copy()

    def _is_cyclical_sic(cik: int) -> bool:
        sic = sic_map.get(int(cik)) if sic_map else None
        if sic is None:
            return False
        return any(lo <= sic <= hi for lo, hi, _ in _CYCLICAL_SIC)

    def _cyclical_label_sic(cik: int) -> str:
        sic = sic_map.get(int(cik)) if sic_map else None
        if sic is None:
            return ""
        for lo, hi, label in _CYCLICAL_SIC:
            if lo <= sic <= hi:
                return label
        return ""

    if sic_map:
        out["cyclical"] = out["cik"].apply(_is_cyclical_sic)
        label_col = out["cik"].apply(_cyclical_label_sic)
    else:
        out["cyclical"] = out["name"].apply(lambda n: bool(_CYCLICAL_NAME.search(n)))
        label_col = out["name"].apply(
            lambda n: _CYCLICAL_NAME.search(n).group(0) if _CYCLICAL_NAME.search(n) else ""
        )

    # Append warning for cyclical companies
    def _add_warn(row):
        label = label_col.loc[row.name]
        if not label:
            return row["warnings"]
        note = f"earnings may be at a peak ({label})"
        existing = str(row["warnings"] or "").strip()
        return f"{existing}; {note}" if existing else note

    out["warnings"] = out.apply(_add_warn, axis=1)
    return out


def _filter(df: pd.DataFrame, mask: pd.Series, label: str) -> pd.DataFrame:
    before = len(df)
    out = df[mask]
    dropped = before - len(out)
    if dropped:
        import sys
        print(f"  Filter '{label}': dropped {dropped}, {len(out)} remain", file=sys.stderr)
    return out


def _log(msg: str) -> None:
    import sys
    print(f"  {msg}", file=sys.stderr)
