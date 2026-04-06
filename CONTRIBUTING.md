# Contributing

## Methodology

We load data into [DuckDB](https://duckdb.org/) from our various sources, with Python scripts to facilitate processing.

### CrUX data

Use the query from [crux-top-list](https://github.com/zakird/crux-top-lists), uses up about 1GB.

```sql
SELECT distinct origin, experimental.popularity.rank
    FROM `chrome-ux-report.experimental.global`
    WHERE yyyymm = ? -- e.g., integer 202210
    GROUP BY origin, experimental.popularity.rank
    ORDER BY experimental.popularity.rank;
```

### analytics.usa.gov

We make use of a [GSA-provided API endpoint](https://open.gsa.gov/api/dap/) to load daily visits data across all domains. See [`download_domain_analytics.py`](./scripts/download_domain_analytics.py). Current data:

| total_records | unique_domains | unique_dates | earliest_date | latest_date | total_visits |
| ------------: | -------------: | -----------: | ------------- | ----------- | -----------: |
|       2719354 |          13949 |          700 | 2024-01-01    | 2025-12-31  |  45924286145 |

We also use the 30-day "top domains" report, to understand how visits correspond to page views. We calculate a ratio per CrUX rank. See [`usa_gov_ratios.py`](./scripts/usa_gov_ratios.py). Ratios:

| crux_rank |       ratio        |
|----------:|-------------------:|
| 1000      | 1.5196271612956924 |
| 5000      | 2.189230320166268  |
| 10000     | 3.144702561255876  |
| 50000     | 2.8478748621843297 |
| 100000    | 2.1925891045844548 |
| 500000    | 3.1621492897281116 |
| 1000000   | 1.921615096341093  |
| 5000000   | 1.7917797110781726 |
| 10000000  | 2.7332945059533627 |
| 50000000  | 1.4732009186595454 |

### Tranco

The [`fetch_tranco_data.py`](./scripts/fetch_tranco_data.py) script loads Tranco data for a specific month:

```bash
./scripts/fetch_tranco_data.py --date 2025-12-31
```

## Tranco full results

One-off export: yearly totals extrapolated from the daily rate (× 365). **Visits** come from the GSA API; **pageviews** use `pageviews_per_day` from [`yearly_pageviews.sql`](./scripts/yearly_pageviews.sql), which applies the USA.gov visits→pageviews ratio (CrUX rank, then hostname, then global—see [`usa_gov_ratios.py`](./scripts/usa_gov_ratios.py)).

```sql
copy (
  select
      domain,
      tranco_rank,
      cast(round(visits_per_day * 365.0) as bigint) as visits_365,
      cast(round(pageviews_per_day * 365.0) as bigint) as pageviews_365,
      visits_to_pageviews_ratio,
      crux_rank,
      days_recorded
  from
      yearly_pageviews
  where
      tranco_rank is not null
  order by
      tranco_rank
) to './tranco-visits-pageviews.csv';
```
