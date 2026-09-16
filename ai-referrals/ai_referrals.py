#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx",
#     "pandas",
#     "plotly",
#     "kaleido",
#     "tabulate",
# ]
# ///
"""
Analyze AI referral traffic to US government websites using the DAP API.

Data source: https://open.gsa.gov/api/dap/
Fetches traffic-source reports from mid-2023 to present day, then compares
AI assistant referrals (ChatGPT, Perplexity, Claude, Gemini, Copilot)
against traditional traffic sources over time.

Caches raw API responses in .cache/ to avoid repeated fetches.
Outputs charts (PNG + HTML) and a Markdown report.
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

API_BASE = "https://api.gsa.gov/analytics/dap/v2.0.0/reports/traffic-source/data"
PAGE_LIMIT = 10_000
START_DATE = date(2023, 8, 1)  # DAP v2 data starts around mid-2023
END_DATE = date(2026, 9, 1)  # Last complete month
CACHE_DIR = Path(__file__).parent / ".cache"
OUTPUT_DIR = Path(__file__).parent

DATA_SOURCE = "Digital Analytics Program (DAP)"

AI_SOURCES = {
    "chatgpt.com": "ChatGPT",
    "perplexity.ai": "Perplexity",
    "perplexity": "Perplexity",
    "claude.ai": "Claude",
    "gemini.google.com": "Gemini",
    "copilot.com": "Copilot",
    "copilot.microsoft.com": "Copilot",
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


def cache_path_for_month(year: int, month: int) -> Path:
    return CACHE_DIR / f"traffic-source_{year}-{month:02d}.json"


def fetch_data(api_key: str) -> pd.DataFrame:
    """Fetch traffic-source data in monthly chunks, using file cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    all_records = []

    with httpx.Client(timeout=60) as client:
        chunk_start = START_DATE
        while chunk_start <= END_DATE:
            chunk_end = min(
                (chunk_start.replace(day=1) + timedelta(days=32)).replace(day=1)
                - timedelta(days=1),
                END_DATE,
            )

            cache_file = cache_path_for_month(chunk_start.year, chunk_start.month)
            # Cache any month whose last day is on or before END_DATE
            is_cacheable = chunk_end <= END_DATE

            if cache_file.exists() and is_cacheable:
                records = json.loads(cache_file.read_text())
                print(
                    f"Cached {chunk_start} to {chunk_end}: {len(records)} records",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Fetching {chunk_start} to {chunk_end}...",
                    file=sys.stderr,
                )
                records = fetch_all_pages(
                    client,
                    api_key,
                    chunk_start.isoformat(),
                    chunk_end.isoformat(),
                )
                if is_cacheable:
                    cache_file.write_text(json.dumps(records))
                time.sleep(1)

            all_records.extend(records)
            chunk_start = chunk_end + timedelta(days=1)

    print(f"\nTotal records: {len(all_records)}", file=sys.stderr)
    df = pd.DataFrame(all_records)
    df["date"] = pd.to_datetime(df["date"])
    df["visits"] = pd.to_numeric(df["visits"], errors="coerce").fillna(0).astype(int)
    return df


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def build_weekly_ai_df(df: pd.DataFrame) -> pd.DataFrame:
    ai_mask = df["source"].str.lower().isin(AI_SOURCES)
    ai_df = df[ai_mask].copy()
    ai_df["ai_name"] = ai_df["source"].str.lower().map(AI_SOURCES)
    ai_df["week"] = ai_df["date"].dt.to_period("W").dt.start_time
    return ai_df.groupby(["week", "ai_name"])["visits"].sum().reset_index()


def build_weekly_ai_vs_rest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = df["date"].dt.to_period("W").dt.start_time
    source_lower = df["source"].str.lower()

    def bucket(s):
        if s in AI_SOURCES:
            return "AI referrals (total)"
        return TRADITIONAL_SOURCES.get(s, None)

    df["bucket"] = source_lower.map(bucket)
    df = df[df["bucket"].notna()]
    return df.groupby(["week", "bucket"])["visits"].sum().reset_index()


