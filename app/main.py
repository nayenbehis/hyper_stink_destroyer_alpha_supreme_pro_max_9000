"""hyper_stink_destroyer — main Streamlit entrypoint."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import plotly.graph_objects as go
import streamlit as st

from research.ai_analysis import stream_analysis
from research.export import build_export
from research.fundamentals import get_analyst_ratings, get_earnings_data, get_peers, get_price_history, get_snapshot
from research.macro import SERIES as MACRO_SERIES, get_series_for_chart, get_snapshot as get_macro_snapshot, relevant_series
from research.news import get_news
from research.sec import get_insider_trades, get_key_metrics, get_recent_filings

st.set_page_config(
    page_title="HYPER STINK DESTROYER",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'IBM Plex Mono', monospace !important;
    background-color: #111111 !important;
    color: #e0e0e0 !important;
  }
  section[data-testid="stSidebar"] {
    background-color: #111111 !important;
    border-right: 2px solid #b8622a !important;
  }
  input, textarea, select {
    background-color: #111111 !important;
    color: #b8622a !important;
    border: 1px solid #b8622a !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
  }
  .stButton > button {
    background-color: #b8622a !important;
    color: #111111 !important;
    border: none !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
  }
  .stButton > button:hover { background-color: #995020 !important; }
  h1, h2, h3, h4, h5, h6 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #b8622a !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
  }
  hr { border-color: #b8622a !important; opacity: 0.4 !important; }
  [data-testid="metric-container"] {
    background-color: #111111 !important;
    border: 1px solid #2a2a2a !important;
    border-left: 3px solid #b8622a !important;
    padding: 8px 12px !important;
    border-radius: 0 !important;
  }
  [data-testid="metric-container"] label {
    color: #666666 !important;
    font-size: 0.7em !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
  }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #b8622a !important;
    font-size: 1.4em !important;
    font-weight: 600 !important;
  }
  .stAlert {
    border-radius: 0 !important;
    border-left: 3px solid #b8622a !important;
    background-color: #111111 !important;
    color: #e0e0e0 !important;
  }
  .stDataFrame, table { border: 1px solid #2a2a2a !important; }
  .bloomberg-header {
    background-color: #b8622a;
    color: #111111;
    padding: 4px 16px;
    font-size: 0.75em;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    display: flex;
    justify-content: space-between;
    margin-bottom: 16px;
  }
  .ticker-label {
    font-size: 2.5em;
    font-weight: 600;
    color: #b8622a;
    letter-spacing: 0.08em;
  }
  .dim { color: #555555; font-size: 0.8em; }
  .section-label {
    color: #555555;
    font-size: 0.7em;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    border-bottom: 1px solid #2a2a2a;
    padding-bottom: 4px;
    margin-bottom: 12px;
  }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="bloomberg-header">'
    '<span>HYPER STINK DESTROYER ALPHA SUPREME PRO MAX 9000</span>'
    '<span>AI STOCK RESEARCH TERMINAL</span>'
    '</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### `> RESEARCH TERMINAL`")
    st.markdown('<hr/>', unsafe_allow_html=True)
    ticker = st.text_input("TICKER", placeholder="AAPL", max_chars=10).upper()
    period = st.selectbox("CHART PERIOD", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
    run = st.button("EXECUTE RESEARCH", use_container_width=True)
    st.markdown('<hr/>', unsafe_allow_html=True)
    st.markdown('<span class="dim">EDGAR · YFINANCE · FREE</span>', unsafe_allow_html=True)
    _sidebar_export_placeholder = st.empty()


_PERIOD_MONTHS = {"1mo": 2, "3mo": 4, "6mo": 8, "1y": 14, "2y": 26, "5y": 62}


def fmt_large(n):
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"


def fmt_pct(n):
    if n is None:
        return "N/A"
    return f"{n*100:.2f}%"


if not ticker:
    st.markdown("```\n> AWAITING INPUT...\n> ENTER TICKER SYMBOL TO INITIATE RESEARCH\n```")

if run and ticker:
    with st.spinner("FETCHING DATA..."):
        try:
            snap = get_snapshot(ticker)
            st.session_state["snap"] = snap
            st.session_state["ticker"] = ticker
        except Exception as e:
            st.error(f"Could not fetch data for {ticker}: {e}")
            st.stop()

if "snap" in st.session_state and st.session_state.get("ticker") == ticker:
    with _sidebar_export_placeholder.container():
        st.markdown('<hr/>', unsafe_allow_html=True)
        export_md = build_export(ticker, st.session_state["snap"])
        st.download_button(
            label="EXPORT FOR CLAUDE",
            data=export_md,
            file_name=f"{ticker}_research_dossier.md",
            mime="text/markdown",
            use_container_width=True,
        )

if "snap" in st.session_state and st.session_state.get("ticker") == ticker:
    snap = st.session_state["snap"]

    # Header
    price = snap["price"]
    prev = snap["prev_close"]
    change = ((price - prev) / prev) if price and prev else None
    change_str = f"  {'▲' if change and change >= 0 else '▼'} {abs(change)*100:.2f}%" if change is not None else ""

    st.markdown(
        f'<span class="ticker-label">{ticker}</span>'
        f'<span style="color:#888;font-size:1.1em;margin-left:16px">{snap["name"]}</span>'
        f'<span style="color:{"#4caf50" if change and change >= 0 else "#ef5350"};font-size:1.2em;margin-left:12px">{change_str}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<span class="dim">{snap["sector"]} · {snap["industry"]}</span>', unsafe_allow_html=True)
    st.markdown("---")

    # Key metrics row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("PRICE", f"${price:,.2f}" if price else "N/A")
    c2.metric("MKT CAP", fmt_large(snap["market_cap"]))
    c3.metric("P/E", f"{snap['pe_ratio']:.1f}" if snap["pe_ratio"] else "N/A")
    c4.metric("FWD P/E", f"{snap['forward_pe']:.1f}" if snap["forward_pe"] else "N/A")
    c5.metric("EPS", f"${snap['eps']:.2f}" if snap["eps"] else "N/A")
    c6.metric("DIV YIELD", fmt_pct(snap["dividend_yield"]))

    c7, c8, c9, c10, c11, c12 = st.columns(6)
    c7.metric("52W HIGH", f"${snap['52w_high']:,.2f}" if snap["52w_high"] else "N/A")
    c8.metric("52W LOW", f"${snap['52w_low']:,.2f}" if snap["52w_low"] else "N/A")
    c9.metric("VOLUME", f"{snap['volume']:,}" if snap["volume"] else "N/A")
    c10.metric("AVG VOL", f"{snap['avg_volume']:,}" if snap["avg_volume"] else "N/A")
    c11.metric("DAY HIGH", f"${snap['day_high']:,.2f}" if snap["day_high"] else "N/A")
    c12.metric("DAY LOW", f"${snap['day_low']:,.2f}" if snap["day_low"] else "N/A")

    st.markdown("---")

    # Price chart + SEC side by side
    col_chart, col_sec = st.columns([2, 1])

    with col_chart:
        st.markdown('<div class="section-label">PRICE HISTORY</div>', unsafe_allow_html=True)
        with st.spinner("Loading chart..."):
            hist = get_price_history(ticker, period=period)

        if not hist.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["Open"],
                high=hist["High"],
                low=hist["Low"],
                close=hist["Close"],
                increasing_line_color="#b8622a",
                decreasing_line_color="#555555",
                name=ticker,
            ))

            # FRED macro overlay — dotted line on secondary axis
            macro_overlay_label = None
            if os.getenv("FRED_API_KEY") and snap.get("sector"):
                try:
                    rel = relevant_series(snap["sector"])
                    if rel:
                        sk = rel[0]
                        mdata = get_series_for_chart(sk, months=_PERIOD_MONTHS.get(period, 14))
                        if not mdata.empty:
                            macro_overlay_label = MACRO_SERIES[sk]["label"]
                            unit = MACRO_SERIES[sk]["unit"]
                            fig.add_trace(go.Scatter(
                                x=list(mdata.index),
                                y=list(mdata.values),
                                name=macro_overlay_label,
                                line=dict(color="#5a9fd4", width=1.5, dash="dot"),
                                yaxis="y2",
                                opacity=0.8,
                            ))
                except Exception:
                    pass

            layout_kwargs = dict(
                paper_bgcolor="#111111",
                plot_bgcolor="#111111",
                font=dict(family="IBM Plex Mono", color="#e0e0e0", size=11),
                xaxis=dict(gridcolor="#1e1e1e", showgrid=True),
                yaxis=dict(gridcolor="#1e1e1e", showgrid=True),
                margin=dict(l=0, r=0, t=0, b=0),
                xaxis_rangeslider_visible=False,
                height=340,
                legend=dict(bgcolor="#111111", font=dict(size=10)),
            )
            if macro_overlay_label:
                layout_kwargs["yaxis2"] = dict(
                    overlaying="y",
                    side="right",
                    showgrid=False,
                    tickfont=dict(color="#5a9fd4", size=10),
                    title=dict(text=macro_overlay_label, font=dict(size=9, color="#5a9fd4")),
                )
            fig.update_layout(**layout_kwargs)
            st.plotly_chart(fig, use_container_width=True)

    with col_sec:
        st.markdown('<div class="section-label">SEC FILINGS</div>', unsafe_allow_html=True)
        with st.spinner("Fetching EDGAR..."):
            filings = get_recent_filings(ticker, form_type="10-K", limit=5)

        if filings:
            for f in filings:
                st.markdown(
                    f'`{f["form"]}` &nbsp; {f["date"]} &nbsp; '
                    f'[VIEW ↗]({f["edgar_url"]})',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<span class="dim">No 10-K filings found</span>', unsafe_allow_html=True)

        st.markdown('<div class="section-label" style="margin-top:16px">SEC KEY METRICS (XBRL)</div>', unsafe_allow_html=True)
        with st.spinner("Fetching XBRL facts..."):
            try:
                km = get_key_metrics(ticker)
                st.metric("REVENUE", fmt_large(km.get("revenue")))
                st.metric("NET INCOME", fmt_large(km.get("net_income")))
                st.metric("TOTAL ASSETS", fmt_large(km.get("total_assets")))
                st.metric("OP CASH FLOW", fmt_large(km.get("operating_cash_flow")))
            except Exception:
                st.markdown('<span class="dim">XBRL data unavailable</span>', unsafe_allow_html=True)

    # Analyst ratings
    st.markdown("---")
    st.markdown('<div class="section-label">ANALYST CONSENSUS</div>', unsafe_allow_html=True)
    with st.spinner("Fetching analyst data..."):
        try:
            ratings = get_analyst_ratings(ticker)
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("CONSENSUS", str(ratings["recommendation"] or "N/A").upper())
            a2.metric("PRICE TARGET", f"${ratings['target_mean']:,.2f}" if ratings["target_mean"] else "N/A")
            a3.metric("TARGET HIGH", f"${ratings['target_high']:,.2f}" if ratings["target_high"] else "N/A")
            a4.metric("# ANALYSTS", str(ratings["num_analysts"] or "N/A"))
        except Exception:
            st.markdown('<span class="dim">Analyst data unavailable</span>', unsafe_allow_html=True)

    # Earnings calendar
    st.markdown("---")
    st.markdown('<div class="section-label">EARNINGS CALENDAR · EPS HISTORY</div>', unsafe_allow_html=True)
    with st.spinner("Fetching earnings data..."):
        try:
            ed = get_earnings_data(ticker)
            e1, e2 = st.columns([1, 3])
            with e1:
                st.metric("NEXT EARNINGS", ed["next_date"] or "N/A")
            with e2:
                if ed["history"]:
                    st.markdown(
                        '<div style="display:flex;gap:12px;flex-wrap:wrap">',
                        unsafe_allow_html=True,
                    )
                    for h in reversed(ed["history"]):
                        surprise = h.get("surprise_pct")
                        color = "#4caf50" if surprise and surprise >= 0 else "#ef5350"
                        surprise_str = f'<span style="color:{color}"> ({surprise:+.1f}%)</span>' if surprise is not None else ""
                        est_str = f' vs est ${h["estimate"]:.2f}' if h.get("estimate") is not None else ""
                        st.markdown(
                            f'<span class="dim">{h["period"]}</span> &nbsp;'
                            f'<span style="color:#b8622a;font-weight:600">${h["actual"]:.2f}</span>'
                            f'<span class="dim">{est_str}</span>{surprise_str}<br>',
                            unsafe_allow_html=True,
                        )
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.markdown('<span class="dim">No EPS history available</span>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<span class="dim">Earnings data unavailable: {e}</span>', unsafe_allow_html=True)

    # Macro context
    st.markdown("---")
    st.markdown('<div class="section-label">MACRO CONTEXT · FRED</div>', unsafe_allow_html=True)
    if not os.getenv("FRED_API_KEY"):
        st.markdown(
            '<span class="dim">Add FRED_API_KEY to .env for macro data · free at '
            '<a href="https://fred.stlouisfed.org/docs/api/api_key.html" style="color:#b8622a">'
            'fred.stlouisfed.org ↗</a></span>',
            unsafe_allow_html=True,
        )
    else:
        with st.spinner("Fetching FRED macro data..."):
            try:
                rel_keys = relevant_series(snap.get("sector", ""))
                macro_snap = get_macro_snapshot()
                mcols = st.columns(len(rel_keys))
                for i, key in enumerate(rel_keys):
                    m = macro_snap.get(key, {})
                    val = m.get("value")
                    prev_val = m.get("prev")
                    label = m.get("label", key)
                    unit = m.get("unit", "")
                    val_str = f"{val:.2f}{unit}" if val is not None else "N/A"
                    delta_str = f"{(val - prev_val):+.2f}{unit}" if (val is not None and prev_val is not None) else None
                    mcols[i].metric(label.upper(), val_str, delta_str)
            except Exception as e:
                st.markdown(f'<span class="dim">Macro data unavailable: {e}</span>', unsafe_allow_html=True)

    # Insider trades
    st.markdown("---")
    st.markdown('<div class="section-label">INSIDER TRADES · FORM 4</div>', unsafe_allow_html=True)
    with st.spinner("Fetching insider trades..."):
        try:
            trades = get_insider_trades(ticker, limit=10)
        except Exception:
            trades = []

    if trades:
        for t in trades:
            txs = t.get("transactions", [])
            if txs:
                for tx in txs:
                    color = "#4caf50" if tx["action"] == "BUY" else "#ef5350"
                    shares_fmt = f"{float(tx['shares']):,.0f}" if tx["shares"] else "?"
                    price_fmt = f"${float(tx['price']):,.2f}" if tx["price"] else "?"
                    st.markdown(
                        f'<span style="color:{color};font-weight:600">{tx["action"]}</span> &nbsp;'
                        f'<span style="color:#ccc">{t["name"]}</span> &nbsp;'
                        f'<span class="dim">({t["role"]})</span> &nbsp;·&nbsp;'
                        f'<span style="color:#b8622a">{shares_fmt} shares @ {price_fmt}</span> &nbsp;·&nbsp;'
                        f'<span class="dim">{t["date"]}</span>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    f'<span class="dim">{t["date"]} · {t["name"]} · '
                    f'<a href="{t["edgar_url"]}" style="color:#b8622a">VIEW ↗</a></span>',
                    unsafe_allow_html=True,
                )
    else:
        st.markdown('<span class="dim">No recent Form 4 filings found</span>', unsafe_allow_html=True)

    # Peer comparison
    if snap.get("sector"):
        st.markdown("---")
        st.markdown(f'<div class="section-label">SECTOR PEERS · {snap["sector"].upper()}</div>', unsafe_allow_html=True)
        with st.spinner("Fetching peer data..."):
            try:
                peers = get_peers(ticker, snap["sector"], limit=5, industry=snap.get("industry", ""))
            except Exception:
                peers = []

        if peers:
            import pandas as pd
            peer_rows = []
            for p in peers:
                peer_rows.append({
                    "TICKER": p["ticker"],
                    "NAME": p["name"],
                    "PRICE": f"${p['price']:,.2f}" if p["price"] else "N/A",
                    "MKT CAP": fmt_large(p["market_cap"]),
                    "P/E": f"{p['pe_ratio']:.1f}" if p["pe_ratio"] else "N/A",
                    "FWD P/E": f"{p['forward_pe']:.1f}" if p["forward_pe"] else "N/A",
                    "EPS": f"${p['eps']:.2f}" if p["eps"] else "N/A",
                    "52W CHG": f"{p['ytd_change']*100:.1f}%" if p.get("ytd_change") else "N/A",
                })
            df_peers = pd.DataFrame(peer_rows).set_index("TICKER")
            st.dataframe(
                df_peers,
                use_container_width=True,
                height=min(40 + len(peer_rows) * 35, 240),
            )
        else:
            st.markdown('<span class="dim">No peer data available</span>', unsafe_allow_html=True)

    # AI Analysis
    st.markdown("---")
    st.markdown('<div class="section-label">AI RESEARCH NOTE · GROQ</div>', unsafe_allow_html=True)

    api_key_set = bool(os.getenv("GROQ_API_KEY"))
    if not api_key_set:
        st.markdown(
            '<span class="dim">Add GROQ_API_KEY to .env to enable AI analysis. Free at console.groq.com</span>',
            unsafe_allow_html=True,
        )
    else:
        if st.button("GENERATE AI ANALYSIS", use_container_width=False):
            with st.spinner("CLAUDE IS THINKING..."):
                try:
                    km = get_key_metrics(ticker)
                except Exception:
                    km = {}
                try:
                    rat = get_analyst_ratings(ticker)
                except Exception:
                    rat = {}

            try:
                placeholder = st.empty()
                full_text = ""
                for chunk in stream_analysis(ticker, snap, km, rat):
                    full_text += chunk
                    placeholder.markdown(
                        '<div style="background:#0d0d0d;border-left:3px solid #b8622a;'
                        'padding:16px 20px;font-size:0.88em;line-height:1.7;color:#ccc">'
                        + full_text.replace("$", r"\$")
                        + "</div>",
                        unsafe_allow_html=True,
                    )
            except Exception as e:
                st.error(f"AI analysis failed: {e}")

    # News feed
    st.markdown("---")
    st.markdown('<div class="section-label">RECENT NEWS</div>', unsafe_allow_html=True)
    with st.spinner("Fetching news..."):
        try:
            articles = get_news(ticker, limit=8)
        except Exception:
            articles = []

    if articles:
        for a in articles:
            st.markdown(
                f'<div style="margin-bottom:10px;line-height:1.5">'
                f'<a href="{a["url"]}" style="color:#e0e0e0;text-decoration:none;font-size:0.88em" target="_blank">'
                f'{a["title"]}</a><br>'
                f'<span class="dim">{a["publisher"]} &nbsp;·&nbsp; {a["date"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown('<span class="dim">No recent news found</span>', unsafe_allow_html=True)

    # Description
    if snap.get("description"):
        st.markdown("---")
        st.markdown('<div class="section-label">COMPANY OVERVIEW</div>', unsafe_allow_html=True)
        st.markdown(f'<span style="font-size:0.85em;color:#aaa">{snap["description"]}</span>', unsafe_allow_html=True)
