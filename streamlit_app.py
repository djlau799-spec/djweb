from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from stock_market_research import (
    StockReport,
    analyze_market_context,
    analyze_ticker,
    fetch_sgd_myr_history,
    fetch_price_history,
    fetch_yahoo_quotes,
    fmt_money,
    fmt_pct,
    load_sec_ticker_map,
    render_markdown,
    to_jsonable,
)


st.set_page_config(
    page_title="Stock Market Research",
    layout="wide",
    initial_sidebar_state="expanded",
)


def config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default))


DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA"
DEFAULT_SEC_USER_AGENT = config_value("SEC_USER_AGENT", "market-research-app/1.0 contact@example.com")
DEFAULT_ALPHA_VANTAGE_KEY = config_value("ALPHAVANTAGE_API_KEY") or config_value("ALPHA_VANTAGE_API_KEY")

NOTABLE_STOCK_GROUPS = {
    "AI & Mega-Cap Tech": ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "TSLA"],
    "Semiconductors": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "QCOM", "MU", "INTC"],
    "Software & Cybersecurity": ["MSFT", "CRM", "ADBE", "NOW", "ORCL", "PANW", "CRWD", "PLTR"],
    "Financials": ["JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "BRK.B"],
    "Healthcare": ["LLY", "UNH", "JNJ", "MRK", "ABBV", "PFE", "TMO", "ISRG"],
    "Energy & Industrials": ["XOM", "CVX", "COP", "CAT", "GE", "RTX", "HON", "DE"],
    "Consumer & Retail": ["COST", "WMT", "HD", "MCD", "NKE", "SBUX", "DIS", "NFLX"],
    "Market ETFs": ["SPY", "QQQ", "DIA", "IWM", "SMH", "XLK", "XLF", "XLE"],
}

DEFAULT_GROUPS = ["AI & Mega-Cap Tech", "Semiconductors", "Market ETFs"]
DEFAULT_REFRESH_SECONDS = 60
SGD_MYR_PERIODS = {
    "Today": ("1d", "1m"),
    "Past week": ("5d", "15m"),
    "Past month": ("1mo", "1h"),
    "Past 3 months": ("3mo", "1d"),
    "Past year": ("1y", "1d"),
}


st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1280px;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e6e8ec;
        border-radius: 8px;
        padding: 0.75rem 0.85rem;
        background: #ffffff;
    }
    .small-note {
        color: #667085;
        font-size: 0.9rem;
        line-height: 1.35;
    }
    .rating-buy {
        color: #027a48;
        font-weight: 700;
    }
    .rating-monitor {
        color: #b54708;
        font-weight: 700;
    }
    .rating-avoid {
        color: #b42318;
        font-weight: 700;
    }
    .decision-card {
        border: 1px solid #e6e8ec;
        border-radius: 8px;
        padding: 0.85rem;
        min-height: 230px;
        background: #ffffff;
    }
    .decision-label {
        color: #475467;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_tickers(raw: str) -> list[str]:
    parts = re.split(r"[\s,;]+", raw)
    tickers: list[str] = []
    seen = set()
    for part in parts:
        ticker = part.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        tickers.append(ticker)
        seen.add(ticker)
    return tickers


def tickers_from_groups(groups: list[str]) -> list[str]:
    tickers: list[str] = []
    seen = set()
    for group in groups:
        for ticker in NOTABLE_STOCK_GROUPS.get(group, []):
            if ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)
    return tickers


def resolved_news_source(selection: str, alpha_vantage_key: str) -> str:
    if selection == "Auto":
        return "trusted"
    if selection == "Trusted: Yahoo + Alpha Vantage":
        return "trusted"
    if selection == "Alpha Vantage":
        return "alpha-vantage"
    if selection == "Yahoo RSS":
        return "yahoo-rss"
    return "none"


def yahoo_news_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{urllib.parse.quote(ticker)}/news/"


def moomoo_stock_url(ticker: str) -> str:
    normalized = ticker.replace(".", "-")
    return f"https://www.moomoo.com/stock/{urllib.parse.quote(normalized)}-US"


def key_watch_note(report: StockReport) -> str:
    for note in report.notes:
        if "moving average" in note.lower() or "volume" in note.lower() or "net income" in note.lower():
            return note
    return report.notes[0] if report.notes else "Review price trend, filings, and recent news."


def collect_news_rows(reports: list[StockReport]) -> pd.DataFrame:
    rows = []
    for report in reports:
        for item in report.news:
            rows.append(
                {
                    "Ticker": report.ticker,
                    "Source": item.source or "News",
                    "Headline": item.title,
                    "Published": item.published,
                    "Sentiment": item.sentiment,
                    "URL": item.url,
                }
            )
    return pd.DataFrame(rows)


