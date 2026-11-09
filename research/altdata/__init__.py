"""research.altdata — public alternative-data sources wired into hyperstink."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import types
from pathlib import Path

from . import insiders, jobs, reddit, reviews, sitemap, wayback

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_out(ticker: str) -> str:
    return str(_REPO_ROOT / "research_runs" / f"{ticker}_altdata")


def cmd_all(a) -> None:
    """Run every applicable source and write a combined ALTDATA.md."""
    ticker = a.ticker.upper()
    out = a.out or _default_out(ticker)
    today = dt.date.today().isoformat()
    sections: list[str] = [f"# Alternative data: {ticker} — {today}\n"]

    def _run(label: str, fn, fake_args: dict) -> None:
        ns = types.SimpleNamespace(out=out, **fake_args)
        try:
            md, _ = fn(ns)
            sections.append(md)
        except SystemExit as e:
            sections.append(f"## {label}\n\n_skipped: {e}_\n")
        except Exception as e:
            sections.append(f"## {label}\n\n_error: {e}_\n")

    # insiders — always
    _run("Insiders", insiders.build_insiders, {"ticker": ticker, "days": 365})

    # sitemap — if --site and --match given
    if a.site and a.match:
        _run(
            "Sitemap",
            sitemap.build_sitemap,
            {
                "site": a.site, "match": a.match,
                "depth": None, "sitemap_url": None,
                "start": 2020, "every": 3, "max": 12, "pause": 1.0,
            },
        )

    # jobs — if --jobs-query given
    if a.jobs_query:
        _run(
            "Jobs",
            jobs.build_jobs,
            {
                "query": a.jobs_query, "company": None,
                "location": None, "sites": "indeed,zip_recruiter",
                "results": 150, "hours": 720, "country": "USA", "history": None,
            },
        )

    # reviews — if --app given
    if a.app_id:
        _run("Reviews", reviews.build_reviews, {"app_id": a.app_id, "count": 400})

    # reddit — using ticker as query; gracefully skips if unauthenticated
    _run(
        "Reddit",
        reddit.build_reddit,
        {
            "query": ticker,
            "subs": "stocks,investing,ValueInvesting,SecurityAnalysis,wallstreetbets",
            "pages": 1,
        },
    )

    from pathlib import Path as _Path
    import os
    os.makedirs(out, exist_ok=True)
    combined = "\n\n---\n\n".join(sections)
    dest = _Path(out) / "ALTDATA.md"
    dest.write_text(combined, encoding="utf-8")
    print(f"\nwrote {dest}")


def altdata_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hyperstink altdata",
        description="Pull public alternative-data trails for a stock pitch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = ap.add_subparsers(dest="cmd", required=True)

    wayback.add_subparser(sp)
    sitemap.add_subparser(sp)
    jobs.add_subparser(sp)
    insiders.add_subparser(sp)
    reddit.add_subparser(sp)
    reviews.add_subparser(sp)

    all_p = sp.add_parser(
        "all",
        help="run every applicable source and write a combined ALTDATA.md",
    )
    all_p.add_argument("ticker", help="ticker symbol, e.g. BFAM")
    all_p.add_argument("--site", help="company website for sitemap/wayback, e.g. https://www.brighthorizons.com")
    all_p.add_argument("--match", help="regex for sitemap URLs to count, e.g. '/daycare-centers/'")
    all_p.add_argument("--jobs-query", dest="jobs_query", help="search term for job postings, e.g. \"Bright Horizons\"")
    all_p.add_argument("--app", dest="app_id", help="Google Play app ID, e.g. com.brighthorizons.backupcare")
    all_p.add_argument(
        "--out",
        help="output directory (default: research_runs/<TICKER>_altdata/)",
    )
    all_p.set_defaults(fn=cmd_all)

    a = ap.parse_args(argv)
    a.fn(a)
    return 0
