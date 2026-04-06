-- Calculate yearly pageviews per domain (2024 only)
-- This aggregates daily visit data in domain_analytics for calendar year 2024
--
-- The GSA API reports sessions as "visits". We estimate pageviews by multiplying
-- visits by (pageviews/visits) ratios from analytics.usa.gov's live JSON report
-- (see scripts/usa_gov_ratios.py), in this order:
--   1. Per CrUX rank: weighted sum(pageviews)/sum(visits) for USA.gov hosts that
--      match an origin in ``crux`` at that rank (table crux_rank_pageview_ratio).
--   2. Per hostname in the JSON (usa_domain_pageview_ratio).
--   3. Weighted global ratio from the JSON (usa_global_pageview_ratio).

-- CrUX top list (origin + rank). Adjust the URL/snapshot as needed.
-- Use full CrUX dataset if possible.
-- CREATE OR REPLACE TABLE crux AS
-- SELECT *
-- FROM 'https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/global/202512.csv.gz';

-- Restrict analytics rows to 2024 (change bounds here if you switch years)
CREATE OR REPLACE VIEW domain_analytics_2024 AS
SELECT *
FROM domain_analytics
WHERE date >= DATE '2024-01-01'
  AND date < DATE '2025-01-01';

CREATE OR REPLACE VIEW domain_analytics_2025 AS
SELECT *
FROM domain_analytics
WHERE date >= DATE '2025-01-01'
  AND date < DATE '2026-01-01';

CREATE OR REPLACE VIEW yearly_pageviews AS
SELECT
    YEAR(yp.date) AS year,
    yp.domain,
    SUM(yp.visits) AS total_visits,
    COUNT(DISTINCT yp.date) AS days_recorded,
    SUM(yp.visits) / NULLIF(COUNT(DISTINCT yp.date), 0) AS visits_per_day,
    COALESCE(
        MAX(cr_rank.ratio),
        MAX(r.ratio),
        (SELECT ratio FROM usa_global_pageview_ratio LIMIT 1)
    ) AS visits_to_pageviews_ratio,
    (SUM(yp.visits) / NULLIF(COUNT(DISTINCT yp.date), 0))
        * COALESCE(
            MAX(cr_rank.ratio),
            MAX(r.ratio),
            (SELECT ratio FROM usa_global_pageview_ratio LIMIT 1)
        ) AS pageviews_per_day,
    MIN(yp.date) AS first_date,
    MAX(yp.date) AS last_date,
    crux.rank AS crux_rank,
    tranco.rank AS tranco_rank
FROM domain_analytics_2025 AS yp
LEFT JOIN usa_domain_pageview_ratio AS r
    ON regexp_replace(lower(yp.domain), '^www\.', '') = r.hostname_norm
LEFT JOIN crux
    ON yp.domain = regexp_extract(crux.origin, '^(?:https?:\/\/)?([^\/]+)', 1)
LEFT JOIN crux_rank_pageview_ratio AS cr_rank
    ON crux.rank = cr_rank.crux_rank
LEFT JOIN tranco
    ON regexp_extract(yp.domain, '^(?:www\.)?(.+)', 1) = tranco.domain
GROUP BY
    YEAR(yp.date),
    yp.domain,
    crux.rank,
    tranco.rank;

-- Median yearly pageviews (extrapolated from estimated daily pageview rate × 365) per CrUX rank
CREATE OR REPLACE VIEW crux_rank_median_pageviews AS
SELECT
    crux_rank,
    CAST(ROUND(MIN(pageviews_per_day * 365.0)) AS BIGINT) AS min_pageviews,
    CAST(ROUND(MAX(pageviews_per_day * 365.0)) AS BIGINT) AS max_pageviews,
    CAST(ROUND(MEDIAN(pageviews_per_day * 365.0)) AS BIGINT) AS median_pageviews,
    CAST(ROUND(AVG(pageviews_per_day * 365.0)) AS BIGINT) AS avg_pageviews,
    CAST(ROUND(MIN(visits_per_day * 365.0)) AS BIGINT) AS min_visits,
    CAST(ROUND(MAX(visits_per_day * 365.0)) AS BIGINT) AS max_visits,
    CAST(ROUND(MEDIAN(visits_per_day * 365.0)) AS BIGINT) AS median_visits,
    CAST(ROUND(AVG(visits_per_day * 365.0)) AS BIGINT) AS avg_visits,
    COUNT(*) AS count
FROM yearly_pageviews
WHERE
    days_recorded > 365.0 / 2.0
    AND crux_rank IS NOT NULL
GROUP BY crux_rank;