def format_timestamp(value: str) -> str:
    if not value:
        return "n/a"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def cached_sec_ticker_map(sec_user_agent: str) -> dict[str, dict[str, Any]]:
    return load_sec_ticker_map(sec_user_agent)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_market_context() -> list[str]:
    return analyze_market_context()


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_price_history(ticker: str) -> pd.DataFrame:
    bars = fetch_price_history(ticker)
    return pd.DataFrame(
        [
            {
                "Date": bar.day,
                "Open": bar.open,
                "High": bar.high,
                "Low": bar.low,
                "Close": bar.close,
                "Volume": bar.volume,
            }
            for bar in bars
        ]
    )


@st.cache_data(ttl=30, show_spinner=False)
def cached_live_quotes(tickers: tuple[str, ...]) -> pd.DataFrame:
    rows = fetch_yahoo_quotes(list(tickers))
    for row in rows:
        ticker = row.get("ticker", "")
        row["Yahoo News"] = yahoo_news_url(ticker)
        row["Moomoo"] = moomoo_stock_url(ticker)
        row["Updated"] = format_timestamp(row.get("market_time", ""))
        delay = row.get("exchange_delay_minutes")
        if row.get("is_realtime"):
            row["Feed"] = "Real-time"
        elif isinstance(delay, (int, float)):
            row["Feed"] = f"Delayed {delay} min"
        elif delay:
            row["Feed"] = f"Chart feed ({delay})"
        else:
            row["Feed"] = "Delayed/unknown"
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def cached_sgd_myr_history(chart_range: str, interval: str) -> tuple[dict[str, Any], pd.DataFrame]:
    payload = fetch_sgd_myr_history(chart_range, interval)
    rows = payload.get("rows", [])
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values("datetime")
    return payload.get("meta", {}), frame


@st.cache_data(ttl=55, show_spinner=False)
def cached_sgd_myr_live_history() -> tuple[dict[str, Any], pd.DataFrame]:
    payload = fetch_sgd_myr_history("1d", "1m")
    rows = payload.get("rows", [])
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values("datetime")
    return payload.get("meta", {}), frame


def rating_class(rating: str) -> str:
    if "Buy" in rating:
        return "rating-buy"
    if "Monitor" in rating:
        return "rating-monitor"
    if "Avoid" in rating:
        return "rating-avoid"
    return ""


def decision_bucket(report: StockReport) -> str:
    rating = report.rating.lower()
    if "buy" in rating:
        return "Buy-watchlist"
    if "avoid" in rating:
        return "Avoid / wait"
    if "insufficient" in rating:
        return "Insufficient data"
    return "Monitor"


def latest_headline(report: StockReport) -> str:
    if not report.news:
        return "No recent headline collected."
    return report.news[0].title or "Untitled headline"


def action_checklist(report: StockReport) -> list[str]:
    price = report.price
    checklist = [
        "Check current quote against the latest close before entering.",
        "Read the newest Yahoo Finance and Moomoo source pages.",
    ]
    if price.get("sma_50") and price.get("close"):
        if price["close"] >= price["sma_50"]:
            checklist.append("Confirm the stock can hold above its 50-day average.")
        else:
            checklist.append("Wait for price to reclaim its 50-day average.")
    if report.warnings:
        checklist.append("Resolve data warnings and risk alerts before sizing any position.")
    if report.news:
        checklist.append("Verify whether recent headlines are durable catalysts or short-term noise.")
    return checklist


def risk_and_catalyst_rows(reports: list[StockReport]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    risk_terms = ("risk", "below", "negative", "weak", "declin", "failed", "elevated", "warning")
    catalyst_terms = ("positive", "constructive", "above", "growth", "strong", "improv", "momentum")
    for report in reports:
        for warning in report.warnings:
            rows.append({"Ticker": report.ticker, "Type": "Risk", "Item": warning})
        for note in report.notes:
            lowered = note.lower()
            if any(term in lowered for term in risk_terms):
                rows.append({"Ticker": report.ticker, "Type": "Risk", "Item": note})
            elif any(term in lowered for term in catalyst_terms):
                rows.append({"Ticker": report.ticker, "Type": "Catalyst", "Item": note})
    return pd.DataFrame(rows)


def quote_lookup(quotes: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if quotes.empty or "ticker" not in quotes:
        return {}
    return {str(row["ticker"]): row.to_dict() for _, row in quotes.iterrows()}


def report_table(reports: list[StockReport], quotes: pd.DataFrame | None = None) -> pd.DataFrame:
    live = quote_lookup(quotes if quotes is not None else pd.DataFrame())
    rows = []
    for report in sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True):
        price = report.price
        fundamentals = report.fundamentals
        quote = live.get(report.ticker, {})
        rows.append(
            {
                "Ticker": report.ticker,
                "Company": report.company or "n/a",
                "Rating": report.rating,
                "Score": report.scores.get("total", 0.0),
                "Live Price": quote.get("price"),
                "Live Change %": quote.get("change_percent"),
                "Trend Close": price.get("close"),
                "1M": price.get("return_1m_pct"),
                "3M": price.get("return_3m_pct"),
                "1Y": price.get("return_1y_pct"),
                "Net Income": fundamentals.get("net_income", {}).get("value"),
                "Why watch": key_watch_note(report),
                "Warnings": len(report.warnings),
            }
        )
    return pd.DataFrame(rows)


def payload_json(reports: list[StockReport], market_notes: list[str], news_source: str) -> str:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "news_source": news_source,
        "market_notes": market_notes,
        "reports": [to_jsonable(report) for report in reports],
    }
    return json.dumps(payload, indent=2, default=str)


