from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from stock_market_research import (
    StockReport,
    analyze_market_context,
    analyze_ticker,
    fetch_price_history,
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


def rating_class(rating: str) -> str:
    if "Buy" in rating:
        return "rating-buy"
    if "Monitor" in rating:
        return "rating-monitor"
    if "Avoid" in rating:
        return "rating-avoid"
    return ""


def report_table(reports: list[StockReport]) -> pd.DataFrame:
    rows = []
    for report in sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True):
        price = report.price
        fundamentals = report.fundamentals
        rows.append(
            {
                "Ticker": report.ticker,
                "Company": report.company or "n/a",
                "Rating": report.rating,
                "Score": report.scores.get("total", 0.0),
                "Close": price.get("close"),
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


def render_rankings(reports: list[StockReport]) -> None:
    table = report_table(reports)
    if table.empty:
        st.info("No report rows available.")
        return

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.NumberColumn("Score", format="%.2f"),
            "Close": st.column_config.NumberColumn("Close", format="$%.2f"),
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


def render_ticker_details(reports: list[StockReport]) -> None:
    ranked = sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True)
    selected = st.selectbox(
        "Ticker",
        options=[report.ticker for report in ranked],
        index=0,
    )
    report = next(item for item in ranked if item.ticker == selected)

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
    st.title("Notable Stock Watch Dashboard")
    st.caption("Automated public-data research dashboard. Not financial advice.")

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
        alpha_vantage_key = st.text_input("Alpha Vantage API key", value=DEFAULT_ALPHA_VANTAGE_KEY, type="password")
        news_limit = st.slider("Headlines per ticker", min_value=0, max_value=20, value=6)
        run = st.button("Refresh dashboard", type="primary", use_container_width=True)

        st.divider()
        st.markdown(
            "<p class='small-note'>Scores combine price trend, SEC fundamentals, and trusted-news sentiment. "
            "Moomoo source links are included for manual checks; Moomoo API access requires OpenD credentials.</p>",
            unsafe_allow_html=True,
        )

    tickers = parse_tickers(ticker_input)[:max_tickers]
    news_source = resolved_news_source(news_selection, alpha_vantage_key)

    if not tickers:
        st.info("Enter at least one ticker.")
        return

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
        st.write("Choose the notable stock groups, then refresh the dashboard.")
        return

    render_summary(reports)

    tabs = st.tabs(["Overview", "Rankings", "Important news", "Ticker detail", "Downloads"])
    with tabs[0]:
        render_market_snapshot(market_notes)
        st.subheader("Current Watchlist Focus")
        top_reports = sorted(reports, key=lambda item: item.scores.get("total", 0.0), reverse=True)[:5]
        for report in top_reports:
            st.write(f"**{report.ticker}** - {report.rating}: {key_watch_note(report)}")

    with tabs[1]:
        render_rankings(reports)

    with tabs[2]:
        render_news_center(reports)

    with tabs[3]:
        render_ticker_details(reports)

    with tabs[4]:
        render_downloads(reports, market_notes, current_news_source)


if __name__ == "__main__":
    main()
