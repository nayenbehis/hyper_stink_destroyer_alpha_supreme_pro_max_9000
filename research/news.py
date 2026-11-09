"""News feed — yfinance first, Google News RSS fallback."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

import requests
import yfinance as yf

_GNEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; hyper-stink-destroyer/1.0)"}


def _google_news(query: str, limit: int) -> list[dict]:
    """Fetch from Google News RSS."""
    url = _GNEWS_URL.format(query=quote_plus(query))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        results = []
        for item in items[:limit]:
            title = (item.findtext("title") or "").strip()
            link = item.findtext("link") or ""
            pub = item.findtext("pubDate") or ""
            source_el = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            publisher = ""
            src = item.find("source")
            if src is not None:
                publisher = src.text or ""
            try:
                from email.utils import parsedate_to_datetime
                date_str = parsedate_to_datetime(pub).strftime("%Y-%m-%d")
            except Exception:
                try:
                    date_str = datetime.strptime(pub[:16], "%a, %d %b %Y").strftime("%Y-%m-%d")
                except Exception:
                    date_str = pub[:10]
            if title:
                results.append({"title": title, "publisher": publisher, "url": link, "date": date_str})
        return results
    except Exception:
        return []


def get_news(ticker: str, limit: int = 8) -> list[dict]:
    """Return recent news headlines — yfinance first, Google News RSS fallback."""
    # Try yfinance
    try:
        raw = yf.Ticker(ticker).news or []
        results = []
        for item in raw[:limit]:
            ts = item.get("providerPublishTime", 0)
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
            content = item.get("content", {})
            title = content.get("title") or item.get("title", "")
            publisher = (content.get("provider", {}) or {}).get("displayName") or item.get("publisher", "")
            url = (content.get("canonicalUrl", {}) or {}).get("url") or item.get("link", "")
            if title:
                results.append({"title": title, "publisher": publisher, "url": url, "date": date_str})
        if results:
            return results
    except Exception:
        pass

    # Fallback: Google News RSS using ticker + "stock"
    name = ""
    try:
        name = yf.Ticker(ticker).info.get("shortName", "")
    except Exception:
        pass

    query = f"{name} {ticker} stock" if name else f"{ticker} stock"
    return _google_news(query, limit)
