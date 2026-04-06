#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "duckdb",
#     "pandas",
#     "numpy",
#     "matplotlib",
#     "seaborn",
#     "scipy",
# ]
# ///
"""
Load views from yearly_pageviews.sql, summarize median yearly pageviews per CrUX rank,
fit a log–log (power-law) regression, extrapolate to high ranks, and plot (Seaborn/Matplotlib).

Requires an existing DuckDB database with `domain_analytics`, `crux`, and `tranco` tables
as expected by yearly_pageviews.sql (CrUX load is commented there if you maintain it separately).

Usage:
    ./analyze_crux_pageviews.py
    ./analyze_crux_pageviews.py --db analytics_data.duckdb --output chart.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.ticker import EngFormatter
from scipy.stats import linregress

from usa_gov_ratios import ensure_usa_gov_ratios

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SQL = SCRIPT_DIR / "yearly_pageviews.sql"
DEFAULT_DB = SCRIPT_DIR / ".." / "analytics_data.duckdb"
DEFAULT_OUTPUT = SCRIPT_DIR / ".." / "yearly-pageviews-by-crux-rank.png"

EXTRAPOLATION_RANKS = (5_000_000, 10_000_000, 50_000_000, 100_000_000)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CrUX rank vs median yearly pageviews — regression and chart"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"DuckDB file (default: {DEFAULT_DB.name})",
    )
    parser.add_argument(
        "--sql",
        type=Path,
        default=DEFAULT_SQL,
        help=f"SQL setup script (default: {DEFAULT_SQL.name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"PNG path (default: {DEFAULT_OUTPUT.name})",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    if not args.sql.is_file():
        print(f"SQL file not found: {args.sql}", file=sys.stderr)
        sys.exit(1)

    sql_text = args.sql.read_text()
    con = duckdb.connect(str(args.db))
    try:
        ensure_usa_gov_ratios(con)
        con.execute(sql_text)
        df = con.execute(
            """
            SELECT crux_rank, median_pageviews, count
            FROM crux_rank_median_pageviews
            WHERE median_pageviews IS NOT NULL AND median_pageviews > 0
            ORDER BY crux_rank
            """
        ).df()
    except duckdb.Error as e:
        print(
            f"DuckDB error (check crux / domain_analytics / tranco): {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        con.close()

    if len(df) < 2:
        print(
            "Need at least 2 CrUX ranks with positive median pageviews. Got "
            f"{len(df)} row(s).",
            file=sys.stderr,
        )
        sys.exit(1)

    x = df["crux_rank"].to_numpy(dtype=float)
    y = df["median_pageviews"].to_numpy(dtype=float)
    log_x = np.log10(x)
    log_y = np.log10(y)
    reg = linregress(log_x, log_y)
    r2 = reg.rvalue**2
    slope = reg.slope
    intercept = reg.intercept

    # y = 10^intercept * x^slope  on linear axes; power-law coefficient for legend
    coef = 10.0**intercept

    # Red points: preset ranks strictly above the max CrUX rank in the data
    extrap_ranks = np.array(
        [r for r in EXTRAPOLATION_RANKS if r > x.max()],
        dtype=float,
    )
    extrap_y = 10.0 ** (intercept + slope * np.log10(extrap_ranks))

    # Smooth trend line (log–log straight line)
    x_line = np.logspace(np.log10(x.min()), np.log10(1e8), 400)
    y_line = 10.0 ** (intercept + slope * np.log10(x_line))

    sns.set_theme(style="whitegrid", context="talk")
    fig, ax = plt.subplots(figsize=(10, 6.5))

    ax.scatter(
        x,
        y,
        c="#1f77b4",
        s=45,
        zorder=3,
        label="Median pageviews data",
    )
    if len(extrap_ranks):
        ax.scatter(
            extrap_ranks,
            extrap_y,
            c="#d62728",
            s=45,
            zorder=3,
            label="Estimated from trend line",
        )

    ax.plot(
        x_line,
        y_line,
        color="#7eb6d4",
        linestyle="--",
        linewidth=1.8,
        zorder=2,
        label=f"Fit: {coef:.2E} × rank^{slope:.2f}  ($R^2$ = {r2:.3f})",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(EngFormatter())
    ax.yaxis.set_major_formatter(EngFormatter())
    ax.set_xlabel("Rank (log scale)")
    ax.set_ylabel("Median pageviews by rank (log scale)")
    ax.set_title("Yearly pageviews by CrUX rank")

    subtitle = "Data: 2025 yearly pageviews, 202512 CrUX ranks"
    fig.text(0.5, 0.93, subtitle, ha="center", fontsize=11, color="0.35")
    fig.text(
        0.5,
        0.02,
        "Source: https://github.com/thibaudcolas/ranking-to-pageviews",
        ha="center",
        fontsize=9,
        color="0.4",
    )

    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {args.output}")
    print(f"Power law (median pageviews vs rank): {coef:.3E} × rank^{slope:.4f}")
    print(f"R² (log–log linear regression): {r2:.4f}")
    if len(extrap_ranks):
        print("Extrapolated median yearly pageviews (from fit):")
        for r, pv in zip(extrap_ranks, extrap_y):
            print(f"  rank {r:>12,}: {pv:,.0f}")


if __name__ == "__main__":
    main()
