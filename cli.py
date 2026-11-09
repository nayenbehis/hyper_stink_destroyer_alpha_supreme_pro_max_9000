"""Terminal entrypoint: build a research dossier without Streamlit.

    python cli.py TICKER [--out PATH]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from research.export import build_export, redact_secrets  # noqa: E402
from research.fundamentals import get_snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent


def _coverage_block(md: str) -> str:
    lines = md.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("## 📋 Data Coverage"))
    except StopIteration:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"), len(lines))
    return "\n".join(lines[start:end]).rstrip()


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "altdata":
        from research.altdata import altdata_main
        return altdata_main(argv[1:])
    if argv and argv[0] == "screen":
        from research.screen import screen_main
        return screen_main(argv[1:])

    parser = argparse.ArgumentParser(description="Build a markdown research dossier for a ticker.")
    parser.add_argument("ticker", help="Ticker symbol, e.g. MP or AAPL")
    parser.add_argument("--out", type=Path, help="Output path (default: research_runs/TICKER_YYYY-MM-DD/00_dossier.md)")
    args = parser.parse_args(argv)

    ticker = args.ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum() or len(ticker) > 10:
        print(f"error: '{args.ticker}' is not a valid ticker symbol", file=sys.stderr)
        return 2

    try:
        snap = get_snapshot(ticker)
    except Exception as e:
        print(f"error: could not fetch market data for {ticker}: {redact_secrets(str(e))}", file=sys.stderr)
        return 1
    if snap.get("price") is None and snap.get("market_cap") is None:
        print(f"error: no market data found for '{ticker}' — check the symbol", file=sys.stderr)
        return 1

    out = args.out or REPO_ROOT / "research_runs" / f"{ticker}_{datetime.now():%Y-%m-%d}" / "00_dossier.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    md = build_export(ticker, snap)

    if out.exists():
        backup = out.with_name(f"{out.stem}.{datetime.fromtimestamp(out.stat().st_mtime):%H%M%S}.bak{out.suffix}")
        out.rename(backup)
        print(f"note: existing dossier moved to {backup}")
    out.write_text(md, encoding="utf-8")

    print(f"wrote {out}")
    print()
    print(_coverage_block(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
