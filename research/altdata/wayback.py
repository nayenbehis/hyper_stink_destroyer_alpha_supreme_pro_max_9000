"""Wayback Machine page-scraping source: count regex matches over time."""
from __future__ import annotations

import datetime as dt
import re
import time

from ._http import get, slug, table, emit


def build_wayback(a) -> tuple[str, list[dict]]:
    params = {
        "url": a.url, "output": "json",
        "fl": "timestamp,original,statuscode,length",
        "filter": "statuscode:200", "collapse": "timestamp:6",
        "from": str(a.start),
    }
    r = get("https://web.archive.org/cdx/search/cdx", params=params, timeout=60)
    data = r.json() if r.text.strip() else []
    snaps = data[1:] if data else []
    if not snaps:
        raise SystemExit(
            "no snapshots found for that URL "
            "(try the exact URL, with or without www/trailing slash)"
        )
    picked, last = [], None
    for ts, orig, _sc, _ln in snaps:
        d = dt.datetime.strptime(ts[:8], "%Y%m%d").date()
        if last is None or (d.year - last.year) * 12 + d.month - last.month >= a.every:
            picked.append((ts, orig, d))
            last = d
    picked = picked[-a.max:]
    pats = [re.compile(p, re.I) for p in (a.pattern or [])]
    rows = []
    for ts, orig, d in picked:
        rr = get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=60)
        html = rr.text
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        row = {
            "date": d.isoformat(),
            "snapshot": f"https://web.archive.org/web/{ts}/{orig}",
            "http": rr.status_code,
            "kb": round(len(html) / 1024, 1),
            "links": len(re.findall(r"<a\s", html, re.I)),
        }
        for p in pats:
            row[f"count[{p.pattern}]"] = len(p.findall(html if a.raw else text))
        if a.number:
            m = re.search(a.number, text, re.I)
            row["number"] = (
                m.group(1).replace(",", "") if m and m.groups() else (m.group(0) if m else "")
            )
        rows.append(row)
        time.sleep(a.pause)
    cols = list(rows[0].keys())
    md = (
        f"## Wayback trail: {a.url}\n\n"
        f"{len(snaps)} monthly captures since {a.start}; showing one every "
        f"{a.every} months ({len(rows)} pages fetched).\n\n"
        + table(rows, cols)
        + "\n\nCaveat: pages may load content with JavaScript, so counts can miss items the browser "
        "shows; open a snapshot link to confirm what was counted."
    )
    return md, rows


def cmd_wayback(a) -> None:
    md, rows = build_wayback(a)
    emit(a, f"wayback_{slug(a.url)}", md, rows)


def add_subparser(sp) -> None:
    w = sp.add_parser("wayback", help="count things on a page over time via Wayback Machine")
    w.add_argument("url")
    w.add_argument("--start", type=int, default=2019, help="first year (default 2019)")
    w.add_argument("--every", type=int, default=6, help="months between samples (default 6)")
    w.add_argument("--max", type=int, default=16, help="max pages to fetch (default 16)")
    w.add_argument("--pattern", action="append", help="regex to count (repeatable)")
    w.add_argument(
        "--number",
        help=r"regex with one group capturing a number, e.g. '([\d,]+) centers'",
    )
    w.add_argument("--raw", action="store_true", help="count in raw HTML instead of visible text")
    w.add_argument("--pause", type=float, default=1.5)
    w.add_argument("--out", help="directory to save .md and .csv")
    w.set_defaults(fn=cmd_wayback)
