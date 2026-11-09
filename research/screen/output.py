"""CSV / Markdown / terminal output for the screener."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR  = _REPO_ROOT / "research_runs"

# Columns shown in terminal summary (in order)
_TERM_COLS = [
    "ticker", "name", "market_cap", "score",
    "score_cheap", "score_qual", "score_neglect",
    "fcf_yield", "ev_oi", "pb",
    "op_margin", "fcf_consistency", "nd_ebit",
    "data_years", "warnings",
]

# Columns in full CSV export
_CSV_COLS = [
    "cik", "ticker", "name", "market_cap", "price", "ev",
    "total_debt", "net_debt", "cash", "equity",
    "latest_rev", "avg_fcf", "avg_oi",
    "fcf_yield", "ev_oi", "pb", "pct_below_hi", "nd_ebit", "op_margin",
    "ocf_pos_years", "fcf_consistency", "rev_cagr", "data_years",
    "adv", "analysts", "inst_pct", "news_count",
    "score_cheap", "score_qual", "score_neglect", "score_cq", "score",
    "warnings",
]


def one_liner(row: pd.Series) -> str:
    """Format a single result row as a one-line string for console output."""
    cap = _fmt_m(row.get("market_cap"))
    fcf = f"{row['fcf_yield']*100:.1f}%" if pd.notna(row.get("fcf_yield")) else "—"
    ev_oi = f"{row['ev_oi']:.1f}x" if pd.notna(row.get("ev_oi")) else "—"
    score = f"{row.get('score', 0):.0f}"
    warn = f" ⚠ {row['warnings']}" if row.get("warnings") else ""
    return f"{row.name:<6}  {str(row.get('name',''))[:30]:<30}  {cap:>7}  score={score}  FCF={fcf}  EV/OI={ev_oi}{warn}"


def print_results(df: pd.DataFrame, top_n: int = 25) -> None:
    """Print top-N results to stdout."""
    subset = df.head(top_n)
    print(f"\n{'='*80}")
    print(f"  HYPERSTINK SCREEN — top {min(top_n, len(subset))} of {len(df)} qualifying companies")
    print(f"{'='*80}")
    for ticker, row in subset.iterrows():
        print(one_liner(row))
    if len(df) > top_n:
        print(f"\n  … and {len(df) - top_n} more (see CSV for full list)")
    print()


def make_run_dir(label: str = "") -> Path:
    today = date.today().isoformat()
    slug = f"screen_{today}" + (f"_{label}" if label else "")
    run_dir = _RUNS_DIR / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_csv(df: pd.DataFrame, run_dir: Path) -> Path:
    path = run_dir / "results.csv"
    cols = [c for c in _CSV_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in cols]
    df[cols + extra].to_csv(path)
    return path


def write_markdown(df: pd.DataFrame, run_dir: Path, top_n: int = 50) -> Path:
    path = run_dir / "SCREEN.md"
    today = date.today().isoformat()
    lines: list[str] = [
        f"# Hyperstink Screen — {today}\n",
        f"**Universe after filters:** {len(df)} companies\n",
        "",
        "| # | Ticker | Name | Mkt Cap | Score | FCF Yield | EV/OI | FCF Cons. | Warnings |",
        "|---|--------|------|---------|-------|-----------|-------|-----------|----------|",
    ]
    for i, (ticker, row) in enumerate(df.head(top_n).iterrows(), 1):
        cap   = _fmt_m(row.get("market_cap"))
        fcf   = f"{row['fcf_yield']*100:.1f}%" if pd.notna(row.get("fcf_yield")) else "—"
        ev_oi = f"{row['ev_oi']:.1f}x"          if pd.notna(row.get("ev_oi")) else "—"
        cons  = f"{int(row.get('fcf_consistency', 0))}/5"
        sc    = f"{row.get('score', 0):.0f}"
        warn  = str(row.get("warnings") or "").replace("|", "∣")
        name  = str(row.get("name", ""))[:35].replace("|", "∣")
        lines.append(f"| {i} | {ticker} | {name} | {cap} | {sc} | {fcf} | {ev_oi} | {cons} | {warn} |")
    if len(df) > top_n:
        lines.append(f"\n*…{len(df) - top_n} more in results.csv*")
    lines += [
        "",
        "## Scoring weights",
        "- Cheapness 40%: FCF yield, EV/EBIT, P/B, % below 5-yr high",
        "- Quality   30%: FCF consistency, operating margin, net debt/EBIT",
        "- Neglect   30%: analyst count, news count, institutional %, market cap",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _fmt_m(val) -> str:
    if val is None or (hasattr(val, "__float__") and pd.isna(val)):
        return "—"
    v = float(val)
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"
