#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx",
#     "pandas",
#     "plotly",
#     "kaleido",
#     "tabulate",
#     "duckdb",
#     "pyarrow",
#     "zstandard",
# ]
# ///
"""
Analyze AI referral traffic to US government websites using the DAP API.

Data source: https://open.gsa.gov/api/dap/
Fetches daily traffic-source reports from 2023-07-27 (first available day) to
the last complete month, then compares AI assistant referrals (ChatGPT,
Perplexity, Claude, Gemini, Copilot, Grok, DeepSeek, Mistral, and others)
against traditional traffic sources over time.

Storage:
- data/traffic.duckdb  — DuckDB database with the raw daily records.
- data/traffic.parquet.zst — a single-file copy for Git LFS. The database is
  rebuilt from this file if missing.

The script only fetches days that are missing from the database. Days the API
genuinely does not have (see KNOWN_GAPS) are never re-fetched.

Outputs charts (PNG + HTML), and a Markdown report.
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

API_BASE = "https://api.gsa.gov/analytics/dap/v2.0.0/reports/traffic-source/data"
PAGE_LIMIT = 10_000
# The API returned an empty result for 2023-07-01..26 in 2026; the earliest day
# it serves is 2023-07-27. The other ranges below were confirmed empty in
# 2026-09 too — genuinely missing from the API, not interrupted fetches.
FIRST_AVAILABLE_DATE = date(2023, 7, 27)
KNOWN_GAPS: set[date] = (
    {date(2023, 7, d) for d in range(1, 29)}
    | {date(2023, 9, 12), date(2023, 12, 13)}
    | {date(2024, 3, 12), date(2024, 6, 11), date(2024, 8, 21), date(2024, 12, 20)}
    | {date(2026, 7, 9)}
)
END_DATE = date(2026, 9, 1) - timedelta(days=1)  # last day of the last complete month
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "traffic.duckdb"
PARQUET_PATH = DATA_DIR / "traffic.parquet.zst"
OUTPUT_DIR = Path(__file__).parent / "assets"

DATA_SOURCE = "Digital Analytics Program (DAP)"

AI_SOURCES = {
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "openai": "ChatGPT",
    "perplexity.ai": "Perplexity",
    "perplexity": "Perplexity",
    "claude.ai": "Claude",
    "anthropic.com": "Claude",
    "gemini.google.com": "Gemini",
    "copilot.com": "Copilot",
    "copilot.microsoft.com": "Copilot",
    "copilot.cloud.microsoft": "Copilot",
    "copilotstudio.microsoft.com": "Copilot",
    "grok.com": "Grok",
    "x.ai": "Grok",
    "chat.deepseek.com": "DeepSeek",
    "chat.mistral.ai": "Mistral",
    "poe.com": "Poe",
    "you.com": "You.com",
}

SEARCH_SOURCES = {"google", "bing", "yahoo", "duckduckgo"}

TRADITIONAL_SOURCES = {
    "google": "Google Search",
    "bing": "Bing",
    "(direct)": "Direct",
    "yahoo": "Yahoo",
    "duckduckgo": "DuckDuckGo",
}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def load_database() -> duckdb.DuckDBPyConnection:
    """Open the DuckDB database, rebuilding it from the LFS parquet if needed."""
    DATA_DIR.mkdir(exist_ok=True)
    if not DB_PATH.exists() and PARQUET_PATH.exists():
        print(f"No database; rebuilding {DB_PATH.name} from {PARQUET_PATH.name}...", file=sys.stderr)
        con = duckdb.connect(str(DB_PATH))
        con.execute(
            f"""
            CREATE TABLE traffic AS
            SELECT * FROM read_parquet('{PARQUET_PATH}')
            """
        )
        con.execute("ALTER TABLE traffic ALTER date TYPE DATE")
        con.execute("ALTER TABLE traffic ALTER id TYPE BIGINT")
        con.execute("ALTER TABLE traffic ALTER visits TYPE BIGINT")
        con.execute("CREATE UNIQUE INDEX traffic_id ON traffic (id)")
        return con
    con = duckdb.connect(str(DB_PATH))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS traffic (
            id BIGINT PRIMARY KEY,
            date DATE,
            report_name VARCHAR,
            report_agency VARCHAR,
            source VARCHAR,
            visits BIGINT,
            session_default_channel_group VARCHAR
        )
        """
    )
    return con


