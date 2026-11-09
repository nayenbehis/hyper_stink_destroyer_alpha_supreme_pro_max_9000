"""build_export — compile all available research into a markdown dossier.

Shared by app/main.py (Streamlit download) and cli.py (terminal output).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from research.fundamentals import get_analyst_ratings, get_earnings_data, get_peers
from research.macro import get_snapshot as get_macro_snapshot, relevant_series
from research.news import get_news
from research.sec import get_annual_history, get_insider_trades, get_quarterly_history


def build_export(ticker: str, snap: dict) -> str:  # noqa: C901
    """Compile all available research into a markdown document for Claude agents."""
    now = datetime.now(tz=timezone.utc)
    warnings: list[str] = []
    cov: dict[str, str] = {}  # section → ✅ / ⚠️ / ❌

    # ── helpers ─────────────────────────────────────────────────────────────
    def _b(v, abs_val=False):
        if v is None: return "N/A"
        n = abs(v) if abs_val else v
        sign = "-" if v < 0 and not abs_val else ""
        if abs(n) >= 1e12: return f"{sign}${abs(n)/1e12:.2f}T"
        if abs(n) >= 1e9:  return f"{sign}${abs(n)/1e9:.2f}B"
        if abs(n) >= 1e6:  return f"{sign}${abs(n)/1e6:.0f}M"
        return f"{sign}${abs(n):,.0f}"

    def _f(v, prefix="$", suffix="", dec=2):
        if v is None: return "N/A"
        return f"{prefix}{v:,.{dec}f}{suffix}"

    def _pct(num, denom):
        if num is None or not denom: return "N/A"
        return f"{num / denom * 100:.1f}%"

    def _yoy(curr, prev):
        """YoY change. When either value is negative, shows absolute $ delta instead of %."""
        if curr is None or prev is None or prev == 0: return "—"
        if curr < 0 or prev < 0:
            delta = curr - prev
            if abs(delta) >= 1e9: return f"{delta/1e9:+.1f}B"
            if abs(delta) >= 1e6: return f"{delta/1e6:+.0f}M"
            return f"{delta:+.2f}"
        return f"{(curr - prev) / abs(prev) * 100:+.1f}%"

    def _rec(r):
        m = {"strong_buy": "STRONG BUY ✅", "buy": "BUY ✅", "hold": "HOLD ⚖️",
             "sell": "SELL ❌", "strong_sell": "STRONG SELL ❌"}
        return m.get(str(r).lower(), str(r).upper())

    def _v(fy_data: dict, metric: str):
        """Get numeric value for metric in a FY dict, or None."""
        entry = fy_data.get(metric)
        return entry["value"] if entry else None

    # ── fetch multi-year history ─────────────────────────────────────────────
    hist: dict = {"years": [], "data": {}, "latest_fy_end": "", "warnings": [], "current_shares_outstanding": None}
    try:
        hist = get_annual_history(ticker, years=5)
        warnings.extend(hist.get("warnings", []))
        cov["financials"] = "✅" if len(hist["years"]) >= 3 else ("⚠️" if hist["years"] else "❌")
    except Exception as e:
        cov["financials"] = "❌"
        warnings.append(f"annual history: {e}")

    # ── fetch quarterly history ───────────────────────────────────────────────
    qhist: dict = {"quarters": [], "data": {}, "ttm": {}, "balance_sheet": {}, "current_shares": None, "warnings": []}
    try:
        qhist = get_quarterly_history(ticker)
        warnings.extend(qhist.get("warnings", []))
        cov["quarterly"] = "✅" if qhist["quarters"] else "⚠️"
    except Exception as e:
        cov["quarterly"] = "❌"
        warnings.append(f"quarterly history: {e}")

    mc   = snap.get("market_cap")
    price = snap.get("price")
    hi, lo = snap.get("52w_high"), snap.get("52w_low")
    pos_52w = f"{(price - lo) / (hi - lo) * 100:.0f}% of 52W range" if price and hi and lo and hi != lo else "N/A"

    # ── capital structure — prefer quarterly balance sheet over FY ───────────
    bs = qhist.get("balance_sheet", {})
    bs_period = bs.get("period_end", "")

    def _bs(metric):
        """Get value from quarterly balance sheet, note the XBRL tag used."""
        entry = bs.get(metric)
        if entry and isinstance(entry, dict):
            return entry.get("value"), entry.get("tag", "")
        return None, ""

    latest_fy_data = hist["data"].get(hist["years"][-1], {}) if hist["years"] else {}

    cash_val,  cash_tag  = _bs("cash")
    sti_val,   sti_tag   = _bs("short_term_investments")
    ltd_val,   ltd_tag   = _bs("long_term_debt")
    std_val,   std_tag   = _bs("short_term_debt")
    pref_val,  pref_tag  = _bs("preferred_stock")

    # Fall back to FY data if quarterly balance sheet missing
    if cash_val is None: cash_val = _v(latest_fy_data, "cash"); cash_tag = "FY"
    if ltd_val  is None: ltd_val  = _v(latest_fy_data, "long_term_debt"); ltd_tag = "FY"
    if std_val  is None: std_val  = _v(latest_fy_data, "short_term_debt"); std_tag = "FY"
    if pref_val is None: pref_val = _v(latest_fy_data, "preferred_stock"); pref_tag = "FY"
    if sti_val  is None: sti_val  = _v(latest_fy_data, "short_term_investments"); sti_tag = "FY"

    cash_plus_sti = (cash_val or 0) + (sti_val or 0) if (cash_val is not None or sti_val is not None) else None
    total_debt = (ltd_val or 0) + (std_val or 0) if (ltd_val is not None or std_val is not None) else None
    net_debt   = (total_debt - cash_plus_sti) if (total_debt is not None and cash_plus_sti is not None) else None
    ev         = (mc + net_debt + (pref_val or 0)) if (mc and net_debt is not None) else None
    cov["capital_structure"] = "✅" if (cash_plus_sti is not None or total_debt is not None) else "⚠️"

    # Current shares — prefer dei, fall back to yfinance basic shares
    current_shares = qhist.get("current_shares") or hist.get("current_shares_outstanding")
    if not current_shares:
        basic_sh_data = _v(latest_fy_data, "basic_shares")
        current_shares = int(basic_sh_data) if basic_sh_data else None

    # ── valuation inputs — TTM where available, else latest FY ──────────────
    lfy = hist["years"][-1] if hist["years"] else None
    ttm = qhist.get("ttm", {})

    def _ttm_or_fy(metric):
        """Return (value, period_label) — TTM from quarterly data, else latest FY."""
        if metric in ttm and ttm[metric] is not None:
            return ttm[metric], "TTM"
        return _v(latest_fy_data, metric), f"FY{lfy}"

    rev_val,  rev_period  = _ttm_or_fy("revenue")
    ocf_val,  ocf_period  = _ttm_or_fy("operating_cash_flow")
    capex_val, capex_period = _ttm_or_fy("capex")
    ni_val,   ni_period   = _ttm_or_fy("net_income")

    fcf_val = (ocf_val - abs(capex_val)) if (ocf_val is not None and capex_val is not None) else None
    fcf_period = ocf_period  # same source as OCF

    ev_rev  = f"{ev/rev_val:.1f}x" if ev and rev_val else "N/A"
    ev_fcf  = f"{ev/fcf_val:.1f}x" if ev and fcf_val and fcf_val > 0 else "N/A"
    fcf_yield = _pct(fcf_val, mc)
    pe_ttm    = _f(snap.get("pe_ratio"), prefix="", suffix="x") if snap.get("pe_ratio") else "N/A"
    cov["valuation"] = "✅" if ev else "⚠️"

    # ── analyst ─────────────────────────────────────────────────────────────
    rat: dict = {}
    try:
        rat = get_analyst_ratings(ticker)
        cov["analyst"] = "✅" if rat.get("recommendation") else "⚠️"
    except Exception as e:
        cov["analyst"] = "❌"
        warnings.append(f"analyst: {e}")

    # ── earnings ────────────────────────────────────────────────────────────
    ed: dict = {"next_date": None, "history": []}
    try:
        ed = get_earnings_data(ticker)
        cov["earnings"] = "✅" if ed.get("history") else "⚠️"
    except Exception as e:
        cov["earnings"] = "❌"
        warnings.append(f"earnings: {e}")

    # ── insider trades ───────────────────────────────────────────────────────
    trades: list = []
    try:
        trades = get_insider_trades(ticker, limit=10)
        has_tx = any(t.get("transactions") for t in trades)
        cov["insider"] = "✅" if has_tx else "⚠️"
    except Exception as e:
        cov["insider"] = "❌"
        warnings.append(f"insider trades: {e}")

    # ── macro ────────────────────────────────────────────────────────────────
    macro_data: dict = {}
    rel_keys: list = []
    try:
        rel_keys = relevant_series(snap.get("sector", ""))
        if not os.getenv("FRED_API_KEY"):
            raise EnvironmentError("FRED_API_KEY not set")
        macro_data = get_macro_snapshot()
        # get_snapshot swallows per-series errors, so an all-None result means nothing loaded
        if not any(macro_data.get(k, {}).get("value") is not None for k in rel_keys):
            raise RuntimeError("no FRED series returned data")
        cov["macro"] = "✅"
    except Exception as e:
        macro_data = {}
        cov["macro"] = "❌"
        warnings.append(f"macro (FRED): {e}")

    # ── peers ────────────────────────────────────────────────────────────────
    peers: list = []
    try:
        if snap.get("sector"):
            peers = get_peers(ticker, snap["sector"], limit=5, industry=snap.get("industry", ""))
        cov["peers"] = "✅" if peers else "⚠️"
    except Exception as e:
        cov["peers"] = "❌"
        warnings.append(f"peers: {e}")

    # ── news ─────────────────────────────────────────────────────────────────
    articles: list = []
    try:
        articles = get_news(ticker, limit=8)
        cov["news"] = "✅" if articles else "⚠️"
    except Exception as e:
        cov["news"] = "❌"
        warnings.append(f"news: {e}")

    cov["market_snapshot"] = "✅"

    # ════════════════════════════════════════════════════════════════════════
    # BUILD DOCUMENT
    # ════════════════════════════════════════════════════════════════════════
    L = []  # lines

    # ── header ───────────────────────────────────────────────────────────────
    L += [
        f"# {ticker} · {snap.get('name', ticker)}",
        f"> **As-of:** {now.strftime('%Y-%m-%dT%H:%M:%S%z')}  ",
        f"> **Latest FY End:** {hist.get('latest_fy_end') or 'unknown'}  ",
        f"> **Sector:** {snap.get('sector', 'N/A')} / {snap.get('industry', 'N/A')}",
        "",
        "## 📋 Data Coverage",
        "",
        "| Section | Status |",
        "|---------|--------|",
    ]
    section_labels = {
        "market_snapshot": "Market Snapshot",
        "financials": "Multi-Year Financials (SEC XBRL)",
        "quarterly": "Latest Quarters + TTM",
        "capital_structure": "Capital Structure",
        "valuation": "Valuation Inputs",
        "analyst": "Analyst Consensus",
        "earnings": "Earnings History",
        "insider": "Insider Trades (Form 4)",
        "macro": "Macro Context (FRED)",
        "peers": "Industry Peers",
        "news": "Recent News",
    }
    for key, label in section_labels.items():
        L.append(f"| {label} | {cov.get(key, '❌')} |")
    L.append("")
    if warnings:
        for w in warnings:
            L.append(f"> ⚠️ DATA UNAVAILABLE — {w}")
        L.append("")

    # ── market snapshot ───────────────────────────────────────────────────────
    shares_str = f"{current_shares/1e6:.1f}M" if current_shares else "N/A"
    mc_check = _b(price * current_shares) if (price and current_shares) else "N/A"
    L += [
        "---",
        "## 📊 Market Snapshot",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Price | {_f(price)} |",
        f"| Market Cap (yfinance) | {_b(mc)} |",
        f"| Shares Outstanding (current) | {shares_str} |",
        f"| Market Cap (price × shares) | {mc_check} |",
        f"| P/E (TTM, GAAP) | {pe_ttm} |",
        f"| Forward P/E | {_f(snap.get('forward_pe'), prefix='', suffix='x', dec=1) if snap.get('forward_pe') else 'N/A'} |",
        f"| EPS (TTM, GAAP) | {_f(snap.get('eps'))} |",
        f"| Dividend Yield | {_f(snap.get('dividend_yield') * 100, prefix='', suffix='%') if snap.get('dividend_yield') else 'N/A'} |",
        f"| 52W High / Low | {_f(hi)} / {_f(lo)} |",
        f"| 52W Position | {pos_52w} |",
        "",
    ]

    # ── multi-year financials ─────────────────────────────────────────────────
    if hist["years"]:
        yrs = hist["years"]
        fy_labels = [f"FY{y}" for y in yrs]
        header = "| Metric | " + " | ".join(fy_labels) + " | YoY |"
        sep    = "|--------|" + "--------|" * len(yrs) + "-----|"

        def row(label, metric, fmt_fn=_b):
            vals = [_v(hist["data"].get(y, {}), metric) for y in yrs]
            cells = " | ".join(fmt_fn(v) for v in vals)
            yoy = _yoy(vals[-1], vals[-2]) if len(vals) >= 2 else "—"
            return f"| {label} | {cells} | {yoy} |"

        def pct_row(label, num_metric, denom_metric):
            cells = []
            for y in yrs:
                yd = hist["data"].get(y, {})
                n, d = _v(yd, num_metric), _v(yd, denom_metric)
                cells.append(_pct(n, d))
            return f"| {label} | " + " | ".join(cells) + " | — |"

        # FCF row
        fcf_vals = []
        for y in yrs:
            yd = hist["data"].get(y, {})
            o, c = _v(yd, "operating_cash_flow"), _v(yd, "capex")
            fcf_vals.append((o - abs(c)) if o is not None and c is not None else None)
        fcf_cells = " | ".join(_b(v) for v in fcf_vals)
        fcf_yoy = _yoy(fcf_vals[-1], fcf_vals[-2]) if len(fcf_vals) >= 2 else "—"

        # FCF margin = FCF / revenue
        fcf_margin_cells = []
        for y, fv in zip(yrs, fcf_vals):
            r = _v(hist["data"].get(y, {}), "revenue")
            fcf_margin_cells.append(_pct(fv, r))

        # Diluted shares YoY change
        sh_vals = [_v(hist["data"].get(y, {}), "diluted_shares") for y in yrs]
        sh_cells = " | ".join(f"{v/1e6:.0f}M" if v else "N/A" for v in sh_vals)
        sh_yoy = _yoy(sh_vals[-1], sh_vals[-2]) if len(sh_vals) >= 2 else "—"

        # SBC as % of revenue
        sbc_pct_cells = []
        for y in yrs:
            yd = hist["data"].get(y, {})
            s, r = _v(yd, "sbc"), _v(yd, "revenue")
            sbc_pct_cells.append(_pct(s, r))

        src_note = f"*Source: SEC EDGAR XBRL / yfinance fallback · FY end: {hist.get('latest_fy_end', 'unknown')}*"
        L += [
            "---",
            "## 📈 Multi-Year Financials",
            "",
            src_note,
            "",
            header, sep,
            row("Revenue", "revenue"),
            row("Gross Profit", "gross_profit"),
            pct_row("  Gross Margin", "gross_profit", "revenue"),
            row("Operating Income", "operating_income"),
            pct_row("  Operating Margin", "operating_income", "revenue"),
            row("Net Income", "net_income"),
            pct_row("  Net Margin", "net_income", "revenue"),
            row("Diluted EPS (GAAP)", "diluted_eps", lambda v: _f(v) if v is not None else "N/A"),
            f"| Diluted Shares (wtd-avg) | {sh_cells} | {sh_yoy} |",
            row("Operating Cash Flow", "operating_cash_flow"),
            row("Capex", "capex"),
            f"| FCF (OCF − Capex) | {fcf_cells} | {fcf_yoy} |",
            f"| FCF Margin (FCF/Rev) | " + " | ".join(fcf_margin_cells) + " | — |",
            row("SBC", "sbc"),
            f"| SBC % of Revenue | " + " | ".join(sbc_pct_cells) + " | — |",
            row("Cash & Equivalents", "cash"),
            row("Short-Term Investments", "short_term_investments"),
            row("Long-Term Debt (noncurrent)", "long_term_debt"),
            row("Short-Term Debt (current)", "short_term_debt"),
            "",
        ]

    # ── latest quarters ──────────────────────────────────────────────────────
    if qhist["quarters"]:
        qs = qhist["quarters"]
        q_labels = [f"Q {p}" for p in qs]
        has_ttm = bool(qhist["ttm"])
        q_header = "| Metric | " + " | ".join(q_labels) + (" | TTM |" if has_ttm else " |")
        q_sep    = "|--------|" + "---------|" * len(qs) + ("---------|" if has_ttm else "")

        def qrow(label, metric):
            vals = [qhist["data"].get(p, {}).get(metric) for p in qs]
            cells = " | ".join(_b(v) for v in vals)
            ttm_cell = _b(qhist["ttm"].get(metric)) if has_ttm else ""
            return f"| {label} | {cells} |" + (f" {ttm_cell} |" if has_ttm else "")

        def qfcf_row():
            vals = []
            for p in qs:
                pd_data = qhist["data"].get(p, {})
                o = pd_data.get("operating_cash_flow")
                c = pd_data.get("capex")
                vals.append((o - abs(c)) if o is not None and c is not None else None)
            cells = " | ".join(_b(v) for v in vals)
            ttm_fcf = qhist["ttm"].get("operating_cash_flow"), qhist["ttm"].get("capex")
            ttm_v = (ttm_fcf[0] - abs(ttm_fcf[1])) if all(v is not None for v in ttm_fcf) else None
            ttm_cell = _b(ttm_v) if has_ttm else ""
            return f"| FCF (OCF − Capex) | {cells} |" + (f" {ttm_cell} |" if has_ttm else "")

        L += [
            "---",
            "## 📊 Latest Quarters",
            "",
            "*Source: SEC EDGAR XBRL 10-Q · quarterly values via YTD subtraction*",
            "",
            q_header, q_sep,
            qrow("Revenue", "revenue"),
            qrow("Operating Income", "operating_income"),
            qrow("Net Income", "net_income"),
            qrow("Operating Cash Flow", "operating_cash_flow"),
            qrow("Capex", "capex"),
            qfcf_row(),
            "",
            "**Latest Balance Sheet** *(as of " + (bs_period or "unknown") + ")*",
            "",
            "| Metric | Value | XBRL Tag |",
            "|--------|-------|----------|",
        ]
        for bm, blabel in [("cash", "Cash"), ("short_term_investments", "Short-Term Investments"),
                            ("long_term_debt", "Long-Term Debt (noncurrent)"),
                            ("short_term_debt", "Short-Term Debt (current)"),
                            ("preferred_stock", "Preferred / Mezz Equity")]:
            entry = bs.get(bm)
            if entry and isinstance(entry, dict):
                L.append(f"| {blabel} | {_b(entry['value'])} | `{entry['tag']}` |")
        L.append("")
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — Latest Quarters (10-Q XBRL not found)\n")

    # ── capital structure ─────────────────────────────────────────────────────
    cs_as_of = f"Q/A as of {bs_period}" if bs_period else f"FY{lfy}"
    cs_cash_label = "Cash & ST Investments" if sti_val else "Cash & Equivalents"
    sti_note = f" *(cash: {cash_tag}, STI: {sti_tag})*" if sti_val else f" *({cash_tag})*"
    debt_note = f" *(LT: {ltd_tag} + ST: {std_tag})*"
    ev_note = " *(MC + debt − cash+STI" + (" + preferred)*" if pref_val else ")*")
    L += [
        "---",
        "## 🏗️ Capital Structure",
        f"*{cs_as_of} · FY end: {hist.get('latest_fy_end', 'unknown')}*",
        "",
        "| Metric | Value | Source |",
        "|--------|-------|--------|",
        f"| {cs_cash_label} | {_b(cash_plus_sti)} | {sti_note.strip()} |",
        f"| Long-Term Debt (noncurrent) | {_b(ltd_val)} | *{ltd_tag}* |",
        f"| Short-Term Debt (current) | {_b(std_val)} | *{std_tag}* |",
        f"| Total Face Debt | {_b(total_debt)} | {debt_note.strip()} |",
        f"| Net Cash (Cash+STI − Debt) | {_b(-net_debt if net_debt is not None else None)} | — |" if net_debt is not None and net_debt > 0 else f"| Net Debt (Debt − Cash+STI) | {_b(net_debt)} | — |",
        f"| Preferred Stock / Mezz Equity | {_b(pref_val)} | *{pref_tag}* |",
        f"| Market Cap | {_b(mc)} | yfinance |",
        f"| Enterprise Value | {_b(ev)} | {ev_note.strip()} |",
        f"| Shares Outstanding (current) | {shares_str} | dei XBRL |",
        "",
    ]

    # ── valuation inputs ──────────────────────────────────────────────────────
    L += [
        "---",
        "## 💰 Valuation Inputs",
        f"*EV={_b(ev)}, MC={_b(mc)}*",
        "",
        "| Multiple | Value | Period |",
        "|----------|-------|--------|",
        f"| EV / Revenue | {ev_rev} | {rev_period} |",
        f"| EV / FCF (OCF − Capex) | {ev_fcf} | {fcf_period} |",
        f"| FCF Yield (FCF/MC) | {fcf_yield} | {fcf_period} |",
        f"| FCF | {_b(fcf_val)} | {fcf_period} |",
        f"| Revenue | {_b(rev_val)} | {rev_period} |",
        f"| P/E (TTM, GAAP) | {pe_ttm} | TTM |",
        f"| Forward P/E | {_f(snap.get('forward_pe'), prefix='', suffix='x', dec=1) if snap.get('forward_pe') else 'N/A'} | fwd |",
        "",
    ]

    # ── analyst ───────────────────────────────────────────────────────────────
    if rat:
        tm = rat.get("target_mean")
        upside = f" ({(tm - price) / price * 100:+.1f}% vs current)" if tm and price else ""
        L += [
            "---",
            "## 🎯 Analyst Consensus",
            "",
            "| | |",
            "|--|--|",
            f"| Recommendation | **{_rec(rat.get('recommendation'))}** |",
            f"| Price Target (mean) | {_f(tm)}{upside} |",
            f"| Target Range | {_f(rat.get('target_low'))} – {_f(rat.get('target_high'))} |",
            f"| # Analysts | {rat.get('num_analysts', 'N/A')} |",
            "",
        ]
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — Analyst Consensus\n")

    # ── earnings ──────────────────────────────────────────────────────────────
    L += ["---", "## 📅 Earnings", "", f"**Next Earnings Date:** {ed.get('next_date') or 'N/A'}", ""]
    if ed.get("history"):
        L += ["| Quarter | Actual EPS (adj) | Estimate (adj) | Surprise |",
              "|---------|-----------------|----------------|----------|",
              "| *Note: yfinance EPS is adjusted (non-GAAP); GAAP EPS in Multi-Year Financials* | | | |"]
        for h in reversed(ed["history"]):
            s = h.get("surprise_pct")
            L.append(f"| {h['period']} | **{_f(h['actual'])}** | {_f(h.get('estimate')) if h.get('estimate') is not None else '—'} | {'🟢' if s and s >= 0 else '🔴'} {f'{s:+.1f}%' if s is not None else '—'} |")
        L.append("")
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — EPS history not found\n")

    # ── insider trades ────────────────────────────────────────────────────────
    L += ["---", "## 🔍 Insider Trades (Form 4)", ""]
    buys, sells = [], []
    for t in trades:
        for tx in t.get("transactions", []):
            s = f"{float(tx['shares']):,.0f} sh @ {_f(float(tx['price']) if tx.get('price') else None)}" if tx.get("shares") else "—"
            entry = f"| {t['date']} | {t['name']} | {t['role']} | {s} |"
            (buys if tx["action"] == "BUY" else sells).append(entry)
    if buys:
        L += ["**BUYS**", "| Date | Name | Role | Transaction |", "|------|------|------|-------------|"]
        L.extend(buys[:5])
        L.append("")
    if sells:
        L += ["**SELLS**", "| Date | Name | Role | Transaction |", "|------|------|------|-------------|"]
        L.extend(sells[:5])
        L.append("")
    if not buys and not sells:
        L.append("> ⚠️ DATA UNAVAILABLE — No insider transactions parsed from Form 4 XML\n")

    # ── macro ─────────────────────────────────────────────────────────────────
    if macro_data and rel_keys:
        L += ["---", "## 🌍 Macro Context (FRED)", "",
              "| Indicator | Value | Δ from Prior |",
              "|-----------|-------|--------------|"]
        for key in rel_keys:
            m = macro_data.get(key, {})
            val, prev = m.get("value"), m.get("prev")
            unit = m.get("unit", "")
            if unit == "index": unit = ""
            val_str = f"{val:.2f}{unit}" if val is not None else "N/A"
            delta = f"{val - prev:+.2f}{unit}" if val is not None and prev is not None else "—"
            L.append(f"| {m.get('label', key)} | {val_str} | {delta} |")
        L.append("")
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — Macro (add FRED_API_KEY to .env)\n")

    # ── peers ──────────────────────────────────────────────────────────────────
    if peers:
        match_label = peers[0].get("match", "sector") if peers else "sector"
        industry_label = snap.get("industry") or snap.get("sector", "")
        L += ["---", f"## 👥 Industry Peers — {industry_label} *(match: {match_label})*",
              "",
              "| Ticker | Name | Price | Mkt Cap | P/E | Fwd P/E | EPS | Match |",
              "|--------|------|-------|---------|-----|---------|-----|-------|"]
        for p in peers:
            L.append(f"| {p['ticker']} | {p['name']} | {_f(p.get('price'))} | {_b(p.get('market_cap'))} | {_f(p.get('pe_ratio'), prefix='', suffix='x') if p.get('pe_ratio') else 'N/A'} | {_f(p.get('forward_pe'), prefix='', suffix='x', dec=1) if p.get('forward_pe') else 'N/A'} | {_f(p.get('eps'))} | {p.get('match','?')} |")
        L.append("")
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — Peers\n")

    # ── news ───────────────────────────────────────────────────────────────────
    if articles:
        L += ["---", "## 📰 Recent News", ""]
        for a in articles:
            L.append(f"- **{a['title']}**  ")
            L.append(f"  *{a['publisher']} · {a['date']}*")
        L.append("")
    else:
        L.append("> ⚠️ DATA UNAVAILABLE — No news found\n")

    # ── overview ───────────────────────────────────────────────────────────────
    if snap.get("description"):
        L += ["---", "## 🏢 Company Overview", "", snap["description"][:1200], ""]

    L += [
        "---",
        f"*Hyper Stink Destroyer Alpha Supreme Pro Max 9000 · {now.strftime('%Y-%m-%dT%H:%M:%SZ')}*",
    ]
    return redact_secrets("\n".join(L))


def redact_secrets(text: str) -> str:
    """Mask any API key values from the environment (exception messages can embed request URLs)."""
    for name, val in os.environ.items():
        if val and len(val) >= 8 and any(s in name.upper() for s in ("KEY", "TOKEN", "SECRET")):
            text = text.replace(val, "***")
    return text
