# Contributing

## How the data pipeline works

`ai_referrals.py` fetches daily traffic-source reports from the [DAP API](https://open.gsa.gov/api/dap/)
and stores every raw record (one row per source per day) in a DuckDB database:

```
data/traffic.duckdb        DuckDB database (primary working store)
data/traffic.parquet.zst   Single-file copy of the same data, stored in Git LFS
assets/                    Generated charts (PNG + interactive HTML)
REPORT.md                  Generated analysis report
```

The parquet file is the canonical copy for Git: the DuckDB file is a local
build artifact (do not commit it). On a fresh clone, the script rebuilds
`data/traffic.duckdb` from `data/traffic.parquet.zst` automatically.

### Incremental fetching

The script only fetches days that are missing from the database:

1. It computes every expected day from the first day the API serves
   (2023-07-27) to the last day of the last complete month.
2. Days absent from the database are fetched in contiguous ranges and inserted
   with `INSERT OR IGNORE` (deduplication by record `id`).
3. Days the API genuinely does not serve are listed in `KNOWN_GAPS` at the top
   of the script, so they are never re-fetched. As of September 2026 these
   are: 2023-07-01 to 2023-07-28, plus 8 single days (2023-09-12, 2023-12-13,
   2024-03-12, 2024-06-11, 2024-08-21, 2024-12-20, 2026-07-09).
4. The full database is re-exported to `data/traffic.parquet.zst` after each run.

If a new missing day appears (e.g. the API drops a recent day), the report's
"Data coverage" section flags it as an *unexpected* missing day. Once confirmed
unavailable via the API, add it to `KNOWN_GAPS`.

### Updating END_DATE

`END_DATE` is pinned to the last complete month at the time of writing
(2026-08-31). To roll the analysis forward, set it to the last day of the new
last complete month, or compute it dynamically:

```python
today = date.today()
END_DATE = (today.replace(day=1) - timedelta(days=1))
```

The monthly, quarterly, and yearly figures all restrict themselves to complete
months/quarters/years, so a stale `END_DATE` never produces partial-period
numbers — it just omits newer months.

## Setting up Git LFS for the parquet file

The dataset is ~23 MB compressed, so it is tracked with Git LFS:

```bash
git lfs install
git lfs track "data/*.parquet.zst"
git add .gitattributes data/traffic.parquet.zst
git commit -m "Track dataset in Git LFS"
```

`.gitattributes` must be committed *before* (or with) the parquet file, so Git
stores it as an LFS pointer rather than a full blob.

## Running

```bash
export GSA_API_KEY=your_key   # free key: https://api.data.gov/signup/
./ai_referrals.py
```

Dependencies are declared inline (PEP 723) and resolved by
[`uv`](https://docs.astral.sh/uv/). `DEMO_KEY1` is used as fallback but has
strict rate limits — a real key is strongly recommended for initial fetches.

## Data caveats

- AI sources are identified by matching the `source` field after
  normalization (lowercased, URL paths and trailing debris stripped). The
  mapping lives in `AI_SOURCES` at the top of the script. New AI assistants
  appear over time — check the report's "Data coverage" and the raw source
  values when numbers look off.
- The API's `traffic-source` report only reflects DAP-participating domains
  and includes non-`.gov` hosts (e.g. `ait.org.tw`); there is no per-domain
  filter on the aggregate report.
- Visit counts are per (day, source) across all DAP domains; there is no
  per-domain breakdown at this aggregation level.
