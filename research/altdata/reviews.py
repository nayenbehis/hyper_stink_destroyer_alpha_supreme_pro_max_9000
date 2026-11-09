"""Reviews source: Google Play app ratings and volume by month."""
from __future__ import annotations

import time
from collections import defaultdict

from ._http import slug, table, emit


def build_reviews(a) -> tuple[str, list[dict]]:
    try:
        from google_play_scraper import Sort, app as gp_app, reviews
    except ImportError:
        raise SystemExit("pip install google-play-scraper")

    info = gp_app(a.app_id, lang="en", country="us")
    res, token = [], None
    while len(res) < a.count:
        batch, token = reviews(
            a.app_id, lang="en", country="us", sort=Sort.NEWEST,
            count=min(200, a.count - len(res)),
            continuation_token=token,
        )
        res += batch
        if not token or not batch:
            break
        time.sleep(1)

    rows = [
        {
            "date": r["at"].date().isoformat(),
            "score": r["score"],
            "thumbs": r["thumbsUpCount"],
            "version": r.get("reviewCreatedVersion") or "",
            "text": (r["content"] or "")[:200].replace("\n", " "),
        }
        for r in res
    ]
    by_m: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_m[r["date"][:7]].append(r["score"])
    months = [
        {"month": m, "reviews": len(v), "avg_stars": round(sum(v) / len(v), 2)}
        for m, v in sorted(by_m.items())
    ][-12:]
    overall = info.get("score")
    md = (
        f"## App reviews: {info['title']} ({a.app_id})\n\n"
        f"Installs: {info.get('installs')}, overall rating "
        f"{round(overall, 2) if overall else 'n/a'} from {info.get('ratings')} ratings. "
        f"Last {len(rows)} reviews by month:\n\n"
        + table(months, ["month", "reviews", "avg_stars"])
        + "\n\nWatch for: falling stars after an update or price change, and review volume "
        "as a rough proxy for active users."
    )
    return md, rows


def cmd_reviews(a) -> None:
    md, rows = build_reviews(a)
    emit(a, f"reviews_{slug(a.app_id)}", md, rows)


def add_subparser(sp) -> None:
    v = sp.add_parser("reviews", help="Google Play app reviews by month")
    v.add_argument("app_id", help="e.g. com.brighthorizons.mybrightday")
    v.add_argument("--count", type=int, default=600)
    v.add_argument("--out", help="directory to save .md and .csv")
    v.set_defaults(fn=cmd_reviews)
