"""AI-powered stock analysis using Groq (free tier)."""

from __future__ import annotations

import os
from typing import Any, Generator

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def _fmt(val, prefix="$", suffix="", decimals=2):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{prefix}{val:,.{decimals}f}{suffix}"
    return str(val)


def _build_prompt(ticker: str, snap: dict, sec_metrics: dict, analyst: dict) -> str:
    mc = snap.get("market_cap")
    mc_str = f"${mc/1e9:.1f}B" if mc and mc >= 1e9 else (f"${mc/1e6:.0f}M" if mc else "N/A")

    rev = sec_metrics.get("revenue")
    ni = sec_metrics.get("net_income")
    assets = sec_metrics.get("total_assets")
    ocf = sec_metrics.get("operating_cash_flow")
    rev_str = f"${rev/1e9:.1f}B" if rev and rev >= 1e9 else (f"${rev/1e6:.0f}M" if rev else "N/A")
    ni_str = f"${ni/1e9:.1f}B" if ni and ni >= 1e9 else (f"${ni/1e6:.0f}M" if ni else "N/A")

    return f"""You are a senior equity analyst writing a research note for institutional investors.

Analyze {ticker} ({snap.get('name', ticker)}) and produce a concise, high-signal research note.

## MARKET DATA
- Price: {_fmt(snap.get('price'))}
- Market Cap: {mc_str}
- P/E (TTM): {_fmt(snap.get('pe_ratio'), prefix='', suffix='x')}
- Forward P/E: {_fmt(snap.get('forward_pe'), prefix='', suffix='x')}
- EPS: {_fmt(snap.get('eps'))}
- 52W High/Low: {_fmt(snap.get('52w_high'))} / {_fmt(snap.get('52w_low'))}
- Sector: {snap.get('sector', 'N/A')} | Industry: {snap.get('industry', 'N/A')}

## SEC EDGAR FINANCIALS (LATEST ANNUAL)
- Revenue: {rev_str}
- Net Income: {ni_str}
- Total Assets: {"${:.1f}B".format(assets/1e9) if assets and assets >= 1e9 else "N/A"}
- Operating Cash Flow: {"${:.1f}B".format(ocf/1e9) if ocf and ocf >= 1e9 else "N/A"}

## ANALYST CONSENSUS
- Consensus: {str(analyst.get('recommendation', 'N/A')).upper()}
- Price Target (Mean): {_fmt(analyst.get('target_mean'))}
- Target Range: {_fmt(analyst.get('target_low'))} – {_fmt(analyst.get('target_high'))}
- Number of Analysts: {analyst.get('num_analysts', 'N/A')}

## BUSINESS DESCRIPTION
{snap.get('description', 'N/A')[:600] if snap.get('description') else 'N/A'}

---

Write a research note with these sections:

**INVESTMENT THESIS** (2-3 sentences: the core bull or bear case)

**KEY STRENGTHS** (3 bullet points max)

**KEY RISKS** (3 bullet points max)

**VALUATION SNAPSHOT** (brief take on whether current multiple is rich, fair, or cheap vs. the sector)

**VERDICT** (one line: BUY / HOLD / SELL and why, based purely on the data above)

Be direct and data-driven. No fluff."""


def stream_analysis(
    ticker: str,
    snap: dict[str, Any],
    sec_metrics: dict[str, Any],
    analyst: dict[str, Any],
) -> Generator[str, None, None]:
    """Stream an AI research note for a ticker. Yields text chunks."""
    client = _get_client()
    prompt = _build_prompt(ticker, snap, sec_metrics, analyst)

    stream = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta is not None and delta != "":
            yield delta
