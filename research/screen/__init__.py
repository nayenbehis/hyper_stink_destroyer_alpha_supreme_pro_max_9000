"""research.screen — code-only stock screener.

Usage:
    python3 cli.py screen [--top N] [--refresh] [--lane insiders|spinoffs|activists]
    hyperstink screen ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cache, filters, metrics, output, scoring
from .prices import fetch_prices, fetch_neglect_info
from .sec    import build_fundamentals, get_sic_codes, load_universe

_NEGLECT_TOP_N = 150   # how many top-score_cq stocks to enrich with Yahoo info


def screen_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hyperstink screen",
        description="Find good, cheap, ignored U.S. small/mid-cap stocks.",
    )
    p.add_argument("--top",     type=int,   default=25, help="rows to show (default 25)")
    p.add_argument("--refresh", action="store_true",    help="bypass 7-day cache")
    p.add_argument(
        "--lane", choices=["insiders", "spinoffs", "activists"],
        help="Phase-2 special scan instead of main screen",
    )
    p.add_argument("--out",     default="",             help="override output directory")
    p.add_argument(
        "--include-financials", action="store_true",
        help="keep banks, insurers, REITs in results",
    )
    p.add_argument(
        "--min-cap",  type=float, default=200e6, help="min market cap (default 200M)")
    p.add_argument(
        "--max-cap",  type=float, default=5e9,   help="max market cap (default 5B)")
    a = p.parse_args(argv)

    # --- Phase-2 lanes ---
    if a.lane:
        return _run_lane(a)

    # --- Main screen ---
    print("Loading universe…", file=sys.stderr)
    universe = load_universe(refresh=a.refresh)
    print(f"Universe: {len(universe)} companies", file=sys.stderr)

    target_ciks = set(universe["cik"].tolist())

    print("Fetching XBRL fundamentals…", file=sys.stderr)
    frames = build_fundamentals(target_ciks=target_ciks, refresh=a.refresh)

    print("Fetching prices (batch OHLCV)…", file=sys.stderr)
    tickers = universe["ticker"].tolist()
    price_df = fetch_prices(tickers, refresh=a.refresh)

    print("Building metrics…", file=sys.stderr)
    df = metrics.build_metrics_df(frames, universe, price_df)
    print(f"Metrics built: {len(df)} companies with enough data", file=sys.stderr)

    # Drop rows with no EV/OI — these are financials/banks that slipped past the
    # name filter (no EBIT-style income; keeping them would inflate neglect scores).
    before_drop = len(df)
    df = df[df["ev_oi"].notna()]
    if len(df) < before_drop:
        print(f"  Dropped {before_drop - len(df)} rows with missing EV/OI (likely financials)", file=sys.stderr)

    # SIC codes for the surviving subset (financial and cyclical filters)
    print("Fetching SIC codes…", file=sys.stderr)
    survivor_ciks = df["cik"].astype(int).tolist() if "cik" in df.columns else []
    sic_map = get_sic_codes(survivor_ciks, refresh=a.refresh) if survivor_ciks else {}

    print("Applying filters…", file=sys.stderr)
    filtered = filters.apply_all(
        df,
        min_cap=a.min_cap,
        max_cap=a.max_cap,
        include_financials=a.include_financials,
        sic_map=sic_map,
    )
    print(f"After filters: {len(filtered)} companies", file=sys.stderr)

    if filtered.empty:
        print("No companies survived the filters. Try --include-financials or wider cap range.")
        return 1

    # Phase-1 scoring (cheapness + quality) to pick which stocks get the expensive
    # Yahoo per-ticker info call.
    print("Phase-1 scoring (cheapness + quality)…", file=sys.stderr)
    scored1 = scoring.add_scores(filtered)
    top_tickers = (
        scored1.sort_values("score_cq", ascending=False)
               .head(_NEGLECT_TOP_N)
               .index.tolist()
    )

    print(f"Fetching neglect info for top {len(top_tickers)} stocks…", file=sys.stderr)
    neglect_df = fetch_neglect_info(top_tickers, refresh=a.refresh)

    # Merge Yahoo info into scored1
    scored1 = _merge_neglect(scored1, neglect_df, a.min_cap, a.max_cap)

    # Flag cyclical industries
    scored1 = filters.flag_cyclicals(scored1, sic_map=sic_map)

    # Final neglect scoring and combined score
    print("Scoring (neglect + combine)…", file=sys.stderr)
    scored = scoring.add_neglect_scores(scored1)
    scored = scoring.combine_scores(scored)

    # Output
    run_dir = output.make_run_dir("") if not a.out else Path(a.out)
    csv_path = output.write_csv(scored, run_dir)
    md_path  = output.write_markdown(scored, run_dir, top_n=50)

    output.print_results(scored, top_n=a.top)
    print(f"Results: {csv_path}")
    print(f"Report:  {md_path}")
    return 0


def _merge_neglect(df, neglect_df, min_cap: float, max_cap: float):
    """Merge Yahoo neglect info into df; recompute EV/ratios using Yahoo market cap."""
    import pandas as pd

    out = df.copy()

    for tkr in neglect_df.index:
        if tkr not in out.index:
            continue
        row = neglect_df.loc[tkr]

        # Prefer Yahoo market cap (more current than SEC shares × close)
        yf_cap = row.get("market_cap_yf")
        if yf_cap and pd.notna(yf_cap) and float(yf_cap) > 0:
            out.at[tkr, "market_cap"] = float(yf_cap)
            # Recompute EV, ratios that depend on market cap
            net_debt = out.at[tkr, "net_debt"]
            ev = float(yf_cap) + (net_debt if pd.notna(net_debt) else 0.0)
            out.at[tkr, "ev"] = ev
            avg_fcf = out.at[tkr, "avg_fcf"]
            avg_oi  = out.at[tkr, "avg_oi"]
            out.at[tkr, "fcf_yield"] = float(avg_fcf) / float(yf_cap) if pd.notna(avg_fcf) and float(yf_cap) > 0 else out.at[tkr, "fcf_yield"]
            out.at[tkr, "ev_oi"]     = ev / float(avg_oi) if pd.notna(avg_oi) and float(avg_oi) > 0 and ev > 0 else out.at[tkr, "ev_oi"]

        # Merge analyst/institutional data
        for col in ("analysts", "inst_pct"):
            val = row.get(col)
            if val is not None and pd.notna(val):
                out.at[tkr, col] = float(val)

    # Re-apply cap filter now that we have better market_cap numbers
    before = len(out)
    out = out[out["market_cap"].between(min_cap, max_cap)]
    if len(out) < before:
        print(f"  Re-cap filter: dropped {before - len(out)} after Yahoo market cap update", file=sys.stderr)

    return out


def _run_lane(a: argparse.Namespace) -> int:
    from . import lanes

    print(f"Running '{a.lane}' lane…", file=sys.stderr)
    if a.lane == "insiders":
        universe = load_universe(refresh=a.refresh)
        df = lanes.run_insiders_lane(universe)
    elif a.lane == "spinoffs":
        df = lanes.run_spinoffs_lane()
    else:  # activists
        df = lanes.run_activists_lane()

    if df.empty:
        print("No results for this lane.")
        return 0

    run_dir = output.make_run_dir(a.lane) if not a.out else Path(a.out)
    csv_path = run_dir / f"{a.lane}.csv"
    df.to_csv(csv_path, index=False)

    print(df.to_string(index=False))
    print(f"\nSaved: {csv_path}")
    return 0
