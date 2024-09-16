# Ranking to pageviews

An attempt at extrapolating likely pageview counts based on website rankings in the [CrUX](https://developer.chrome.com/docs/crux) and [Tranco](https://tranco-list.eu/) datasets. Pageview data comes from [analytics.usa.gov](https://analytics.usa.gov/).

## Data sources

| Source                                          | Description                                                                    | Last updated |
| ----------------------------------------------- | ------------------------------------------------------------------------------ | ------------ |
| [analytics.usa.gov](https://analytics.usa.gov/) | Top hostnames, 30 days (10k websites)                                          | 2024-09-09   |
| [Tranco](https://tranco-list.eu/)               | "latest list", 30 days (1M websites)                                           | 2024-09-09   |
| [CrUX](https://developer.chrome.com/docs/crux)  | [Cached Chrome Top Million Websites](https://github.com/zakird/crux-top-lists) | 2024-08-14   |

## Results

|  CrUX Rank | Pageviews (median) | Extrapolated |
| ---------: | -----------------: | -----------: |
|      1,000 |      3,743,794,604 |              |
|      5,000 |        969,861,891 |              |
|     10,000 |        505,802,570 |              |
|     50,000 |        105,333,939 |              |
|    100,000 |         33,557,875 |              |
|    500,000 |          7,759,115 |              |
|  1,000,000 |          2,335,489 |              |
|  5,000,000 |                    |      612,733 |
| 10,000,000 |                    |      293,886 |
| 50,000,000 |                    |       53,367 |

5M, 10M, 50M values extrapolated based on a power series trend line of `7.73E+12x^-1.06`. R² = 0.992.

View the data in Google Sheets: [CrUX rank to pageviews](https://docs.google.com/spreadsheets/d/14kjXr9clXqH4mEhXpkutlUTkNtJrb0OxX8VaQMoEHVA/edit?gid=0#gid=0)

[![Yearly pageviews by CrUX rank (log scale)](./yearly-pageviews-by-crux-rank.png)](./yearly-pageviews-by-crux-rank.png)

The above results are based on CrUX ranks only. Tranco ranks results are shared below for reference.

## Methodology

With [DuckDB](https://duckdb.org/):

```sql
create table tranco as select * from './top-1m.csv';
create table analytics as select * from './top-10000-domains-30-days.csv';
create table crux as select * from './20240814-crux-current.csv';
create table mapping as (
  select
    a.hostname,
    crux.origin as crux_origin,
    column1 as tranco_domain,
    a.pageviews,
    a.visits,
    rank as crux_rank,
    column0 as tranco_rank,
  from analytics a
  -- CrUX has full origins including protocol. Analytics data uses domain only.
  join crux on a.hostname = regexp_extract(crux.origin, '^(?:https?:\/\/)?([^\/]+)', 1)
  -- Tranco has a tendency to use root domains even for sites served on www.
  left join tranco on regexp_extract(a.hostname, '^(?:www\.)?(.+)', 1) = tranco.column1
  order by rank asc
);
copy(select * from mapping) to './crux-tranco-analytics-mapping.csv';
```

## CrUX full results

Pageview scores are given for 365 days.

| crux_rank | min_pageviews | max_pageviews | median_pageviews | avg_pageviews | count |
| --------: | ------------: | ------------: | ---------------: | ------------: | ----: |
|      1000 |    2944146696 |    4543442510 |       3743794603 |    3743794603 |     2 |
|      5000 |          2615 |    4086099226 |        969861891 |    1160648800 |    17 |
|     10000 |      77886985 |    1670330142 |        505802570 |     546856260 |     8 |
|     50000 |          1606 |     720381544 |        105333938 |     140603434 |    55 |
|    100000 |          2932 |     390257476 |         33557874 |      50807897 |    70 |
|    500000 |          1399 |    1249634537 |          7759115 |      18421315 |   336 |
|   1000000 |          1679 |      67022845 |          2335489 |       3763187 |   283 |

```sql
select
    crux_rank,
    min(pageviews * 365.0 / 30.0) as min_pageviews_365,
    max(pageviews * 365.0 / 30.0) as max_pageviews_365,
    median(pageviews * 365.0 / 30.0) as median_pageviews_365,
    avg(pageviews * 365.0 / 30.0) as avg_pageviews_365,
    count(pageviews) as count_pageviews
from
    mapping
group by
    crux_rank
order by
    crux_rank;
```

## Tranco full results

TODO: describe results and pitfalls.

```sql
copy (
  select
      tranco_domain,
      tranco_rank,
      pageviews * 365.0 / 30.0 as pageviews_365,
      crux_rank
  from
      mapping
  where
    tranco_rank not null
  order by
      tranco_rank
) to './tranco-pageviews.csv';
```

## Caveats

- CrUX ranks origins (including protocol and full), while Tranco ranks hostnames.
- Only 771 data points are available, 80% of which are for the 500k/1M ranks.
- The date ranges differ, so the site traffic reflected in the ranks and page views are for different time periods.
- The pageviews dataset is for websites primarily intended for a USA audience, while the rankings are global.
- Yearly pageview data is extrapolated from a specific 30-day period over the summer months in North America.
- There is no data for CrUX ranks above 1M (5M, 10M, 50M).
