#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "duckdb",
# ]
# ///
"""
Download paginated domain analytics data from GSA analytics API.

This script downloads data for a full year, stores it in DuckDB,
and exports to Parquet format for further analysis.

Usage:
    export GSA_API_KEY="your-api-key-here"
    ./download_analytics_data.py

    # Resume from a specific page
    ./download_analytics_data.py --start-page 42
"""

import argparse
import os
import sys
import time

import duckdb
import requests

API_URL = "https://api.gsa.gov/analytics/dap/v2.0.0/reports/domain/data"


def fetch_page(
    api_key: str,
    after: str,
    before: str,
    page: int,
    limit: int = 10000,
    max_retries: int = 5,
) -> list:
    headers = {"X-Api-Key": api_key}
    params = {"after": after, "before": before, "limit": limit, "page": page}

    for attempt in range(max_retries):
        try:
            r = requests.get(API_URL, headers=headers, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == max_retries - 1:
                print(f"\n  Failed after {max_retries} attempts")
                raise
            wait = 2**attempt
            print(
                f"\n  Timeout/connection error (attempt {attempt + 1}/{max_retries}), "
                f"retrying in {wait}s..."
            )
            time.sleep(wait)


def fetch_all_data(
    api_key: str,
    start_date: str,
    end_date: str,
    start_page: int = 1,
    limit: int = 10000,
):
    page = start_page
    total_records = 0

    while True:
        try:
            data = fetch_page(api_key, start_date, end_date, page, limit)
        except requests.RequestException as e:
            print(f"\nError fetching page {page}: {e}", file=sys.stderr)
            print("\nTo resume from this page, run:")
            print(f"  uv run download_analytics_data.py --start-page {page}")
            raise

        if not data:
            break

        total_records += len(data)
        print(f"  page {page}: {len(data):,} rows ({total_records:,} in this run)")
        yield from (
            {"date": r["date"], "domain": r["domain"], "visits": r["visits"]}
            for r in data
        )

        if len(data) < limit:
            break

        page += 1
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(
        description="Download GSA analytics data and store in DuckDB"
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Page number to start from (for resuming after errors)",
    )
    parser.add_argument(
        "--start-date",
        default="2024-01-01",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default="2024-12-31",
        help="End date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    api_key = os.getenv("GSA_API_KEY")
    if not api_key:
        print("Error: GSA_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    db_path = "analytics_data.duckdb"
    parquet_path = "analytics_data.parquet.zst"
    batch_size = 1000

    resume = f", resume page {args.start_page}" if args.start_page > 1 else ""
    print(f"Downloading {args.start_date} … {args.end_date} → {db_path}{resume}")

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS domain_analytics (
            date DATE NOT NULL,
            domain VARCHAR NOT NULL,
            visits BIGINT NOT NULL
        )
    """)

    if args.start_page == 1:
        con.execute(
            "DELETE FROM domain_analytics WHERE date >= ? AND date <= ?",
            [args.start_date, args.end_date],
        )

    batch = []
    insert_sql = "INSERT INTO domain_analytics VALUES (?, ?, ?)"

    def flush():
        if batch:
            con.executemany(insert_sql, batch)
            batch.clear()

    for record in fetch_all_data(
        api_key, args.start_date, args.end_date, args.start_page
    ):
        batch.append((record["date"], record["domain"], record["visits"]))
        if len(batch) >= batch_size:
            flush()

    flush()

    result = con.execute("""
        SELECT
            COUNT(*) as total_records,
            COUNT(DISTINCT domain) as unique_domains,
            COUNT(DISTINCT date) as unique_dates,
            MIN(date) as earliest_date,
            MAX(date) as latest_date,
            SUM(visits) as total_visits
        FROM domain_analytics;
    """).fetchone()

    print(
        f"DB: {result[0]:,} rows, {result[1]:,} domains, "
        f"{result[2]:,} dates, {result[3]}–{result[4]}, {result[5]:,} visits"
    )

    con.execute(f"""
        COPY domain_analytics
        TO '{parquet_path}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.close()

    print(f"Parquet: {parquet_path}")


if __name__ == "__main__":
    main()