def analyze_reports(
    tickers: list[str],
    sec_user_agent: str,
    alpha_vantage_key: str,
    news_source: str,
    news_limit: int,
) -> tuple[list[StockReport], list[str]]:
    progress = st.progress(0)
    status = st.empty()

    status.write("Loading SEC ticker map...")
    try:
        sec_ticker_map = cached_sec_ticker_map(sec_user_agent)
    except Exception as exc:
        st.warning(f"SEC ticker map failed: {exc}")
        sec_ticker_map = {}

    status.write("Collecting market context...")
    try:
        market_notes = cached_market_context()
    except Exception as exc:
        market_notes = [f"Market context could not be collected: {exc}"]

    reports: list[StockReport] = []
    for index, ticker in enumerate(tickers, start=1):
        status.write(f"Analyzing {ticker}...")
        reports.append(
            analyze_ticker(
                ticker=ticker,
                sec_ticker_map=sec_ticker_map,
                sec_user_agent=sec_user_agent,
                alpha_vantage_key=alpha_vantage_key or None,
                news_limit=news_limit,
                news_source=news_source,
            )
        )
        progress.progress(index / len(tickers))
        time.sleep(0.05)

    status.write("Analysis complete.")
    return reports, market_notes


def render_summary(reports: list[StockReport]) -> None:
    ranked = sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True)
    top = ranked[0] if ranked else None
    buy_count = sum(1 for report in reports if "Buy" in report.rating)
    warning_count = sum(len(report.warnings) for report in reports)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickers", len(reports))
    col2.metric("Buy watchlist", buy_count)
    col3.metric("Top score", f"{top.scores.get('total', 0.0):.2f}" if top else "n/a")
    col4.metric("Data warnings", warning_count)

    if top:
        st.markdown(
            f"Top ranked: **{top.ticker}** - "
            f"<span class='{rating_class(top.rating)}'>{top.rating}</span>",
            unsafe_allow_html=True,
        )


