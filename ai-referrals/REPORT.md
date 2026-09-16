# AI Referral Traffic to US Government Websites

Analysis of traffic-source data from the [Digital Analytics Program (DAP)](https://analytics.usa.gov/), covering **2023-08-01** to **2026-09-01**.

Data source: [DAP API v2.0.0](https://open.gsa.gov/api/dap/)  
AI sources tracked: ChatGPT, Perplexity, Claude, Gemini, Copilot

## Key findings

- **AI referrals account for 0.64% of total tracked traffic** (442,496,512 of 69,357,561,696 visits).
- In **September 2026**, AI referrals were **1.92%** of total traffic (2,560,310 visits).
- AI referral traffic grew **+6,462%** from 2024Q2 (1,396,471) to 2026Q3 (91,630,430).
- Month-over-month AI referral growth: **-95.4%** (Aug 2026 to Sep 2026).
- Total AI referrals are **23% of Bing traffic** over the period.
- Overall traffic changed **+1.6%** year-over-year (2024: 20,956,859,831 → 2025: 21,295,719,886).

## AI referrals by source and year

| ai_name    | 2024       | 2025        | 2026        | Total       |
| ---------- | ---------- | ----------- | ----------- | ----------- |
| ChatGPT    | 8,693,195  | 160,177,984 | 199,642,891 | 368,514,070 |
| Perplexity | 7,241,106  | 22,194,484  | 13,645,853  | 43,081,443  |
| Gemini     | 1,421,685  | 6,836,514   | 11,554,667  | 19,812,866  |
| Claude     | 62,696     | 1,519,761   | 4,711,490   | 6,293,947   |
| Copilot    | 493,263    | 1,993,285   | 2,307,638   | 4,794,186   |
| **ALL AI** | 17,911,945 | 192,722,028 | 231,862,539 | 442,496,512 |

## AI share of total traffic by year

| Year | Total Traffic  | AI Referrals | AI Share |
| ---- | -------------- | ------------ | -------- |
| 2023 | 5,738,911,492  | 0            | 0.000%   |
| 2024 | 20,956,859,831 | 17,911,945   | 0.085%   |
| 2025 | 21,295,719,886 | 192,722,028  | 0.905%   |
| 2026 | 21,366,070,487 | 231,862,539  | 1.085%   |

## Peak AI referral weeks

| Week Starting | Total AI Visits |
| ------------- | --------------- |
| 2026-08-24    | 13,903,268      |
| 2026-08-10    | 13,877,195      |
| 2026-08-17    | 12,499,918      |
| 2026-08-03    | 11,696,906      |
| 2026-05-18    | 9,790,547       |

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

- Data from the [DAP API](https://open.gsa.gov/api/dap/) `traffic-source` report (v2.0.0).
- Date range: 2023-08-01 to 2026-09-01.
- AI sources identified by `source` field matching: `chatgpt.com`, `claude.ai`, `copilot.com`, `copilot.microsoft.com`, `gemini.google.com`, `perplexity`, `perplexity.ai`.
- "(direct)" and "(other)" traffic is classified under Direct and Other respectively.
- Percentages are based on total visits across all sources in the traffic-source report.
