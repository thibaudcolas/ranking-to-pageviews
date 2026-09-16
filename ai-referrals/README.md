# AI Referrals to US Government Websites

Tracking how much traffic AI assistants (ChatGPT, Perplexity, Claude, Gemini, Copilot) send to US government websites, using public data from the [Digital Analytics Program (DAP)](https://analytics.usa.gov/).

## Quick start

```bash
# Get a free API key at https://api.data.gov/signup/
export GSA_API_KEY=your_key_here

# Run the analysis (uses uv for dependency management)
./ai_referrals.py
```

The script fetches data, prints a summary table, generates charts, and writes a full report to [`REPORT.md`](REPORT.md).

## What it does

1. **Fetches** daily traffic-source data from the [DAP API](https://open.gsa.gov/api/dap/) (v2.0.0), from July 2023 to present
2. **Caches** raw API responses in `.cache/` so re-runs don't re-fetch completed months
3. **Analyzes** traffic patterns, comparing AI referrals to traditional sources (Google, Bing, Direct, Yahoo, DuckDuckGo)
4. **Generates** four charts (PNG + interactive HTML):
   - `ai_referrals_trend` — weekly visits by individual AI source
   - `ai_share_pct` — AI share of total traffic (%) with total traffic volume overlay
   - `ai_vs_traditional` — log-scale comparison of AI total vs traditional sources
   - `traffic_source_mix` — 100% stacked area of all major traffic categories
5. **Writes** a Markdown report ([`REPORT.md`](REPORT.md)) with key metrics, tables, and embedded charts

## Data source

All data comes from the DAP [traffic-source report](https://open.gsa.gov/api/dap/#available-reports), which tracks visits to US federal government websites by referral source. The DAP covers [thousands of government domains](https://analytics.usa.gov/).

AI sources are identified by matching the `source` field: `chatgpt.com`, `claude.ai`, `copilot.com`, `copilot.microsoft.com`, `gemini.google.com`, `perplexity`, `perplexity.ai`.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (dependencies are declared inline via PEP 723, no `requirements.txt` needed)
- A [api.data.gov API key](https://api.data.gov/signup/) in `GSA_API_KEY` (falls back to `DEMO_KEY1`, which has strict rate limits)