def render_decision_dashboard(
    reports: list[StockReport],
    quotes: pd.DataFrame | None,
    market_notes: list[str],
    strategy_lens: str,
) -> None:
    ranked = sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True)
    live = quote_lookup(quotes if quotes is not None else pd.DataFrame())
    decisions = pd.DataFrame(
        [
            {
                "Ticker": report.ticker,
                "Decision": decision_bucket(report),
                "Score": report.scores.get("total", 0.0),
                "Price trend": report.scores.get("price_trend", 0.0),
                "Fundamentals": report.scores.get("sec_fundamentals", 0.0),
                "News": report.scores.get("news_sentiment", 0.0),
                "Warnings": len(report.warnings),
            }
            for report in reports
        ]
    )

    st.subheader("Daily Decision Dashboard")
    st.caption(
        f"Modeled after the Daily Stock Analysis decision board. Strategy lens: {strategy_lens}. "
        "This is automated research support, not financial advice."
    )

    buy_count = int((decisions["Decision"] == "Buy-watchlist").sum()) if not decisions.empty else 0
    monitor_count = int((decisions["Decision"] == "Monitor").sum()) if not decisions.empty else 0
    avoid_count = int((decisions["Decision"] == "Avoid / wait").sum()) if not decisions.empty else 0
    avg_score = float(decisions["Score"].mean()) if not decisions.empty else 0.0
    warning_count = int(decisions["Warnings"].sum()) if not decisions.empty else 0

    metric_cols = st.columns(5)
    metric_cols[0].metric("Buy-watchlist", buy_count)
    metric_cols[1].metric("Monitor", monitor_count)
    metric_cols[2].metric("Avoid / wait", avoid_count)
    metric_cols[3].metric("Average score", f"{avg_score:.2f}")
    metric_cols[4].metric("Risk alerts", warning_count)

    if ranked:
        top = ranked[0]
        quote = live.get(top.ticker, {})
        top_cols = st.columns([1.1, 1.4])
        with top_cols[0]:
            st.markdown("**Top decision candidate**")
            st.markdown(
                f"### {top.ticker} "
                f"<span class='{rating_class(top.rating)}'>{top.rating}</span>",
                unsafe_allow_html=True,
            )
            if top.company:
                st.caption(top.company)
            live_price = quote.get("price")
            live_change_pct = quote.get("change_percent")
            candidate_cols = st.columns(3)
            candidate_cols[0].metric("Score", f"{top.scores.get('total', 0.0):.2f}")
            candidate_cols[1].metric("Live price", f"${live_price:.2f}" if live_price is not None else "n/a")
            candidate_cols[2].metric("Live change", fmt_pct(live_change_pct))
            st.write(key_watch_note(top))
        with top_cols[1]:
            st.markdown("**Action checklist**")
            for item in action_checklist(top):
                st.write(f"- {item}")

    chart_cols = st.columns([1, 1.4])
    with chart_cols[0]:
        if not decisions.empty:
            mix = decisions.groupby("Decision", as_index=False).size().rename(columns={"size": "Count"})
            chart = (
                alt.Chart(mix)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("Decision:N", sort=None),
                    y=alt.Y("Count:Q", title="Stocks"),
                    color=alt.Color("Decision:N", legend=None),
                    tooltip=["Decision", "Count"],
                )
                .properties(height=240)
            )
            st.altair_chart(chart, use_container_width=True)
    with chart_cols[1]:
        score_rows = []
        for report in ranked[:10]:
            for label, key in (
                ("Price trend", "price_trend"),
                ("Fundamentals", "sec_fundamentals"),
                ("News", "news_sentiment"),
            ):
                score_rows.append(
                    {
                        "Ticker": report.ticker,
                        "Component": label,
                        "Score": report.scores.get(key, 0.0),
                    }
                )
        if score_rows:
            score_frame = pd.DataFrame(score_rows)
            score_chart = (
                alt.Chart(score_frame)
                .mark_bar()
                .encode(
                    x=alt.X("Score:Q", title="Component score"),
                    y=alt.Y("Ticker:N", sort=[report.ticker for report in ranked[:10]]),
                    color=alt.Color("Component:N"),
                    tooltip=["Ticker", "Component", alt.Tooltip("Score:Q", format=".2f")],
                )
                .properties(height=240)
            )
            st.altair_chart(score_chart, use_container_width=True)

    st.subheader("Watchlist Decision Cards")
    for start in range(0, min(len(ranked), 6), 3):
        cols = st.columns(3)
        for col, report in zip(cols, ranked[start : start + 3]):
            quote = live.get(report.ticker, {})
            live_price = quote.get("price")
            live_change_pct = quote.get("change_percent")
            with col:
                with st.container(border=True):
                    st.markdown(f"<div class='decision-label'>{decision_bucket(report)}</div>", unsafe_allow_html=True)
                    st.markdown(
                        f"**{report.ticker}** - "
                        f"<span class='{rating_class(report.rating)}'>{report.rating}</span>",
                        unsafe_allow_html=True,
                    )
                    if report.company:
                        st.caption(report.company)
                    st.metric("Score", f"{report.scores.get('total', 0.0):.2f}")
                    st.write(
                        f"Live: {f'${live_price:.2f}' if live_price is not None else 'n/a'} "
                        f"({fmt_pct(live_change_pct)})"
                    )
                    st.write(key_watch_note(report))
                    st.caption(f"Latest: {latest_headline(report)}")

    st.subheader("Market Review")
    render_market_snapshot(market_notes)

    st.subheader("Risks And Catalysts")
    board = risk_and_catalyst_rows(ranked)
    if board.empty:
        st.info("No risk or catalyst rows were identified from the collected notes.")
    else:
        st.dataframe(board.head(40), use_container_width=True, hide_index=True)


def render_source_links(ticker: str) -> None:
    col1, col2 = st.columns(2)
    col1.link_button("Yahoo Finance News", yahoo_news_url(ticker), use_container_width=True)
    col2.link_button("Moomoo Stock Page", moomoo_stock_url(ticker), use_container_width=True)


def render_market_snapshot(market_notes: list[str]) -> None:
    st.subheader("Market Snapshot")
    if not market_notes:
        st.info("Market context is not available yet.")
        return
    columns = st.columns(min(3, len(market_notes)))
    for index, note in enumerate(market_notes[:3]):
        columns[index % len(columns)].info(note)


