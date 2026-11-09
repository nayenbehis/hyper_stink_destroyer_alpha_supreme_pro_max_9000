"""Sitemap page-count source: track matching URL counts over time via Wayback."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time

from ._http import get, slug, table, emit


def _locs(xml_text: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text)


def compute_diff(
    matched_by_date: dict[str, set[str]]
) -> tuple[list[str], list[str]]:
    """Return (added, removed) URLs between first and last significant snapshot.

    Skips samples with fewer than half the peak count to ignore pre-redesign noise.
    """
    peak = max((len(v) for v in matched_by_date.values()), default=0)
    if not peak:
        return [], []
    nz = [k for k in matched_by_date if len(matched_by_date[k]) >= 0.5 * peak]
    if len(nz) < 2:
        return [], []
    first, last_ = matched_by_date[nz[0]], matched_by_date[nz[-1]]
    return sorted(last_ - first), sorted(first - last_)


def build_sitemap(a) -> tuple[str, list[dict]]:
    site = a.site.rstrip("/")
    sm_url = getattr(a, "sitemap_url", None) or site + "/sitemap.xml"
    pat = re.compile(a.match, re.I)
    params = {
        "url": sm_url, "output": "json", "fl": "timestamp,statuscode",
        "filter": "statuscode:200", "collapse": "timestamp:6",
        "from": str(a.start),
    }
    data = get("https://web.archive.org/cdx/search/cdx", params=params, timeout=60).json() or [[]]
    snaps = [s[0] for s in data[1:]]
    picked, last = [], None
    for ts in snaps:
        d = dt.datetime.strptime(ts[:8], "%Y%m%d").date()
        if last is None or (d.year - last.year) * 12 + d.month - last.month >= a.every:
            picked.append((ts, d))
            last = d
    picked = picked[-a.max:]
    rows: list[dict] = []
    matched_by_date: dict[str, set[str]] = {}

    def fetch_all(ts, url, depth=0):
        archive = f"https://web.archive.org/web/{ts}id_/{url}" if ts else url
        txt = get(archive, timeout=60).text
        if "<sitemapindex" in txt and depth < 2:
            out = []
            for child in _locs(txt)[:60]:
                time.sleep(a.pause)
                out += fetch_all(ts, child, depth + 1)
            return out
        return _locs(txt)

    depth_filter = getattr(a, "depth", None)
    for ts, d in picked + [(None, dt.date.today())]:
        try:
            locs = fetch_all(ts, sm_url)
        except SystemExit as e:
            print(f"skip {ts}: {e}", file=sys.stderr)
            continue
        hits = sorted({
            u.rstrip("/") for u in locs
            if pat.search(u) and (depth_filter is None or u.rstrip("/").count("/") == depth_filter)
        })
        matched_by_date[d.isoformat()] = set(hits)
        rows.append({
            "date": d.isoformat(),
            "source": "live" if ts is None else f"wayback {ts[:8]}",
            "sitemap_urls": len(locs),
            "matching": len(hits),
        })
        time.sleep(a.pause)

    added, removed = compute_diff(matched_by_date)
    dates = sorted(matched_by_date)
    diff = ""
    if added or removed:
        nz = [k for k in dates if len(matched_by_date[k]) >= 0.5 * max(len(v) for v in matched_by_date.values())]
        from_date, to_date = nz[0], nz[-1]
        diff = (
            f"\n\nBetween {from_date} and {to_date}: "
            f"**+{len(added)} added, -{len(removed)} removed**.\n\n"
            "Removed (sample):\n" + "\n".join(f"- {u}" for u in removed[:25]) +
            "\n\nAdded (sample):\n" + "\n".join(f"- {u}" for u in added[:25])
        )
        out_dir = getattr(a, "out", None)
        if out_dir:
            import datetime as _dt
            today = _dt.date.today().isoformat()
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, f"sitemap_{slug(site)}_{today}_changes.json"), "w") as f:
                json.dump(
                    {"from": from_date, "to": to_date, "added": added, "removed": removed},
                    f, indent=1,
                )

    depth_note = f" at depth {depth_filter}" if depth_filter is not None else ""
    md = (
        f"## Sitemap trail: {site} — URLs matching `{a.match}`{depth_note}\n\n"
        + table(rows, ["date", "source", "sitemap_urls", "matching"])
        + diff
        + "\n\nCaveat: sites restructure their URLs and sitemaps; a jump to or from zero usually "
        "means a redesign, not real openings/closures. Compare only periods with the same URL structure."
    )
    return md, rows


def cmd_sitemap(a) -> None:
    md, rows = build_sitemap(a)
    emit(a, f"sitemap_{slug(a.site)}", md, rows)


def add_subparser(sp) -> None:
    m = sp.add_parser(
        "sitemap",
        help="count matching pages in a site's sitemap over time (locations, products)",
    )
    m.add_argument("site", help="e.g. https://www.brighthorizons.com")
    m.add_argument("--match", required=True, help="regex for URLs to count, e.g. '/daycare-centers/'")
    m.add_argument("--depth", type=int, help="only URLs with exactly this many '/' (isolates leaf pages)")
    m.add_argument("--sitemap-url", dest="sitemap_url", help="sitemap URL if not <site>/sitemap.xml")
    m.add_argument("--start", type=int, default=2020)
    m.add_argument("--every", type=int, default=3)
    m.add_argument("--max", type=int, default=12)
    m.add_argument("--pause", type=float, default=1.0)
    m.add_argument("--out", help="directory to save .md and .csv")
    m.set_defaults(fn=cmd_sitemap)
