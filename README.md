# AlphaForge

An AI-powered stock research platform that combines SEC EDGAR filings, fundamental financial data, and Claude to help you research stocks deeply.

**Data sources:** SEC EDGAR · Financial Modeling Prep · Alpha Vantage · FRED  
**AI:** Anthropic Claude  
**UI:** Streamlit

## Setup

### 1. Clone and create a virtual environment

```bash
cd alphaforge
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

| Key | Where to get it |
|-----|----------------|
| `SEC_API_KEY` | https://sec-api.io |
| `ALPHA_VANTAGE_KEY` | https://www.alphavantage.co/support/#api-key |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys |
| `FMP_API_KEY` | https://site.financialmodelingprep.com/developer/docs |

### 4. Run the app

```bash
streamlit run app/main.py
```

## Alternative data (`hyperstink altdata`)

Pull public data trails that don't show up in filings. Each source writes a `.md` and `.csv` to `--out`; outputs keep all caveat lines so you know what each number can and can't prove.

### Run everything at once

```bash
hyperstink altdata all BFAM \
  --site https://www.brighthorizons.com \
  --match /daycare-centers/ \
  --jobs-query "Bright Horizons" \
  --app com.brighthorizons.backupcare
# writes research_runs/BFAM_altdata/ALTDATA.md
```

### Per-source examples (BFAM)

**Sitemap** — count location pages over time:
```bash
hyperstink altdata sitemap https://www.brighthorizons.com \
  --match /daycare-centers/ \
  --out research_runs/BFAM_altdata/
```

**Wayback** — track a number on a specific page:
```bash
hyperstink altdata wayback https://www.brighthorizons.com/child-care \
  --number "([0-9,]+)\s+locations" \
  --out research_runs/BFAM_altdata/
```

**Insiders** — SEC Form 4 open-market trades:
```bash
hyperstink altdata insiders BFAM --days 365 \
  --out research_runs/BFAM_altdata/
```

**Jobs** — hiring snapshot with weekly trend:
```bash
hyperstink altdata jobs "Bright Horizons" \
  --company "Bright Horizons" \
  --history research_runs/BFAM_altdata/jobs_history.csv \
  --out research_runs/BFAM_altdata/
```

**Reddit** — mention volume by month:
```bash
hyperstink altdata reddit BFAM \
  --subs stocks,investing,ValueInvesting \
  --out research_runs/BFAM_altdata/
# Needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env
```

**Reviews** — Google Play ratings by month:
```bash
hyperstink altdata reviews com.brighthorizons.backupcare \
  --out research_runs/BFAM_altdata/
```

---

## `screen` — find good, cheap, ignored stocks

Code-only screener. No LLM calls. Fetches the SEC XBRL frames API (all companies
per concept per call) and yfinance prices, filters, then scores by cheapness,
quality, and neglect.

```bash
# Full run — writes research_runs/screen_YYYY-MM-DD/SCREEN.md + results.csv
python3 cli.py screen

# Or via the CLI entrypoint after `pip install -e .`
hyperstink screen

# Narrow to micro/nano caps
hyperstink screen --min-cap 50e6 --max-cap 500e6

# Show top 50
hyperstink screen --top 50

# Force-refresh all caches (fetches fresh data from SEC + yfinance)
hyperstink screen --refresh
```

### Phase-2 special lanes

```bash
# Companies with ≥2 insider buy filings in the last 90 days
hyperstink screen --lane insiders

# Recent spinoff registrations (10-12B/G stubs, last 365 days)
hyperstink screen --lane spinoffs

# Recent activist disclosures (SC 13D filings, last 180 days)
hyperstink screen --lane activists
```

### Scoring weights (all percentile-ranked 0–100 within the passing universe)

| Dimension | Weight | Components |
|-----------|--------|------------|
| Cheapness | 40%    | FCF yield, EV/EBIT, P/B, % below 5-yr high |
| Quality   | 30%    | FCF consistency, operating margin, net-debt/EBIT |
| Neglect   | 30%    | analyst count, news count, institutional %, market cap |

### Filters applied before scoring

- Market cap $200M–$5B (adjustable via `--min-cap` / `--max-cap`)
- Avg daily dollar volume ≥ $500K
- ≥5 fiscal years of revenue data in SEC XBRL
- OCF positive ≥4 of last 5 years; FCF positive ≥3 of last 5 years
- Net-debt/EBIT ≤ 3 (net-cash companies always pass)
- Revenue CAGR > -5%
- Excludes financials, banks, REITs by SIC 6000–6999 (use `--include-financials` to keep)

---

## Project structure

```
hyper_stink_destroyer_alpha_supreme_pro_max_9000/
├── app/                    # Streamlit pages and UI
├── research/
│   ├── altdata/            # Alternative data sources (sitemap, insiders, jobs, …)
│   ├── screen/             # Code-only stock screener
│   │   ├── sec.py          # SEC XBRL frames API + universe loader
│   │   ├── prices.py       # yfinance batch price fetcher
│   │   ├── metrics.py      # Pure metric computation (FCF, debt, ratios)
│   │   ├── filters.py      # Quality / size / tradability filters
│   │   ├── scoring.py      # Percentile-rank scoring
│   │   ├── output.py       # CSV / Markdown / terminal output
│   │   ├── lanes.py        # Phase-2 special lanes (insiders, spinoffs, activists)
│   │   └── cache.py        # 7-day file-based JSON cache
│   ├── fundamentals.py     # FMP + Alpha Vantage fetchers
│   └── sec.py              # SEC EDGAR fetcher
├── strategies/             # Analysis and scoring modules
├── data/                   # Local DuckDB + screen_cache/
└── tests/                  # Pytest suite (offline fixture-based)
```