def render_live_quotes(tickers: list[str]) -> pd.DataFrame:
    st.subheader("Live Stock Prices")
    st.caption("Quote data comes from Yahoo Finance quote fields and may be real-time or exchange-delayed depending on symbol, exchange, and source availability.")
    try:
        quotes = cached_live_quotes(tuple(tickers))
    except Exception as exc:
        st.warning(f"Could not load live quotes: {exc}")
        return pd.DataFrame()

    if quotes.empty:
        st.info("No live quote rows available.")
        return quotes

    numeric_quotes = quotes.copy()
    numeric_quotes["change_percent"] = pd.to_numeric(numeric_quotes["change_percent"], errors="coerce")
    numeric_quotes["price"] = pd.to_numeric(numeric_quotes["price"], errors="coerce")

    gainers = numeric_quotes.dropna(subset=["change_percent"]).sort_values("change_percent", ascending=False).head(3)
    decliners = numeric_quotes.dropna(subset=["change_percent"]).sort_values("change_percent").head(3)
    market_open = int((quotes["market_state"] == "REGULAR").sum()) if "market_state" in quotes else 0
    realtime_count = int((quotes["is_realtime"] == True).sum()) if "is_realtime" in quotes else 0

    metric_cols = st.columns(4)
    metric_cols[0].metric("Symbols", len(quotes))
    metric_cols[1].metric("Market open", market_open)
    metric_cols[2].metric("Real-time feed rows", realtime_count)
    metric_cols[3].metric("Last refresh", datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))

    mover_cols = st.columns(2)
    with mover_cols[0]:
        st.write("Top gainers")
        for _, row in gainers.iterrows():
            st.metric(str(row["ticker"]), f"${row['price']:.2f}" if pd.notna(row["price"]) else "n/a", f"{row['change_percent']:.2f}%")
    with mover_cols[1]:
        st.write("Top decliners")
        for _, row in decliners.iterrows():
            st.metric(str(row["ticker"]), f"${row['price']:.2f}" if pd.notna(row["price"]) else "n/a", f"{row['change_percent']:.2f}%")

    display = quotes[
        [
            "ticker",
            "name",
            "price",
            "change",
            "change_percent",
            "volume",
            "market_cap",
            "trailing_pe",
            "day_high",
            "day_low",
            "market_state",
            "Feed",
            "Updated",
            "Yahoo News",
            "Moomoo",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "name": "Name",
            "price": "Price",
            "change": "Change",
            "change_percent": "Change %",
            "volume": "Volume",
            "market_cap": "Market Cap",
            "trailing_pe": "Trailing P/E",
            "day_high": "Day High",
            "day_low": "Day Low",
            "market_state": "Market State",
        }
    )
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "Change": st.column_config.NumberColumn("Change", format="%.2f"),
            "Change %": st.column_config.NumberColumn("Change %", format="%.2f%%"),
            "Volume": st.column_config.NumberColumn("Volume", format="%d"),
            "Market Cap": st.column_config.NumberColumn("Market Cap", format="$%d"),
            "Trailing P/E": st.column_config.NumberColumn("Trailing P/E", format="%.2f"),
            "Day High": st.column_config.NumberColumn("Day High", format="$%.2f"),
            "Day Low": st.column_config.NumberColumn("Day Low", format="$%.2f"),
            "Yahoo News": st.column_config.LinkColumn("Yahoo News"),
            "Moomoo": st.column_config.LinkColumn("Moomoo"),
        },
    )
    return quotes


