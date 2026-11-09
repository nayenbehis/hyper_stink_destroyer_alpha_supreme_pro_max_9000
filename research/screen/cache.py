"""Simple file-based JSON cache with a 7-day TTL."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _REPO_ROOT / "data" / "screen_cache"
TTL_DAYS = 7


def _find(key: str) -> Path | None:
    if not CACHE_DIR.exists():
        return None
    cutoff = dt.date.today() - dt.timedelta(days=TTL_DAYS)
    for p in CACHE_DIR.glob(f"{key}_*.json"):
        try:
            date_str = p.stem.rsplit("_", 1)[-1]
            if dt.date.fromisoformat(date_str) >= cutoff:
                return p
        except ValueError:
            pass
    return None


def load(key: str) -> Any | None:
    p = _find(key)
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def save(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = CACHE_DIR / f"{key}_{today}.json"
    path.write_text(json.dumps(data, default=str), encoding="utf-8")


def invalidate(key: str) -> int:
    """Delete all cached files matching key. Returns count removed."""
    removed = 0
    if CACHE_DIR.exists():
        for p in CACHE_DIR.glob(f"{key}_*.json"):
            p.unlink()
            removed += 1
    return removed
