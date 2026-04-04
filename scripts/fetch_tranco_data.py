#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tranco",
#     "duckdb",
# ]
# ///
"""
Fetch Tranco rankings and store them in DuckDB.

This script downloads the latest Tranco list (or a specific date/list_id)
and stores it in a DuckDB table for analysis.

Usage:
    # Fetch latest list
    ./fetch_tranco_data.py
"""

import argparse
import sys
from itertools import islice

import duckdb
from tranco import Tranco


def batched(iterable, n: int):
    it = iter(iterable)
    while True:
        batch = list(islice(it, n))
        if not batch:
            break
        yield batch


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Tranco rankings and store in DuckDB"
    )
    parser.add_argument(
        "--date",
        help="Date of the list to fetch (YYYY-MM-DD). If not specified, fetches latest.",
    )
    parser.add_argument(
        "--db-path",
        default="analytics_data.duckdb",
        help="Path to DuckDB database (default: analytics_data.duckdb)",
    )
    args = parser.parse_args()

    t = Tranco(cache=True, cache_dir=".tranco")
    try:
        tranco_list = t.list(date=args.date) if args.date else t.list()
    except Exception as e:
        print(f"Error fetching Tranco list: {e}", file=sys.stderr)
        sys.exit(1)

    # dict[str, int]: domain -> rank (1..N)
    ranks: dict[str, int] = tranco_list.list

    con = duckdb.connect(args.db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS tranco (
            domain VARCHAR NOT NULL,
            rank INTEGER NOT NULL
        )
    """)
    con.execute("DELETE FROM tranco")

    batch_size = 10_000
    insert_sql = "INSERT INTO tranco VALUES (?, ?)"
    for batch in batched(ranks.items(), batch_size):
        con.executemany(insert_sql, batch)

    result = con.execute("SELECT COUNT(*), MIN(rank), MAX(rank) FROM tranco").fetchone()

    parquet_path = "tranco_data.parquet.zst"
    con.execute(f"""
        COPY tranco
        TO '{parquet_path}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.close()

    n, lo, hi = result
    label = args.date or tranco_list.list_id
    if n == 0:
        print(f"Tranco {label} → {args.db_path}: 0 rows")
    else:
        print(f"Tranco {label} → {args.db_path}: {n:,} rows, ranks {lo:,}–{hi:,}")


if __name__ == "__main__":
    main()
