"""Offline tests for altdata parsers — no live HTTP calls."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- sitemap diff
class TestSitemapDiff:
    from research.altdata.sitemap import compute_diff  # imported at class level for clarity

    def test_basic_diff(self):
        from research.altdata.sitemap import compute_diff
        mbd = {
            "2022-01": {"/locations/a", "/locations/b", "/locations/c"},
            "2023-01": {"/locations/b", "/locations/c", "/locations/d"},
        }
        added, removed = compute_diff(mbd)
        assert added == ["/locations/d"]
        assert removed == ["/locations/a"]

    def test_empty_returns_empty(self):
        from research.altdata.sitemap import compute_diff
        assert compute_diff({}) == ([], [])

    def test_single_snapshot_returns_empty(self):
        from research.altdata.sitemap import compute_diff
        mbd = {"2023-01": {"/a", "/b"}}
        assert compute_diff(mbd) == ([], [])

    def test_skips_low_count_pre_redesign_samples(self):
        from research.altdata.sitemap import compute_diff
        # "2021-01" has only 1 URL (< 50% of peak 100); should be ignored as pre-redesign
        mbd = {
            "2021-01": {"/old"},                          # 1 URL — pre-redesign noise
            "2022-01": {f"/loc/{i}" for i in range(100)},  # 100 URLs — peak
            "2023-01": {f"/loc/{i}" for i in range(95)} | {"/loc/new"},  # 96 URLs
        }
        added, removed = compute_diff(mbd)
        # should diff 2022-01 → 2023-01, not 2021-01 → 2023-01
        assert "/loc/new" in added
        assert "/old" not in removed  # pre-redesign URL excluded from diff base

    def test_no_change(self):
        from research.altdata.sitemap import compute_diff
        urls = {"/a", "/b", "/c"}
        mbd = {"2022-01": urls, "2023-01": urls}
        added, removed = compute_diff(mbd)
        assert added == []
        assert removed == []


# ---------------------------------------------------------------- Form 4 XML parsing
class TestForm4Parsing:
    def test_parses_buy_and_sell(self):
        from research.altdata.insiders import parse_transactions
        xml = (FIXTURES / "form4.xml").read_bytes()
        txns = parse_transactions(xml, "2024-03-01")
        assert len(txns) == 3
        buy = next(t for t in txns if t["code"] == "P")
        sell = next(t for t in txns if t["code"] == "S")
        assert buy["shares"] == 2500
        assert buy["price"] == 42.0
        assert buy["value_usd"] == 105000
        assert sell["shares"] == 1000
        assert sell["price"] == 45.5

    def test_insider_name_and_title(self):
        from research.altdata.insiders import parse_transactions
        xml = (FIXTURES / "form4.xml").read_bytes()
        txns = parse_transactions(xml, "2024-03-01")
        assert all(t["insider"] == "Jane Smith" for t in txns)
        assert all(t["title"] == "CEO" for t in txns)

    def test_transaction_types_mapped(self):
        from research.altdata.insiders import parse_transactions, CODES
        xml = (FIXTURES / "form4.xml").read_bytes()
        txns = parse_transactions(xml, "2024-03-01")
        for t in txns:
            assert t["type"] == CODES.get(t["code"], t["code"])

    def test_filed_date_set(self):
        from research.altdata.insiders import parse_transactions
        xml = (FIXTURES / "form4.xml").read_bytes()
        txns = parse_transactions(xml, "2024-03-01")
        assert all(t["filed"] == "2024-03-01" for t in txns)

    def test_malformed_xml_returns_empty(self):
        from research.altdata.insiders import parse_transactions
        txns = parse_transactions(b"not xml at all <<>>", "2024-01-01")
        assert txns == []


# ---------------------------------------------------------------- Reddit JSON parsing
class TestRedditParsing:
    def test_parses_posts(self):
        from research.altdata.reddit import parse_listing_data
        data = json.loads((FIXTURES / "reddit_listing.json").read_text())["data"]
        rows = parse_listing_data(data, "ValueInvesting", set())
        assert len(rows) == 2  # 3rd is a duplicate id

    def test_deduplication(self):
        from research.altdata.reddit import parse_listing_data
        data = json.loads((FIXTURES / "reddit_listing.json").read_text())["data"]
        seen: set[str] = set()
        rows1 = parse_listing_data(data, "ValueInvesting", seen)
        rows2 = parse_listing_data(data, "stocks", seen)
        assert len(rows2) == 0  # all ids already seen

    def test_row_fields(self):
        from research.altdata.reddit import parse_listing_data
        data = json.loads((FIXTURES / "reddit_listing.json").read_text())["data"]
        rows = parse_listing_data(data, "ValueInvesting", set())
        r = rows[0]
        assert r["score"] == 87
        assert r["comments"] == 23
        assert r["date"].startswith("2024")
        assert r["url"].startswith("https://www.reddit.com")
        assert len(r["title"]) <= 140

    def test_title_truncated_at_140(self):
        from research.altdata.reddit import parse_listing_data
        long_title = "x" * 200
        data = {
            "children": [{
                "kind": "t3",
                "data": {
                    "id": "zzz999",
                    "title": long_title,
                    "score": 1,
                    "num_comments": 0,
                    "created_utc": 1704067200,
                    "permalink": "/r/test/comments/zzz999/x/",
                },
            }]
        }
        rows = parse_listing_data(data, "test", set())
        assert len(rows[0]["title"]) == 140


# ---------------------------------------------------------------- Jobs history CSV
class TestJobsHistoryCSV:
    def test_creates_file_with_header(self, tmp_path):
        from research.altdata.jobs import append_history_row
        path = tmp_path / "history.csv"
        row = {"date": "2024-01-01", "query": "Bright Horizons", "company": "",
               "postings": 42, "hours_window": 720, "sites": "indeed"}
        append_history_row(path, row)
        rows = list(csv.DictReader(path.open()))
        assert len(rows) == 1
        assert rows[0]["postings"] == "42"

    def test_appends_subsequent_rows(self, tmp_path):
        from research.altdata.jobs import append_history_row
        path = tmp_path / "history.csv"
        base = {"date": "2024-01-01", "query": "q", "company": "",
                "postings": 10, "hours_window": 720, "sites": "indeed"}
        append_history_row(path, base)
        append_history_row(path, {**base, "date": "2024-01-08", "postings": 15})
        append_history_row(path, {**base, "date": "2024-01-15", "postings": 20})
        rows = list(csv.DictReader(path.open()))
        assert len(rows) == 3
        assert [r["postings"] for r in rows] == ["10", "15", "20"]

    def test_creates_parent_dirs(self, tmp_path):
        from research.altdata.jobs import append_history_row
        path = tmp_path / "deep" / "nested" / "history.csv"
        row = {"date": "2024-01-01", "query": "q", "company": "",
               "postings": 5, "hours_window": 720, "sites": "indeed"}
        append_history_row(path, row)
        assert path.exists()