@st.fragment(run_every="60s")
def render_sgd_myr_live_fragment() -> None:
    try:
        meta, rates = cached_sgd_myr_live_history()
    except Exception as exc:
        st.warning(f"Could not load SGD/MYR data: {exc}")
        return

    if rates.empty:
        st.info("No SGD/MYR rate rows available.")
        return

    latest_time = rates["datetime"].iloc[-1]
    live_rates = rates[rates["datetime"] >= latest_time - timedelta(minutes=30)].copy()
    if live_rates.empty:
        live_rates = rates.tail(30).copy()

    latest = float(live_rates["close"].iloc[-1])
    first = float(live_rates["close"].iloc[0])
    change = latest - first
    change_pct = (change / first * 100.0) if first else 0.0
    range_high = float(live_rates["high"].dropna().max()) if "high" in live_rates and not live_rates["high"].dropna().empty else latest
    range_low = float(live_rates["low"].dropna().min()) if "low" in live_rates and not live_rates["low"].dropna().empty else latest
    st.session_state["sgd_myr_latest_rate"] = latest
    st.session_state["sgd_myr_latest_time"] = live_rates["datetime"].iloc[-1].isoformat()

    metric_cols = st.columns(3)
    metric_cols[0].metric("SGD/MYR", f"{latest:.4f}", f"{change_pct:.2f}% / 30m")
    metric_cols[1].metric("30m high", f"{range_high:.4f}")
    metric_cols[2].metric("30m low", f"{range_low:.4f}")

    st.subheader("Live 30-Minute Rate Chart")
    chart_min = float(live_rates["close"].min())
    chart_max = float(live_rates["close"].max())
    padding = max((chart_max - chart_min) * 0.25, 0.0003)
    chart = (
        alt.Chart(live_rates)
        .mark_line(point=True)
        .encode(
            x=alt.X("datetime:T", title="Time"),
            y=alt.Y(
                "close:Q",
                title="SGD to MYR",
                scale=alt.Scale(domain=[chart_min - padding, chart_max + padding], zero=False),
            ),
            tooltip=[
                alt.Tooltip("datetime:T", title="Time"),
                alt.Tooltip("close:Q", title="Rate", format=".5f"),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, use_container_width=True)

    last_update = live_rates["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M UTC")
    st.caption(
        f"Last data point: {last_update}. "
        f"Yahoo symbol: SGDMYR=X. Exchange timezone: {meta.get('exchangeTimezoneName', 'n/a')}."
    )

    with st.expander("Live 30-Minute Rate Table"):
        display = live_rates.sort_values("datetime", ascending=False).copy()
        display["datetime"] = display["datetime"].dt.strftime("%Y-%m-%d %H:%M UTC")
        st.dataframe(
            display.rename(
                columns={
                    "datetime": "Time",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Rate",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Open": st.column_config.NumberColumn("Open", format="%.5f"),
                "High": st.column_config.NumberColumn("High", format="%.5f"),
                "Low": st.column_config.NumberColumn("Low", format="%.5f"),
                "Rate": st.column_config.NumberColumn("Rate", format="%.5f"),
            },
        )

def render_sgd_myr_historical_section() -> None:
    with st.expander("Historical chart"):
        period = st.selectbox("Historical range", list(SGD_MYR_PERIODS.keys()), index=2)
        chart_range, interval = SGD_MYR_PERIODS[period]
        try:
            _, historical_rates = cached_sgd_myr_history(chart_range, interval)
        except Exception as exc:
            st.warning(f"Could not load historical SGD/MYR data: {exc}")
            historical_rates = pd.DataFrame()

        if not historical_rates.empty:
            history_min = float(historical_rates["close"].min())
            history_max = float(historical_rates["close"].max())
            history_padding = max((history_max - history_min) * 0.2, 0.0005)
            history_chart = (
                alt.Chart(historical_rates)
                .mark_line()
                .encode(
                    x=alt.X("datetime:T", title="Time"),
                    y=alt.Y(
                        "close:Q",
                        title="SGD to MYR",
                        scale=alt.Scale(domain=[history_min - history_padding, history_max + history_padding], zero=False),
                    ),
                    tooltip=[
                        alt.Tooltip("datetime:T", title="Time"),
                        alt.Tooltip("close:Q", title="Rate", format=".5f"),
                    ],
                )
                .properties(height=300)
            )
            st.altair_chart(history_chart, use_container_width=True)

        st.write("Historical rate table")
        if historical_rates.empty:
            st.info("No historical rate rows available.")
        else:
            display = historical_rates.copy()
            display["datetime"] = display["datetime"].dt.strftime("%Y-%m-%d %H:%M UTC")
            st.dataframe(
                display.rename(
                    columns={
                        "datetime": "Time",
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Rate",
                    }
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Open": st.column_config.NumberColumn("Open", format="%.5f"),
                    "High": st.column_config.NumberColumn("High", format="%.5f"),
                    "Low": st.column_config.NumberColumn("Low", format="%.5f"),
                    "Rate": st.column_config.NumberColumn("Rate", format="%.5f"),
                },
            )


def render_sgd_myr_tracker() -> None:
    st.title("Singapore to Malaysia Live Rate Tracker")
    st.caption("SGD/MYR exchange-rate tracker using Yahoo Finance chart data. The live rate block refreshes every 1 minute.")

    refresh = st.button("Refresh now", use_container_width=True)
    if refresh:
        cached_sgd_myr_live_history.clear()

    render_sgd_myr_live_fragment()
    render_sgd_myr_historical_section()

    st.subheader("SGD to MYR Converter")
    amount_sgd = st.number_input("Amount in SGD", min_value=0.0, value=1000.0, step=50.0)
    rate_used = st.session_state.get("sgd_myr_latest_rate")
    converted = amount_sgd * rate_used if rate_used else 0.0
    conversion_cols = st.columns(3)
    conversion_cols[0].metric("SGD amount", f"S${amount_sgd:,.2f}")
    conversion_cols[1].metric("Estimated MYR", f"RM{converted:,.2f}" if rate_used else "n/a")
    conversion_cols[2].metric("Rate used", f"{rate_used:.4f}" if rate_used else "n/a")

    st.info("For actual transfers, compare this market reference rate with your bank or money-transfer provider's quoted rate and fees.")


def render_rankings(reports: list[StockReport], quotes: pd.DataFrame | None = None) -> None:
    table = report_table(reports, quotes)
    if table.empty:
        st.info("No report rows available.")
        return

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.NumberColumn("Score", format="%.2f"),
            "Live Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
            "Live Change %": st.column_config.NumberColumn("Live Change %", format="%.2f%%"),
            "Trend Close": st.column_config.NumberColumn("Trend Close", format="$%.2f"),
            "1M": st.column_config.NumberColumn("1M", format="%.1f%%"),
            "3M": st.column_config.NumberColumn("3M", format="%.1f%%"),
            "1Y": st.column_config.NumberColumn("1Y", format="%.1f%%"),
            "Net Income": st.column_config.NumberColumn("Net Income", format="$%.0f"),
        },
    )


def render_news_center(reports: list[StockReport]) -> None:
    st.subheader("Important News")
    st.caption("Headlines are pulled from Yahoo Finance RSS and, when configured, Alpha Vantage news sentiment. Moomoo links are provided for manual source checks.")
    news = collect_news_rows(reports)
    if news.empty:
        st.info("No headlines were collected. Try Yahoo RSS or add an Alpha Vantage API key.")
        return

    source_options = ["All"] + sorted(news["Source"].dropna().unique().tolist())
    selected_source = st.selectbox("Source filter", source_options)
    if selected_source != "All":
        news = news[news["Source"] == selected_source]

    st.dataframe(
        news,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("Link"),
            "Sentiment": st.column_config.NumberColumn("Sentiment", format="%.2f"),
        },
    )

    st.write("Source shortcuts")
    source_rows = []
    for ticker in sorted({report.ticker for report in reports}):
        source_rows.append(
            {
                "Ticker": ticker,
                "Yahoo News": yahoo_news_url(ticker),
                "Moomoo": moomoo_stock_url(ticker),
            }
        )
    st.dataframe(
        pd.DataFrame(source_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Yahoo News": st.column_config.LinkColumn("Yahoo News"),
            "Moomoo": st.column_config.LinkColumn("Moomoo"),
        },
    )


