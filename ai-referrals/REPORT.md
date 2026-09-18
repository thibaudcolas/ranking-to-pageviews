# AI Referral Traffic to US Government Websites

Analysis of traffic-source data from the [Digital Analytics Program (DAP)](https://analytics.usa.gov/), covering **2023-07-27** to **2026-08-31**.

Data source: [DAP API v2.0.0](https://open.gsa.gov/api/dap/)  
AI sources tracked: ChatGPT, Claude, Copilot, DeepSeek, Gemini, Grok, Mistral, Perplexity, Poe, You.com

## Data coverage

- Expected coverage: **2023-07-27** to **2026-08-31** (1,132 days); data present for 1,125 days.
- The API does not serve data for 8 known-missing day(s): 2023-07: day(s) 28; 2023-09: day(s) 12; 2023-12: day(s) 13; 2024-03: day(s) 12; 2024-06: day(s) 11; 2024-08: day(s) 21; 2024-12: day(s) 20; 2026-07: day(s) 9.
- Monthly and quarterly figures use complete months only, from **August 2023** (2023-08) to **August 2026** (2026-08).

## Key findings

- **AI referrals account for 0.73% of total tracked traffic** across complete months (431,240,367 of 59,315,481,709 visits).
- In **August 2026** (latest complete month), AI referrals were **1.49%** of total traffic (56,139,211 visits).
- AI referral traffic grew **+311%** from 2025Q1 (24,663,048) to 2026Q2 (101,324,510) — the first complete quarter with meaningful AI traffic to the latest complete quarter (earlier quarters had too little AI data to compare).
- Month-over-month AI referral growth: **-9.2%** (May 2026 to Jun 2026, consecutive complete months).
- Total AI referrals are **26% of Bing traffic** over the period.

## AI referrals by source and year

Complete months only. The first month of the dataset (July 2023) is partial, and the current month is still in progress.

| ai_name    |       2024 |        2025 |        2026 |       Total |
|------------|------------|-------------|-------------|-------------|
| ChatGPT    |  5,217,147 | 160,441,023 | 192,273,767 | 357,931,937 |
| Perplexity |  4,347,990 |  22,194,484 |  14,327,673 |  40,870,147 |
| Gemini     |    847,997 |   6,836,514 |  12,073,253 |  19,757,764 |
| Claude     |     42,403 |   1,519,761 |   4,721,779 |   6,283,943 |
| Copilot    |    306,053 |   2,174,796 |   2,610,568 |   5,091,417 |
| Poe        |    181,258 |     268,916 |      50,704 |     500,878 |
| DeepSeek   |          0 |     468,212 |           0 |     468,212 |
| Grok       |          0 |     168,549 |         950 |     169,499 |
| You.com    |     64,353 |      38,740 |       6,629 |     109,722 |
| Mistral    |          0 |      29,179 |      27,669 |      56,848 |
| **ALL AI** | 11,007,201 | 194,140,174 | 226,092,992 | 431,240,367 |

## AI share of total traffic by year

Complete years only for comparisons; partial years are annotated. The current year is still in progress.

| Year | Total Traffic | AI Referrals | AI Share |
|------|--------------|-------------|----------|
| 2023 (partial year) | 3,466,038,012 | 0 | 0.000% |
| 2024 (partial year) | 13,392,507,469 | 11,007,201 | 0.082% |
| 2025 | 21,295,719,886 | 194,140,174 | 0.912% |
| 2026 (partial year) | 21,161,216,342 | 226,092,992 | 1.068% |

## Peak AI referral weeks

| Week Starting | Total AI Visits |
|--------------|----------------|
| 2026-08-24 | 13,937,958 |
| 2026-08-10 | 13,915,996 |
| 2026-08-17 | 12,538,109 |
| 2026-08-03 | 11,733,866 |
| 2026-05-18 | 9,852,268 |

## Charts

### AI referral trends by source
![AI referral trends](./assets/ai_referrals_trend.png)

### AI share of total traffic and overall traffic volume
![AI share and total traffic](./assets/ai_share_pct.png)

### AI referrals vs traditional traffic sources
![AI vs traditional](./assets/ai_vs_traditional.png)

### Traffic source mix (100% stacked)
![Traffic source mix](./assets/traffic_source_mix.png)

## Methodology

- Data from the [DAP API](https://open.gsa.gov/api/dap/) `traffic-source` report (v2.0.0), fetched daily and stored in DuckDB.
- Date range: 2023-07-27 to 2026-08-31.
- AI sources identified by normalized `source` field matching: `anthropic.com`, `chat.deepseek.com`, `chat.mistral.ai`, `chat.openai.com`, `chatgpt.com`, `claude.ai`, `copilot.cloud.microsoft`, `copilot.com`, `copilot.microsoft.com`, `copilotstudio.microsoft.com`, `gemini.google.com`, `grok.com`, `openai`, `perplexity`, `perplexity.ai`, `poe.com`, `x.ai`, `you.com`.
- "(direct)" and "(other)" traffic is classified under Direct and Other respectively.
- Percentages are based on total visits across all sources in the traffic-source report.
