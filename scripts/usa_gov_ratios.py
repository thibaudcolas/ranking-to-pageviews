#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "duckdb",
# ]
# ///
"""
Load screenPageViews / sessions ratios from analytics.usa.gov's public JSON report.

The GSA DAP API exposes daily session counts as "visits"; the live JSON report at
https://analytics.usa.gov/data/live/top-100000-domains-30-days.json includes both
pageviews and visits per hostname so we can estimate pageviews from visits.

Ratios are stored in DuckDB for use by yearly_pageviews.sql:

- ``usa_domain_pageview_ratio``: per-hostname (pageviews/visits) from the JSON.
- ``usa_global_pageview_ratio``: weighted global ratio from the JSON.
- ``crux_rank_pageview_ratio``: per CrUX ``rank``, for origins in ``crux`` that also
  appear in the JSON (weighted sum(pageviews)/sum(visits) per rank). Requires a
  populated ``crux`` table in the same database.

When estimating pageviews, ``yearly_pageviews.sql`` prefers the CrUX-rank ratio,
then hostname, then global.

Usage:
    ./scripts/usa_gov_ratios.py
    ./scripts/usa_gov_ratios.py --db /path/to/analytics_data.duckdb
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from urllib.error import URLError

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR / ".." / "analytics_data.duckdb"

USA_GOV_TOP_DOMAINS_JSON = (
    "https://analytics.usa.gov/data/live/top-100000-domains-30-days.json"
)

# Same hostname extraction as scripts/yearly_pageviews.sql (crux join), plus www strip
# to align with JSON ``hostname_norm``.
_CRUX_HOST_SQL = """
    regexp_replace(
        lower(regexp_extract(crux.origin, '^(?:https?:\\/\\/)?([^\\/]+)', 1)),
        '^www\\.',
        ''
    )
"""


def normalize_hostname(hostname: str) -> str:
    h = hostname.strip().lower()
    if h.startswith("www."):
        return h[4:]
    return h


def fetch_top_domains_rows() -> list[dict]:
    req = urllib.request.Request(
        USA_GOV_TOP_DOMAINS_JSON,
        headers={"User-Agent": "ranking-to-pageviews/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.load(resp)
    return list(payload["data"])


def _load_json_staging(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _usa_json_staging (
            hostname_norm VARCHAR NOT NULL,
            pageviews BIGINT NOT NULL,
            visits BIGINT NOT NULL
        )
    """)
    batch = [
        (normalize_hostname(r["hostname"]), int(r["pageviews"]), int(r["visits"]))
        for r in rows
        if int(r["visits"]) > 0
    ]
    if not batch:
        raise ValueError("No valid visits in USA.gov JSON data")
    con.executemany("INSERT INTO _usa_json_staging VALUES (?, ?, ?)", batch)


def populate_usa_gov_ratios(con: duckdb.DuckDBPyConnection) -> None:
    """Create or replace ratio tables from the live JSON report and optional ``crux``."""
    rows = fetch_top_domains_rows()
    _load_json_staging(con, rows)

    global_ratio = con.execute("""
        SELECT SUM(pageviews)::DOUBLE / SUM(visits) FROM _usa_json_staging
    """).fetchone()[0]
    if global_ratio is None or global_ratio <= 0:
        raise ValueError("Could not compute global pageviews/visits ratio from JSON")

    con.execute("""
        CREATE OR REPLACE TABLE usa_domain_pageview_ratio AS
        SELECT
            hostname_norm,
            SUM(pageviews)::DOUBLE / SUM(visits) AS ratio
        FROM _usa_json_staging
        GROUP BY hostname_norm
    """)

    con.execute("""
        CREATE OR REPLACE TABLE usa_global_pageview_ratio (
            id INTEGER PRIMARY KEY,
            ratio DOUBLE NOT NULL
        )
    """)
    con.execute(
        "INSERT INTO usa_global_pageview_ratio (id, ratio) VALUES (1, ?)",
        [global_ratio],
    )

    con.execute("""
        CREATE OR REPLACE TABLE crux_rank_pageview_ratio (
            crux_rank BIGINT NOT NULL PRIMARY KEY,
            ratio DOUBLE NOT NULL
        )
    """)
    try:
        con.execute(f"""
            INSERT INTO crux_rank_pageview_ratio (crux_rank, ratio)
            SELECT
                crux.rank AS crux_rank,
                SUM(s.pageviews)::DOUBLE / SUM(s.visits) AS ratio
            FROM crux
            INNER JOIN _usa_json_staging AS s
                ON {_CRUX_HOST_SQL} = s.hostname_norm
            WHERE s.visits > 0
            GROUP BY crux.rank
        """)
    except duckdb.Error:
        # ``crux`` missing or unreadable; keep empty rank table (fallback to hostname/global).
        pass


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*) FROM duckdb_tables()
        WHERE table_name = ?
        """,
        [name],
    ).fetchone()
    return row is not None and row[0] > 0


def ensure_usa_gov_ratios(con: duckdb.DuckDBPyConnection) -> None:
    """Populate ratio tables if they are missing or empty (e.g. older DBs)."""
    try:
        n = con.execute("SELECT COUNT(*) FROM usa_global_pageview_ratio").fetchone()[0]
        if n > 0 and _table_exists(con, "crux_rank_pageview_ratio"):
            return
    except duckdb.Error:
        pass
    populate_usa_gov_ratios(con)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch USA.gov pageviews/visits ratios into DuckDB tables "
        "(usa_domain_pageview_ratio, usa_global_pageview_ratio, "
        "crux_rank_pageview_ratio when crux is present)."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"DuckDB file to write (default: {DEFAULT_DB.name})",
    )
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.db))
    try:
        populate_usa_gov_ratios(con)
        hosts = con.execute(
            "SELECT COUNT(*) FROM usa_domain_pageview_ratio"
        ).fetchone()[0]
        ratio = con.execute(
            "SELECT ratio FROM usa_global_pageview_ratio LIMIT 1"
        ).fetchone()[0]
        ranks = con.execute("SELECT COUNT(*) FROM crux_rank_pageview_ratio").fetchone()[
            0
        ]
    except (OSError, URLError, ValueError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        con.close()

    print(f"Wrote {args.db}")
    print(f"  Hostname ratios: {hosts:,}")
    print(f"  CrUX rank ratios: {ranks:,}")
    print(f"  Global ratio (pageviews/visits): {ratio:.6f}")


if __name__ == "__main__":
    main()