def build_monthly_share_100(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly traffic share by category, summing to 100%."""
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").dt.start_time
    source_lower = df["source"].str.lower()

    def categorize(s):
        if s in AI_SOURCES:
            return "AI referrals"
        if s in SEARCH_SOURCES:
            return "Search"
        if s == "(direct)":
            return "Direct"
        return "Other"

    df["category"] = source_lower.map(categorize)
    monthly = df.groupby(["month", "category"])["visits"].sum().reset_index()
    monthly_total = monthly.groupby("month")["visits"].transform("sum")
    monthly["share_pct"] = monthly["visits"] / monthly_total * 100
    return monthly


def build_monthly_ai_share_and_total(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly AI share % and total traffic volume."""
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").dt.start_time
    source_lower = df["source"].str.lower()
    df["is_ai"] = source_lower.isin(AI_SOURCES)

    monthly_total = df.groupby("month")["visits"].sum().reset_index()
    monthly_total.columns = ["month", "total_visits"]
    monthly_ai = df[df["is_ai"]].groupby("month")["visits"].sum().reset_index()
    monthly_ai.columns = ["month", "ai_visits"]

    merged = monthly_total.merge(monthly_ai, on="month", how="left").fillna(0)
    merged["ai_share_pct"] = merged["ai_visits"] / merged["total_visits"] * 100
    return merged


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

AI_COLORS = {
    "ChatGPT": "#10a37f",
    "Perplexity": "#1a73e8",
    "Claude": "#d97706",
    "Gemini": "#4285f4",
    "Copilot": "#9333ea",
}


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


def plot_ai_share_and_total(monthly: pd.DataFrame) -> go.Figure:
    """Dual-axis chart: AI share % (bars) + total traffic (line)."""
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
        title="AI referrals as % of total traffic (monthly)",
        template="plotly_white",
        xaxis_title="",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="AI share (%)", secondary_y=False)
    fig.update_yaxes(title_text="Total monthly visits", secondary_y=True)
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


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def fmt(n: int | float) -> str:
    """Format a number with commas."""
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


