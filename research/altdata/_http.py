"""Shared HTTP session, retry/backoff, and output helpers for altdata sources."""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import time

import requests

UA = "hyperstink-research/0.1 research@example.com"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})


def get(url: str, **kw) -> requests.Response:
    """GET with 3 retries, exponential backoff on 429 and connection errors."""
    timeout = kw.pop("timeout", 30)
    err: Exception | None = None
    for i in range(3):
        try:
            r = S.get(url, timeout=timeout, **kw)
            if r.status_code == 429:
                time.sleep(5 * (i + 1))
                continue
            return r
        except requests.RequestException as e:
            err = e
            time.sleep(2 * (i + 1))
    raise SystemExit(f"request failed: {url} ({err!r})")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def emit(args: object, name: str, md: str, rows: list[dict] | None) -> str:
    """Print markdown, optionally save .md and .csv to args.out. Returns the markdown."""
    print(md)
    out_dir = getattr(args, "out", None)
    if out_dir and rows is not None:
        today = dt.date.today().isoformat()
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, f"{name}_{today}")
        with open(base + ".md", "w") as f:
            f.write(md + "\n")
        if rows:
            with open(base + ".csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        print(f"\n_saved {base}.md / .csv_")
    return md
