"""Reddit source: post volume and top posts by month for a query."""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from collections import defaultdict

from ._http import S, get, slug, table, emit


def parse_listing_data(data: dict, sub: str, seen: set[str]) -> list[dict]:
    """Parse one Reddit /search.json listing into rows. Mutates `seen` to deduplicate."""
    rows = []
    for c in data["children"]:
        x = c["data"]
        if x["id"] in seen:
            continue
        seen.add(x["id"])
        rows.append({
            "date": dt.datetime.fromtimestamp(x["created_utc"], tz=dt.timezone.utc).date().isoformat(),
            "sub": sub,
            "score": x["score"],
            "comments": x["num_comments"],
            "title": x["title"][:140],
            "url": "https://www.reddit.com" + x["permalink"],
        })
    return rows


def _auth_session() -> str:
    """Return base URL after attempting OAuth with env credentials. Falls back to old.reddit."""
    cid = os.environ.get("REDDIT_CLIENT_ID")
    sec = os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            cid = os.environ.get("REDDIT_CLIENT_ID")
            sec = os.environ.get("REDDIT_CLIENT_SECRET")
        except ImportError:
            pass
    if cid and sec:
        tok = S.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, sec),
            data={"grant_type": "client_credentials"},
            timeout=30,
        ).json().get("access_token")
        if tok:
            S.headers["Authorization"] = f"bearer {tok}"
            return "https://oauth.reddit.com"
    return "https://old.reddit.com"


def build_reddit(a) -> tuple[str, list[dict]]:
    subs = a.subs.split(",")
    base = _auth_session()
    rows: list[dict] = []
    seen: set[str] = set()
    no_cid = not os.environ.get("REDDIT_CLIENT_ID")

    for sub in subs:
        after = None
        for _ in range(a.pages):
            p = {"q": a.query, "restrict_sr": 1, "sort": "new", "limit": 100, "t": "all"}
            if after:
                p["after"] = after
            if base.startswith("https://old"):
                url = f"{base}/r/{sub}/search.json"
            else:
                url = f"{base}/r/{sub}/search"
            r = get(url, params=p, allow_redirects=False)
            if r.status_code != 200:
                msg = f"r/{sub}: HTTP {r.status_code}"
                if no_cid:
                    msg += " (anonymous access blocked; add REDDIT_CLIENT_ID/SECRET to .env)"
                print(msg, file=sys.stderr)
                break
            d = r.json()["data"]
            rows.extend(parse_listing_data(d, sub, seen))
            after = d.get("after")
            time.sleep(1.5)
            if not after:
                break

    if not rows:
        raise SystemExit(
            "no posts found (if every sub returned 302/403, Reddit needs free API keys: "
            "create a 'script' app at https://www.reddit.com/prefs/apps and add "
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET to .env)"
        )
    by_month: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        m = r["date"][:7]
        by_month[m][0] += 1
        by_month[m][1] += r["comments"]
    months = [
        {"month": m, "posts": v[0], "comments": v[1]}
        for m, v in sorted(by_month.items())
    ][-18:]
    top = sorted(rows, key=lambda r: r["score"], reverse=True)[:10]
    md = (
        f"## Reddit mentions: \"{a.query}\" in r/{', r/'.join(subs)}\n\n"
        f"{len(rows)} posts found.\n\nBy month:\n\n"
        + table(months, ["month", "posts", "comments"])
        + "\n\nTop posts:\n\n"
        + table(top, ["date", "sub", "score", "comments", "title"])
        + "\n\nRead it as attention, not truth: a stock nobody on Reddit talks about is neglected; "
        "a spike means the crowd found it."
    )
    return md, rows


def cmd_reddit(a) -> None:
    md, rows = build_reddit(a)
    emit(a, f"reddit_{slug(a.query)}", md, rows)


def add_subparser(sp) -> None:
    r = sp.add_parser("reddit", help="Reddit mentions by month")
    r.add_argument("query")
    r.add_argument(
        "--subs",
        default="stocks,investing,ValueInvesting,SecurityAnalysis,wallstreetbets",
    )
    r.add_argument("--pages", type=int, default=2)
    r.add_argument("--out", help="directory to save .md and .csv")
    r.set_defaults(fn=cmd_reddit)