def export_parquet(con: duckdb.DuckDBPyConnection) -> None:
    """Write the single-file LFS copy of the database."""
    con.execute(
        f"""
        COPY (SELECT * FROM traffic ORDER BY date, id)
        TO '{PARQUET_PATH}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100_000)
        """
    )
    print(f"Exported {PARQUET_PATH} ({PARQUET_PATH.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)


def load_dataframe(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load all records as a pandas DataFrame with normalized columns."""
    df = con.execute("SELECT * FROM traffic").df()
    df["date"] = pd.to_datetime(df["date"])
    # Normalize source variants once: lowercase, strip URL paths and debris
    # e.g. "chatgpt.com/https://chatgpt.com/" and "chatgpt.com)".
    src = df["source"].str.lower().str.split("/").str[0].str.rstrip(")").str.strip()
    df["source_normalized"] = src
    df["visits"] = pd.to_numeric(df["visits"], errors="coerce").fillna(0).astype("int64")
    return df


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def expected_days() -> set[date]:
    """Every day from the first available API day through the last complete day."""
    total = (END_DATE - FIRST_AVAILABLE_DATE).days + 1
    return {FIRST_AVAILABLE_DATE + timedelta(days=i) for i in range(total)}


def coverage_report(con: duckdb.DuckDBPyConnection) -> tuple[set[date], set[date]]:
    """Return (days with data, days expected but absent)."""
    present = {
        row[0]
        for row in con.execute("SELECT DISTINCT date FROM traffic").fetchall()
        if row[0] is not None
    }
    missing = expected_days() - present
    unexplained = missing - KNOWN_GAPS
    return present, unexplained


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def get_api_key() -> str:
    key = os.environ.get("GSA_API_KEY")
    if not key:
        print("Warning: GSA_API_KEY not set, using DEMO_KEY1", file=sys.stderr)
        key = "DEMO_KEY1"
    return key


def fetch_with_retry(
    client: httpx.Client, params: dict, max_retries: int = 8
) -> list[dict]:
    """Fetch a single page with exponential backoff on 429."""
    resp = None
    for attempt in range(max_retries):
        resp = client.get(API_BASE, params=params)
        if resp.status_code == 429:
            wait = min(3 ** (attempt + 1), 120)
            print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return []


def fetch_all_pages(
    client: httpx.Client, api_key: str, after: str, before: str
) -> list[dict]:
    """Fetch all pages of data for a date range."""
    all_data = []
    page = 1
    while True:
        data = fetch_with_retry(
            client,
            {
                "api_key": api_key,
                "after": after,
                "before": before,
                "limit": PAGE_LIMIT,
                "page": page,
            },
        )
        if not data:
            break
        all_data.extend(data)
        print(
            f"  Page {page}: {len(data)} records ({after} to {before})",
            file=sys.stderr,
        )
        if len(data) < PAGE_LIMIT:
            break
        page += 1
        time.sleep(1)
    return all_data


def fetch_missing_days(con: duckdb.DuckDBPyConnection, api_key: str) -> int:
    """Fetch any expected days that are absent from the database, in one range
    per contiguous run of missing days. Returns the number of records inserted."""
    _, missing = coverage_report(con)
    if not missing:
        return 0
    runs: list[tuple[date, date]] = []
    run_start = run_prev = None
    for day in sorted(missing):
        if run_prev is not None and day == run_prev + timedelta(days=1):
            run_prev = day
        else:
            if run_start is not None:
                runs.append((run_start, run_prev))
            run_start = run_prev = day
    if run_start is not None:
        runs.append((run_start, run_prev))

    print(f"Fetching {len(missing)} missing days in {len(runs)} range(s)...", file=sys.stderr)
    inserted = 0
    with httpx.Client(timeout=60) as client:
        for after, before in runs:
            records = fetch_all_pages(client, api_key, after.isoformat(), before.isoformat())
            time.sleep(1)
            if not records:
                print(
                    f"  {after} to {before}: API returned no data (day not available).",
                    file=sys.stderr,
                )
                continue
            inserted += insert_records(con, records)
            print(
                f"  {after} to {before}: inserted {len(records)} records",
                file=sys.stderr,
            )
    return inserted


def insert_records(con: duckdb.DuckDBPyConnection, records: list[dict]) -> int:
    """Insert records, ignoring any that are already stored."""
    if not records:
        return 0
    df = pd.DataFrame(records)
    before = con.execute("SELECT count(*) FROM traffic").fetchone()[0]
    con.execute("INSERT OR IGNORE INTO traffic SELECT * FROM df")
    after = con.execute("SELECT count(*) FROM traffic").fetchone()[0]
    return after - before


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def complete_months(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Months in the data whose days are fully present (no known/unknown gaps)."""
    known_gaps = pd.to_datetime(sorted(KNOWN_GAPS))
    day_counts = df.groupby(df["date"].dt.to_period("M"))["date"].nunique()
    present_days = set(df["date"].dt.normalize())
    complete = []
    for period, count in day_counts.items():
        if count < period.days_in_month:
            continue
        first, last = period.start_time, period.end_time.normalize()
        if known_gaps[(known_gaps >= first) & (known_gaps <= last)].size:
            continue
        if len({d for d in present_days if first <= d <= last}) < period.days_in_month:
            continue
        complete.append(period)
    return pd.DatetimeIndex([p.start_time for p in complete])


def add_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Add normalized-source derived columns: is_ai, ai_name, category, bucket."""
    df = df.copy()
    src = df["source_normalized"]
    df["is_ai"] = src.isin(AI_SOURCES)
    df["ai_name"] = src.map(AI_SOURCES)

    def categorize(s):
        if s in AI_SOURCES:
            return "AI referrals"
        if s in SEARCH_SOURCES:
            return "Search"
        if s == "(direct)":
            return "Direct"
        return "Other"

    df["category"] = src.map(categorize)
    return df


def build_weekly_ai_df(df: pd.DataFrame) -> pd.DataFrame:
    ai_df = df[df["is_ai"]].copy()
    ai_df["week"] = ai_df["date"].dt.to_period("W").dt.start_time
    return ai_df.groupby(["week", "ai_name"])["visits"].sum().reset_index()


def build_weekly_ai_vs_rest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = df["date"].dt.to_period("W").dt.start_time

    def bucket(s):
        if s in AI_SOURCES:
            return "AI referrals (total)"
        return TRADITIONAL_SOURCES.get(s, None)

    df["bucket"] = df["source_normalized"].map(bucket)
    df = df[df["bucket"].notna()]
    return df.groupby(["week", "bucket"])["visits"].sum().reset_index()


def build_monthly_share_100(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly traffic share by category, summing to 100%. Complete months only."""
    df = df[df["month"].isin(complete_months(df))].copy()
    monthly = df.groupby(["month", "category"])["visits"].sum().reset_index()
    monthly_total = monthly.groupby("month")["visits"].transform("sum")
    monthly["share_pct"] = monthly["visits"] / monthly_total * 100
    return monthly


def build_monthly_ai_share_and_total(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly AI share % and total traffic volume. Complete months only."""
    df = df[df["month"].isin(complete_months(df))]
    monthly_total = df.groupby("month")["visits"].sum().reset_index()
    monthly_total.columns = ["month", "total_visits"]
    monthly_ai = df[df["is_ai"]].groupby("month")["visits"].sum().reset_index()
    monthly_ai.columns = ["month", "ai_visits"]

    merged = monthly_total.merge(monthly_ai, on="month", how="left").fillna(0)
    merged["ai_share_pct"] = merged["ai_visits"] / merged["total_visits"] * 100
    return merged.sort_values("month").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

AI_COLORS = {
    "ChatGPT": "#10a37f",
    "Perplexity": "#1a73e8",
    "Claude": "#d97706",
    "Gemini": "#4285f4",
    "Copilot": "#9333ea",
    "Grok": "#111827",
    "DeepSeek": "#3b82f6",
    "Mistral": "#f97316",
    "Poe": "#8b5cf6",
    "You.com": "#14b8a6",
}


def add_source_annotation(fig: go.Figure) -> go.Figure:
    fig.add_annotation(
        text=f"Source: {DATA_SOURCE}",
        xref="paper",
        yref="paper",
        x=1,
        y=-0.15,
        showarrow=False,
        font=dict(size=10, color="gray"),
    )
    return fig


def plot_ai_trends(weekly_ai: pd.DataFrame) -> go.Figure:
    fig = px.line(
        weekly_ai,
        x="week",
        y="visits",
        color="ai_name",
        title="AI referral traffic to US government websites (weekly)",
        labels={"week": "Week", "visits": "Weekly visits", "ai_name": "AI source"},
        color_discrete_map=AI_COLORS,
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title="",
        yaxis_title="Weekly visits",
        legend_title="AI source",
        hovermode="x unified",
    )
    return add_source_annotation(fig)


def plot_ai_vs_traditional(weekly_comp: pd.DataFrame) -> go.Figure:
    fig = px.line(
        weekly_comp,
        x="week",
        y="visits",
        color="bucket",
        title="AI referrals vs traditional traffic sources (weekly)",
        labels={"week": "Week", "visits": "Weekly visits (log)", "bucket": "Source"},
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title="",
        yaxis_title="Weekly visits (log scale)",
        yaxis_type="log",
        hovermode="x unified",
    )
    return add_source_annotation(fig)


def plot_ai_share_and_total(
    monthly: pd.DataFrame, latest_complete_month: pd.Timestamp
) -> go.Figure:
    """Dual-axis chart: AI share % (bars) + total traffic (line). Complete
    months only; the current month is excluded because it is partial."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=monthly["month"],
            y=monthly["ai_share_pct"],
            name="AI share (%)",
            marker_color="#6366f1",
            opacity=0.7,
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=monthly["month"],
            y=monthly["total_visits"],
            name="Total traffic",
            line=dict(color="#ef4444", width=2),
            mode="lines",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title=(
            "AI referrals as % of total traffic (monthly, complete months — "
            f"latest: {latest_complete_month.strftime('%B %Y')})"
        ),
        template="plotly_white",
        xaxis_title="",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="AI share (%)", secondary_y=False)
    fig.update_yaxes(title_text="Total monthly visits", secondary_y=True)
    return add_source_annotation(fig)


def plot_traffic_share_100(monthly_share: pd.DataFrame) -> go.Figure:
    """Stacked area chart of all traffic categories summing to 100%."""
    category_order = [
        "Search",
        "Direct",
        "AI referrals",
        "Other",
    ]
    color_map = {
        "Search": "#4285f4",
        "Direct": "#34a853",
        "AI referrals": "#f59e0b",
        "Other": "#9ca3af",
    }
    fig = px.area(
        monthly_share,
        x="month",
        y="share_pct",
        color="category",
        title="Traffic source mix over time (monthly, % of total)",
        labels={
            "month": "Month",
            "share_pct": "Share (%)",
            "category": "Source",
        },
        category_orders={"category": category_order},
        color_discrete_map=color_map,
        groupnorm="percent",
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title="",
        yaxis_title="Share of total traffic (%)",
        hovermode="x unified",
        legend_title="Source",
    )
    return add_source_annotation(fig)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def fmt(n: int | float) -> str:
    """Format a number with commas."""
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


def coverage_note(present: set[date], unexplained: set[date]) -> str:
    expected = expected_days()
    first = min(expected)
    known = expected - present - unexplained
    lines = [
        f"- Expected coverage: **{first.isoformat()}** to **{END_DATE.isoformat()}** "
        f"({fmt(len(expected))} days); data present for {fmt(len(present))} days.",
    ]
    if known:
        by_month: dict[str, list[int]] = {}
        for d in sorted(known):
            by_month.setdefault(d.strftime("%Y-%m"), []).append(d.day)
        gap_str = "; ".join(
            f"{m}: day(s) {', '.join(map(str, days))}" for m, days in sorted(by_month.items())
        )
        lines.append(
            f"- The API does not serve data for {fmt(len(known))} known-missing "
            f"day(s): {gap_str}."
        )
    if unexplained:
        unexp_str = ", ".join(d.isoformat() for d in sorted(unexplained)[:10])
        lines.append(
            f"- **Warning: {fmt(len(unexplained))} unexpected missing day(s)** "
            f"(not previously seen): {unexp_str}"
            + ("…" if len(unexplained) > 10 else "")
            + ". Re-run the script to fetch them."
        )
    return "\n".join(lines)


def generate_report(
    df: pd.DataFrame,
    present_days: set[date],
    unexplained_missing: set[date],
) -> str:
    """Generate a Markdown report with key metrics. Comparisons use complete
    periods only: partial months/quarters/years would understate traffic."""
    from tabulate import tabulate

    lines = []
    lines.append("# AI Referral Traffic to US Government Websites")
    lines.append("")
    lines.append(
        f"Analysis of traffic-source data from the [Digital Analytics Program (DAP)]"
        f"(https://analytics.usa.gov/), covering **{FIRST_AVAILABLE_DATE}** to "
        f"**{END_DATE}**."
    )
    lines.append("")
    lines.append(f"Data source: [DAP API v2.0.0](https://open.gsa.gov/api/dap/)  ")
    lines.append(
        "AI sources tracked: "
        + ", ".join(sorted({AI_SOURCES[s] for s in AI_SOURCES}))
    )
    lines.append("")

    # --- Overall traffic ---
    df = add_categories(df)
    df["month"] = df["date"].dt.to_period("M").dt.start_time
    df["year"] = df["date"].dt.year
    df["quarter"] = df["date"].dt.to_period("Q")

    complete = complete_months(df)
    latest_complete_month = complete[-1]

    # The period's first month (July 2023) and known-gap months are partial.
    # "Since" figures use data from the first fully-covered month onward.
    analysis_start = complete[0]
    df_full = df[df["month"].isin(complete)]

    total_visits = int(df_full["visits"].sum())
    total_ai = int(df_full[df_full["is_ai"]]["visits"].sum())

    lines.append("## Data coverage")
    lines.append("")
    lines.append(coverage_note(present_days, unexplained_missing))
    lines.append(
        f"- Monthly and quarterly figures use complete months only, "
        f"from **{analysis_start.strftime('%B %Y')}** ({analysis_start.strftime('%Y-%m')}) "
        f"to **{latest_complete_month.strftime('%B %Y')}** "
        f"({latest_complete_month.strftime('%Y-%m')})."
    )
    lines.append("")

    lines.append("## Key findings")
    lines.append("")

    # 1. AI share of total (complete months only)
    ai_pct = total_ai / total_visits * 100
    lines.append(
        f"- **AI referrals account for {ai_pct:.2f}% of total tracked traffic** "
        f"across complete months ({fmt(total_ai)} of {fmt(total_visits)} visits)."
    )

    # 2. Most recent complete month stats
    monthly_data = build_monthly_ai_share_and_total(df)
    recent = monthly_data.iloc[-1]
    recent_month_label = recent["month"].strftime("%B %Y")
    lines.append(
        f"- In **{recent_month_label}** (latest complete month), AI referrals were "
        f"**{recent['ai_share_pct']:.2f}%** of total traffic "
        f"({fmt(int(recent['ai_visits']))} visits)."
    )

    # 3. Growth: compare complete quarters only. A quarter is complete when
    # every one of its months is complete (gap months and the in-progress
    # quarter are excluded).
    complete_month_periods = set(df.loc[df["month"].isin(complete), "month"])
    complete_quarters = {
        q
        for q in {pd.Period(m, freq="Q") for m in complete_month_periods}
        if all(q.start_time + pd.offsets.MonthBegin(k) in complete_month_periods for k in range(3))
    }
    df_cq = df_full[df_full["quarter"].isin(complete_quarters)]
    ai_quarterly = (
        df_cq[df_cq["is_ai"]].groupby("quarter")["visits"].sum().reset_index()
    )
    # Skip quarters with <10,000 visits (AI data only trickles in at first)
    meaningful_q = ai_quarterly[ai_quarterly["visits"] >= 10_000]
    if len(meaningful_q) >= 2:
        first_q = meaningful_q.iloc[0]
        last_q = meaningful_q.iloc[-1]
        if first_q["visits"] > 0:
            growth = (last_q["visits"] - first_q["visits"]) / first_q["visits"]
            lines.append(
                f"- AI referral traffic grew **{growth:+,.0%}** from "
                f"{first_q['quarter']} ({fmt(int(first_q['visits']))}) to "
                f"{last_q['quarter']} ({fmt(int(last_q['visits']))}) — the first "
                f"complete quarter with meaningful AI traffic to the latest "
                f"complete quarter (earlier quarters had too little AI data to "
                f"compare)."
            )
    # 4. Month-over-month growth rate: latest two *consecutive* complete
    # months. Gap months (e.g. July 2026) break consecutivity.
    for i in range(len(monthly_data) - 2, -1, -1):
        prev = monthly_data.iloc[i]
        curr = monthly_data.iloc[i + 1]
        if prev["month"] == curr["month"] - pd.DateOffset(months=1):
            if prev["ai_visits"] > 0:
                mom = (curr["ai_visits"] - prev["ai_visits"]) / prev["ai_visits"] * 100
                lines.append(
                    f"- Month-over-month AI referral growth: **{mom:+.1f}%** "
                    f"({prev['month'].strftime('%b %Y')} to "
                    f"{curr['month'].strftime('%b %Y')}, consecutive complete "
                    f"months)."
                )
            break

    # 5. AI vs Bing comparison (complete months)
    bing_total = int(
        df_full[df_full["source_normalized"] == "bing"]["visits"].sum()
    )
    if bing_total > 0:
        ai_vs_bing = total_ai / bing_total * 100
        lines.append(
            f"- Total AI referrals are **{ai_vs_bing:.0f}% of Bing traffic** "
            f"over the period."
        )

    # 6. Total traffic trend: year-over-year between complete years only.
    year_counts = df_full.groupby("year")["date"].nunique()
    days_in_year = df_full.groupby("year")["date"].max().dt.dayofyear
    complete_years = sorted(year_counts[year_counts == days_in_year].index)
    if len(complete_years) >= 2:
        y1, y2 = complete_years[-2], complete_years[-1]
        yearly_total = df_full.groupby("year")["visits"].sum()
        yoy = (yearly_total[y2] - yearly_total[y1]) / yearly_total[y1] * 100
        lines.append(
            f"- Overall traffic changed **{yoy:+.1f}%** year-over-year "
            f"({y1}: {fmt(int(yearly_total[y1]))} → {y2}: {fmt(int(yearly_total[y2]))})."
        )

    lines.append("")

    # --- AI breakdown table ---
    lines.append("## AI referrals by source and year")
    lines.append("")
    lines.append(
        "Complete months only. The first month of the dataset (July 2023) is "
        "partial, and the current month is still in progress."
    )
    lines.append("")

    ai_df = df_full[df_full["ai_name"].notna()].copy()
    pivot = ai_df.pivot_table(
        values="visits", index="ai_name", columns="year", aggfunc="sum", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    pivot.loc["**ALL AI**"] = pivot.sum()

    lines.append(tabulate(pivot, headers="keys", tablefmt="github", intfmt=","))
    lines.append("")

    # --- AI share by year (complete years only) ---
    lines.append("## AI share of total traffic by year")
    lines.append("")
    lines.append(
        "Complete years only for comparisons; partial years are annotated. "
        "The current year is still in progress."
    )
    lines.append("")

    yearly_ai = ai_df.groupby("year")["visits"].sum()
    yearly_total = df_full.groupby("year")["visits"].sum()
    lines.append("| Year | Total Traffic | AI Referrals | AI Share |")
    lines.append("|------|--------------|-------------|----------|")
    for year in sorted(yearly_total.index):
        t = int(yearly_total[year])
        a = int(yearly_ai.get(year, 0))
        pct = a / t * 100 if t > 0 else 0
        note = "" if year in complete_years else " (partial year)"
        lines.append(f"| {year}{note} | {fmt(t)} | {fmt(a)} | {pct:.3f}% |")
    lines.append("")

    # --- Top AI weeks ---
    lines.append("## Peak AI referral weeks")
    lines.append("")
    weekly_ai = build_weekly_ai_df(df_full)
    weekly_total = weekly_ai.groupby("week")["visits"].sum().reset_index()
    weekly_total = weekly_total.sort_values("visits", ascending=False).head(5)
    lines.append("| Week Starting | Total AI Visits |")
    lines.append("|--------------|----------------|")
    for _, row in weekly_total.iterrows():
        lines.append(
            f"| {row['week'].strftime('%Y-%m-%d')} | {fmt(int(row['visits']))} |"
        )
    lines.append("")

    # --- Charts ---
    lines.append("## Charts")
    lines.append("")
    lines.append("### AI referral trends by source")
    lines.append("![AI referral trends](./assets/ai_referrals_trend.png)")
    lines.append("")
    lines.append("### AI share of total traffic and overall traffic volume")
    lines.append("![AI share and total traffic](./assets/ai_share_pct.png)")
    lines.append("")
    lines.append("### AI referrals vs traditional traffic sources")
    lines.append("![AI vs traditional](./assets/ai_vs_traditional.png)")
    lines.append("")
    lines.append("### Traffic source mix (100% stacked)")
    lines.append("![Traffic source mix](./assets/traffic_source_mix.png)")
    lines.append("")

    # --- Methodology ---
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "- Data from the [DAP API](https://open.gsa.gov/api/dap/) "
        "`traffic-source` report (v2.0.0), fetched daily and stored in DuckDB."
    )
    lines.append(f"- Date range: {FIRST_AVAILABLE_DATE} to {END_DATE}.")
    lines.append(
        "- AI sources identified by normalized `source` field matching: "
        + ", ".join(f"`{s}`" for s in sorted(AI_SOURCES.keys()))
        + "."
    )
    lines.append(
        '- "(direct)" and "(other)" traffic is classified under '
        "Direct and Other respectively."
    )
    lines.append(
        "- Percentages are based on total visits across all sources in "
        "the traffic-source report."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------


def print_summary_table(df: pd.DataFrame, complete_years: list[int]) -> None:
    from tabulate import tabulate

    df = add_categories(df)
    df["year"] = df["date"].dt.year

    ai_df = df[df["ai_name"].notna()].copy()
    pivot = ai_df.pivot_table(
        values="visits", index="ai_name", columns="year", aggfunc="sum", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    pivot.loc["ALL AI"] = pivot.sum()

    print("\n=== AI Referral Traffic Summary (all cached data) ===\n")
    print(tabulate(pivot, headers="keys", tablefmt="github", intfmt=","))

    df_full = df[df["month"].isin(complete_months(df))]
    yearly_total = df_full.groupby("year")["visits"].sum()
    yearly_ai = df_full[df_full["is_ai"]].groupby("year")["visits"].sum()
    pct = (yearly_ai / yearly_total * 100).fillna(0)

    print("\n=== AI Share of Total Traffic by Year (complete years) ===\n")
    for year in sorted(pct.index):
        if year in complete_years:
            print(f"  {year}: {pct[year]:.3f}%")
        else:
            print(f"  {year}: {pct[year]:.3f}% (partial year)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    api_key = get_api_key()
    con = load_database()
    try:
        fetch_missing_days(con, api_key)
        export_parquet(con)
        df = load_dataframe(con)

        present_days, unexplained_missing = coverage_report(con)
        print(
            f"Coverage: {len(present_days)}/{len(expected_days())} expected days present; "
            f"{len(unexplained_missing)} unexpected missing day(s).",
            file=sys.stderr,
        )

        df = add_categories(df)
        df["month"] = df["date"].dt.to_period("M").dt.start_time
        df["year"] = df["date"].dt.year

        # Complete years for the yearly tables (a partial current year would
        # otherwise understate traffic and share).
        df_full = df[df["month"].isin(complete_months(df))]
        year_counts = df_full.groupby("year")["date"].nunique()
        days_in_year = df_full.groupby("year")["date"].max().dt.dayofyear
        complete_years = sorted(year_counts[year_counts == days_in_year].index)

        print_summary_table(df, complete_years)

        # Build aggregations
        weekly_ai = build_weekly_ai_df(df)
        weekly_comp = build_weekly_ai_vs_rest(df)
        monthly_share = build_monthly_share_100(df)
        monthly_ai_total = build_monthly_ai_share_and_total(df)
        latest_complete_month = complete_months(df)[-1]

        # Generate charts
        OUTPUT_DIR.mkdir(exist_ok=True)
        charts = [
            (plot_ai_trends(weekly_ai), "ai_referrals_trend"),
            (plot_ai_vs_traditional(weekly_comp), "ai_vs_traditional"),
            (
                plot_ai_share_and_total(monthly_ai_total, latest_complete_month),
                "ai_share_pct",
            ),
            (plot_traffic_share_100(monthly_share), "traffic_source_mix"),
        ]

        for fig, name in charts:
            fig.write_image(OUTPUT_DIR / f"{name}.png", width=1200, height=600, scale=2)
            fig.write_html(OUTPUT_DIR / f"{name}.html")
            print(f"  Saved {OUTPUT_DIR / name}.png / .html", file=sys.stderr)

        # Generate Markdown report
        report = generate_report(df, present_days, unexplained_missing)
        report_path = Path(__file__).parent / "REPORT.md"
        report_path.write_text(report)
        print(f"  Saved {report_path}", file=sys.stderr)

        print("Done!", file=sys.stderr)
    finally:
        con.close()


if __name__ == "__main__":
    main()