def generate_report(df: pd.DataFrame) -> str:
    """Generate a Markdown report with key metrics."""
    from tabulate import tabulate

    lines = []
    lines.append("# AI Referral Traffic to US Government Websites")
    lines.append("")
    lines.append(
        f"Analysis of traffic-source data from the [Digital Analytics Program (DAP)]"
        f"(https://analytics.usa.gov/), covering **{START_DATE}** to **{END_DATE}**."
    )
    lines.append("")
    lines.append(f"Data source: [DAP API v2.0.0](https://open.gsa.gov/api/dap/)  ")
    lines.append(f"AI sources tracked: ChatGPT, Perplexity, Claude, Gemini, Copilot")
    lines.append("")

    # --- Overall traffic ---
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").dt.start_time
    df["year"] = df["date"].dt.year
    source_lower = df["source"].str.lower()
    df["is_ai"] = source_lower.isin(AI_SOURCES)
    df["ai_name"] = source_lower.map(AI_SOURCES)

    total_visits = df["visits"].sum()
    total_ai = df[df["is_ai"]]["visits"].sum()

    lines.append("## Key findings")
    lines.append("")

    # 1. AI share of total
    ai_pct = total_ai / total_visits * 100
    lines.append(
        f"- **AI referrals account for {ai_pct:.2f}% of total tracked traffic** "
        f"({fmt(total_ai)} of {fmt(total_visits)} visits)."
    )

    # 2. Most recent full month stats
    monthly_data = build_monthly_ai_share_and_total(df)
    recent = monthly_data.iloc[-1]
    recent_month_label = recent["month"].strftime("%B %Y")
    lines.append(
        f"- In **{recent_month_label}**, AI referrals were "
        f"**{recent['ai_share_pct']:.2f}%** of total traffic "
        f"({fmt(int(recent['ai_visits']))} visits)."
    )

    # 3. Growth: compare latest full quarter to first quarter with meaningful data
    df["quarter"] = df["date"].dt.to_period("Q")
    ai_quarterly = df[df["is_ai"]].groupby("quarter")["visits"].sum().reset_index()
    # Skip quarters with <10,000 visits (likely incomplete API data)
    meaningful_q = ai_quarterly[ai_quarterly["visits"] >= 10_000]
    if len(meaningful_q) >= 2:
        first_q = meaningful_q.iloc[0]
        last_full_q = meaningful_q.iloc[-1]
        if first_q["visits"] > 0:
            growth = (last_full_q["visits"] - first_q["visits"]) / first_q["visits"]
            lines.append(
                f"- AI referral traffic grew **{growth:+,.0%}** from "
                f"{first_q['quarter']} ({fmt(int(first_q['visits']))}) to "
                f"{last_full_q['quarter']} ({fmt(int(last_full_q['visits']))})."
            )

    # 4. Month-over-month growth rate (recent)
    if len(monthly_data) >= 2:
        prev = monthly_data.iloc[-2]
        curr = monthly_data.iloc[-1]
        if prev["ai_visits"] > 0:
            mom = (curr["ai_visits"] - prev["ai_visits"]) / prev["ai_visits"] * 100
            lines.append(
                f"- Month-over-month AI referral growth: **{mom:+.1f}%** "
                f"({prev['month'].strftime('%b %Y')} to {curr['month'].strftime('%b %Y')})."
            )

    # 5. AI vs Bing comparison
    bing_total = df[source_lower == "bing"]["visits"].sum()
    if bing_total > 0:
        ai_vs_bing = total_ai / bing_total * 100
        lines.append(
            f"- Total AI referrals are **{ai_vs_bing:.0f}% of Bing traffic** over the period."
        )

    # 6. Total traffic trend
    yearly_total = df.groupby("year")["visits"].sum()
    if len(yearly_total) >= 2:
        years = sorted(yearly_total.index)
        # Compare two most recent full years if available
        if END_DATE.year in years and len(years) >= 3:
            y1, y2 = years[-3], years[-2]  # skip current incomplete year
        else:
            y1, y2 = years[-2], years[-1]
        yoy = (yearly_total[y2] - yearly_total[y1]) / yearly_total[y1] * 100
        lines.append(
            f"- Overall traffic changed **{yoy:+.1f}%** year-over-year "
            f"({y1}: {fmt(int(yearly_total[y1]))} → {y2}: {fmt(int(yearly_total[y2]))})."
        )

    lines.append("")

    # --- AI breakdown table ---
    lines.append("## AI referrals by source and year")
    lines.append("")

    ai_df = df[df["ai_name"].notna()].copy()
    pivot = ai_df.pivot_table(
        values="visits", index="ai_name", columns="year", aggfunc="sum", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    pivot.loc["**ALL AI**"] = pivot.sum()

    lines.append(tabulate(pivot, headers="keys", tablefmt="github", intfmt=","))
    lines.append("")

    # --- AI share by year ---
    lines.append("## AI share of total traffic by year")
    lines.append("")

    yearly_ai = ai_df.groupby("year")["visits"].sum()
    yearly_total = df.groupby("year")["visits"].sum()
    lines.append("| Year | Total Traffic | AI Referrals | AI Share |")
    lines.append("|------|--------------|-------------|----------|")
    for year in sorted(yearly_total.index):
        t = int(yearly_total[year])
        a = int(yearly_ai.get(year, 0))
        pct = a / t * 100 if t > 0 else 0
        lines.append(f"| {year} | {fmt(t)} | {fmt(a)} | {pct:.3f}% |")
    lines.append("")

    # --- Top AI weeks ---
    lines.append("## Peak AI referral weeks")
    lines.append("")
    weekly_ai = build_weekly_ai_df(df)
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
    lines.append("![AI referral trends](ai_referrals_trend.png)")
    lines.append("")
    lines.append("### AI share of total traffic and overall traffic volume")
    lines.append("![AI share and total traffic](ai_share_pct.png)")
    lines.append("")
    lines.append("### AI referrals vs traditional traffic sources")
    lines.append("![AI vs traditional](ai_vs_traditional.png)")
    lines.append("")
    lines.append("### Traffic source mix (100% stacked)")
    lines.append("![Traffic source mix](traffic_source_mix.png)")
    lines.append("")

    # --- Methodology ---
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "- Data from the [DAP API](https://open.gsa.gov/api/dap/) "
        "`traffic-source` report (v2.0.0)."
    )
    lines.append(f"- Date range: {START_DATE} to {END_DATE}.")
    lines.append(
        "- AI sources identified by `source` field matching: "
        + ", ".join(f"`{s}`" for s in sorted(set(AI_SOURCES.keys())))
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


def print_summary_table(df: pd.DataFrame) -> None:
    from tabulate import tabulate

    df = df.copy()
    source_lower = df["source"].str.lower()
    df["ai_name"] = source_lower.map(AI_SOURCES)
    ai_df = df[df["ai_name"].notna()].copy()
    ai_df["year"] = ai_df["date"].dt.year

    pivot = ai_df.pivot_table(
        values="visits", index="ai_name", columns="year", aggfunc="sum", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    pivot.loc["ALL AI"] = pivot.sum()

    print("\n=== AI Referral Traffic Summary ===\n")
    print(tabulate(pivot, headers="keys", tablefmt="github", intfmt=","))

    df["year"] = df["date"].dt.year
    yearly_total = df.groupby("year")["visits"].sum()
    yearly_ai = ai_df.groupby("year")["visits"].sum()
    pct = (yearly_ai / yearly_total * 100).fillna(0)

    print("\n=== AI Share of Total Traffic by Year ===\n")
    for year in sorted(pct.index):
        print(f"  {year}: {pct[year]:.3f}%")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    api_key = get_api_key()

    print("Fetching DAP traffic-source data...", file=sys.stderr)
    df = fetch_data(api_key)

    print_summary_table(df)

    # Build aggregations
    weekly_ai = build_weekly_ai_df(df)
    weekly_comp = build_weekly_ai_vs_rest(df)
    monthly_share = build_monthly_share_100(df)
    monthly_ai_total = build_monthly_ai_share_and_total(df)

    # Generate charts
    charts = [
        (plot_ai_trends(weekly_ai), "ai_referrals_trend"),
        (plot_ai_vs_traditional(weekly_comp), "ai_vs_traditional"),
        (plot_ai_share_and_total(monthly_ai_total), "ai_share_pct"),
        (plot_traffic_share_100(monthly_share), "traffic_source_mix"),
    ]

    for fig, name in charts:
        fig.write_image(f"{name}.png", width=1200, height=600, scale=2)
        fig.write_html(f"{name}.html")
        print(f"  Saved {name}.png / .html", file=sys.stderr)

    # Generate Markdown report
    report = generate_report(df)
    report_path = OUTPUT_DIR / "REPORT.md"
    report_path.write_text(report)
    print(f"  Saved {report_path}", file=sys.stderr)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
