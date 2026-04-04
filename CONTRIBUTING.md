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

We make use of a [GSA-provided API endpoint](https://open.gsa.gov/api/dap/) to load daily page view data across all domains. See [`download_analytics_data.py`](./scripts/download_analytics_data.py). Current data:

| total_records | unique_domains | unique_dates | earliest_date | latest_date | total_visits |
| ------------: | -------------: | -----------: | ------------- | ----------- | -----------: |
|       2719354 |          13949 |          700 | 2024-01-01    | 2025-12-31  |  45924286145 |

### Tranco

The [`fetch_tranco_data.py`](./scripts/fetch_tranco_data.py) script loads Tranco data for a specific month:

```bash
./scripts/fetch_tranco_data.py --date 2025-12-31
```

## Tranco full results

Experimental query, likely unusable as-is:

```sql
copy (
  select
      domain,
      tranco_rank,
      cast(round(visits_per_day * 365.0) as bigint) as pageviews_365,
      crux_rank,
      days_recorded
  from
      yearly_pageviews
  where
    tranco_rank not null
  order by
      tranco_rank
) to './tranco-pageviews.csv';
```
