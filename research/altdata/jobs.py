"""Jobs source: snapshot current postings via JobSpy and append to a history CSV."""
from __future__ import annotations

import csv
import datetime as dt
import os
from collections import Counter
from pathlib import Path
from typing import Union

from ._http import slug, table, emit


def append_history_row(path: Union[str, Path], row: dict) -> None:
    """Append one summary row to a history CSV, creating with header if the file is new."""
    path = str(path)
    is_new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            w.writeheader()
        w.writerow(row)


def build_jobs(a) -> tuple[str, list[dict]]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        raise SystemExit("pip install python-jobspy")

    today = dt.date.today().isoformat()
    df = scrape_jobs(
        site_name=a.sites.split(","),
        search_term=a.query,
        location=a.location or None,
        results_wanted=a.results,
        hours_old=a.hours,
        country_indeed=a.country,
    )
    if df is None or df.empty:
        raise SystemExit(
            "no postings returned (sites may be rate-limiting; try fewer results or another site)"
        )
    if a.company:
        df = df[df["company"].fillna("").str.contains(a.company, case=False, regex=False)]
    n = len(df)
    by_title = Counter(
        df["title"].fillna("?").str.replace(r"\s*[-–(].*$", "", regex=True)
    ).most_common(12)
    by_state = Counter(
        df["location"].fillna("?").str.extract(r",\s*([A-Z]{2})\b")[0].fillna("other")
    ).most_common(12)
    by_site = Counter(df["site"].fillna("?"))
    md = (
        f"## Job postings: \"{a.query}\""
        + (f" at {a.company}" if a.company else "")
        + f" — snapshot {today}\n\n"
        f"**{n} postings** (posted within {a.hours} h; sites: {dict(by_site)})\n\n"
        "Top titles:\n" + "\n".join(f"- {t}: {c}" for t, c in by_title)
        + "\n\nTop states:\n" + "\n".join(f"- {s}: {c}" for s, c in by_state)
    )
    summary_row = {
        "date": today, "query": a.query, "company": a.company or "",
        "postings": n, "hours_window": a.hours, "sites": a.sites,
    }
    if a.history:
        append_history_row(a.history, summary_row)
        hist = list(csv.DictReader(open(a.history)))
        md += (
            "\n\nHistory (" + a.history + "):\n\n"
            + table(hist[-12:], ["date", "postings", "hours_window", "sites"])
        )
    md += (
        "\n\nCaveat: one snapshot is a level, not a trend. Re-run weekly with --history to see "
        "direction; job boards dedupe and rate-limit imperfectly."
    )
    detail = (
        df[["site", "title", "company", "location", "date_posted", "job_url"]]
        .astype(str)
        .to_dict("records")
    )
    return md, detail


def cmd_jobs(a) -> None:
    md, rows = build_jobs(a)
    emit(a, f"jobs_{slug(a.company or a.query)}", md, rows)


def add_subparser(sp) -> None:
    j = sp.add_parser("jobs", help="job postings snapshot (+ history trend)")
    j.add_argument("query")
    j.add_argument("--company", help="keep only postings whose company field contains this")
    j.add_argument("--location")
    j.add_argument("--sites", default="indeed,zip_recruiter")
    j.add_argument("--results", type=int, default=200)
    j.add_argument("--hours", type=int, default=720, help="only postings this new (default 30 days)")
    j.add_argument("--country", default="USA")
    j.add_argument("--history", help="CSV to append a summary row to on each run")
    j.add_argument("--out", help="directory to save .md and .csv")
    j.set_defaults(fn=cmd_jobs)