def render_ticker_details(reports: list[StockReport], quotes: pd.DataFrame | None = None) -> None:
    ranked = sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True)
    selected = st.selectbox(
        "Ticker",
        options=[report.ticker for report in ranked],
        index=0,
    )
    report = next(item for item in ranked if item.ticker == selected)
    quote = quote_lookup(quotes if quotes is not None else pd.DataFrame()).get(report.ticker, {})

    left, right = st.columns([1.1, 1.4])
    with left:
        st.subheader(f"{report.ticker}")
        if report.company:
            st.caption(report.company)
        st.markdown(
            f"<span class='{rating_class(report.rating)}'>{report.rating}</span>",
            unsafe_allow_html=True,
        )

        score_cols = st.columns(3)
        score_cols[0].metric("Total", f"{report.scores.get('total', 0.0):.2f}")
        score_cols[1].metric("Price", f"{report.scores.get('price_trend', 0.0):.2f}")
        score_cols[2].metric("News", f"{report.scores.get('news_sentiment', 0.0):.2f}")

        if quote:
            live_cols = st.columns(3)
            live_price = quote.get("price")
            live_change_pct = quote.get("change_percent")
            live_cols[0].metric("Live price", f"${live_price:.2f}" if live_price is not None else "n/a")
            live_cols[1].metric("Live change", fmt_pct(live_change_pct))
            live_cols[2].metric("Feed", quote.get("Feed", "n/a"))

        price = report.price
        price_cols = st.columns(3)
        close = price.get("close")
        price_cols[0].metric("Close", f"${close:.2f}" if close else "n/a")
        price_cols[1].metric("1M", fmt_pct(price.get("return_1m_pct")))
        price_cols[2].metric("1Y", fmt_pct(price.get("return_1y_pct")))

        fundamentals = report.fundamentals
        st.write("Fundamentals")
        st.write(
            {
                "Revenue": fmt_money(fundamentals.get("revenue", {}).get("value")),
                "Net income": fmt_money(fundamentals.get("net_income", {}).get("value")),
                "Liabilities/assets": fmt_pct(
                    fundamentals.get("liabilities_to_assets") * 100
                    if fundamentals.get("liabilities_to_assets") is not None
                    else None
                ),
            }
        )
        render_source_links(report.ticker)

    with right:
        try:
            price_history = cached_price_history(report.ticker)
            if price_history.empty:
                st.info("No price history available.")
            else:
                chart_data = price_history.set_index("Date")[["Close"]].tail(260)
                st.line_chart(chart_data, use_container_width=True)
        except Exception as exc:
            st.warning(f"Could not render price chart: {exc}")

    detail_tabs = st.tabs(["Notes", "News", "Filings", "Source links", "Raw"])
    with detail_tabs[0]:
        for note in report.notes or ["No notes available."]:
            st.write(f"- {note}")
        for warning in report.warnings:
            st.warning(warning)

    with detail_tabs[1]:
        if not report.news:
            st.info("No recent headlines available.")
        for item in report.news:
            source = f" - {item.source}" if item.source else ""
            title = item.title or "Untitled"
            if item.url:
                st.markdown(f"- [{title}]({item.url}){source}")
            else:
                st.write(f"- {title}{source}")
            if item.summary:
                st.caption(item.summary[:240])

    with detail_tabs[2]:
        filings = report.filings.get("recent", [])
        if filings:
            st.dataframe(pd.DataFrame(filings), use_container_width=True, hide_index=True)
        else:
            st.info("No SEC filing rows available.")

    with detail_tabs[3]:
        render_source_links(report.ticker)
        st.info("Moomoo's official programmatic access uses OpenD/API infrastructure. This cloud app links to Moomoo pages but does not scrape authenticated Moomoo data.")

    with detail_tabs[4]:
        st.json(to_jsonable(report))


def render_downloads(reports: list[StockReport], market_notes: list[str], news_source: str) -> None:
    markdown = render_markdown(reports, market_notes, news_source, "stock_research.json")
    raw_json = payload_json(reports, market_notes, news_source)

    col1, col2 = st.columns(2)
    col1.download_button(
        "Download Markdown",
        data=markdown,
        file_name="stock_research_report.md",
        mime="text/markdown",
        use_container_width=True,
    )
    col2.download_button(
        "Download JSON",
        data=raw_json,
        file_name="stock_research_report.json",
        mime="application/json",
        use_container_width=True,
    )


def main() -> None:
    with st.sidebar:
        page = st.radio(
            "Page",
            ["Stocks & finance news", "SGD/MYR rate tracker"],
            index=0,
        )
        st.divider()

    if page == "SGD/MYR rate tracker":
        render_sgd_myr_tracker()
        return

    st.title("Real-Time Stock Price & Finance News Dashboard")
    st.caption("Live quote board, finance headlines, and research watchlist. Not financial advice.")

    with st.sidebar:
        st.header("Dashboard Universe")
        selected_groups = st.multiselect(
            "Notable stock groups",
            options=list(NOTABLE_STOCK_GROUPS.keys()),
            default=DEFAULT_GROUPS,
        )
        group_tickers = tickers_from_groups(selected_groups)
        ticker_input = st.text_area(
            "Tickers to analyze",
            value=", ".join(group_tickers or parse_tickers(DEFAULT_TICKERS)),
            height=135,
            help="Edit this list directly if you want to add or remove names.",
        )
        max_tickers = st.slider("Max tickers per refresh", min_value=5, max_value=40, value=24)
        sec_user_agent = st.text_input(
            "SEC User-Agent",
            value=DEFAULT_SEC_USER_AGENT,
            help="SEC asks automated tools to identify themselves with contact details.",
        )
        news_selection = st.selectbox(
            "News source",
            ["Auto", "Trusted: Yahoo + Alpha Vantage", "Yahoo RSS", "Alpha Vantage", "None"],
        )
        strategy_lens = st.selectbox(
            "Strategy lens",
            [
                "Balanced decision dashboard",
                "Momentum and trend",
                "News catalyst",
                "Fundamental quality",
                "Risk control",
            ],
            help="Changes the dashboard framing. Scores still come from the app's price, SEC, and news analysis.",
        )
        alpha_vantage_key = st.text_input("Alpha Vantage API key", value=DEFAULT_ALPHA_VANTAGE_KEY, type="password")
        news_limit = st.slider("Headlines per ticker", min_value=0, max_value=20, value=6)
        refresh_prices = st.button("Refresh prices now", use_container_width=True)
        run = st.button("Refresh news and research", type="primary", use_container_width=True)
        auto_refresh = st.checkbox("Auto-refresh prices", value=False)
        refresh_seconds = st.slider("Auto-refresh interval", min_value=30, max_value=300, value=DEFAULT_REFRESH_SECONDS, step=30)

        st.divider()
        st.markdown(
            "<p class='small-note'>Quote rows use Yahoo Finance quote fields and may be real-time or delayed. "
            "Scores combine price trend, SEC fundamentals, and trusted-news sentiment. "
            "Moomoo source links are included for manual checks; Moomoo API access requires OpenD credentials.</p>",
            unsafe_allow_html=True,
        )

    tickers = parse_tickers(ticker_input)[:max_tickers]
    news_source = resolved_news_source(news_selection, alpha_vantage_key)

    if not tickers:
        st.info("Enter at least one ticker.")
        return

    if refresh_prices:
        cached_live_quotes.clear()

    live_quotes = render_live_quotes(tickers)

    if run:
        if "contact@example.com" in sec_user_agent:
            st.warning("Replace the SEC User-Agent with your name and email before relying on SEC data.")
        with st.spinner("Gathering market data..."):
            reports, market_notes = analyze_reports(
                tickers=tickers,
                sec_user_agent=sec_user_agent or DEFAULT_SEC_USER_AGENT,
                alpha_vantage_key=alpha_vantage_key,
                news_source=news_source,
                news_limit=news_limit,
            )
        st.session_state["reports"] = reports
        st.session_state["market_notes"] = market_notes
        st.session_state["news_source"] = news_source

    reports = st.session_state.get("reports", [])
    market_notes = st.session_state.get("market_notes", [])
    current_news_source = st.session_state.get("news_source", news_source)

    if not reports:
        render_market_snapshot([])
        st.write("Use `Refresh news and research` to load finance headlines, rankings, SEC data, and watchlist analysis.")
        if auto_refresh:
            time.sleep(refresh_seconds)
            st.rerun()
        return

    render_summary(reports)

    tabs = st.tabs(["Decision dashboard", "Rankings", "Finance news", "Ticker detail", "Downloads"])
    with tabs[0]:
        render_decision_dashboard(reports, live_quotes, market_notes, strategy_lens)

    with tabs[1]:
        render_rankings(reports, live_quotes)

    with tabs[2]:
        render_news_center(reports)

    with tabs[3]:
        render_ticker_details(reports, live_quotes)

    with tabs[4]:
        render_downloads(reports, market_notes, current_news_source)

    if auto_refresh:
        time.sleep(refresh_seconds)
        st.rerun()


if __name__ == "__main__":
    main()
