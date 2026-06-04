from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from stock_market_research import (
    DSAStockReport,
    build_reports,
    fetch_price_history,
    fetch_sgd_myr_history,
    fetch_yahoo_quotes,
    moomoo_stock_url,
    report_to_dict,
    render_markdown,
    reports_to_json,
    yahoo_news_url,
    yahoo_quote_url,
)


st.set_page_config(
    page_title="Daily Stock Analysis Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA"
DEFAULT_ALPHA_VANTAGE_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "") or os.getenv("ALPHA_VANTAGE_API_KEY", "")
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
STRATEGIES = ["Balanced", "Bull trend", "Event driven", "Risk first"]
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
        padding-top: 1.35rem;
        padding-bottom: 3rem;
        max-width: 1320px;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 0.72rem 0.82rem;
        background: #ffffff;
    }
    .decision-buy { color: #027a48; font-weight: 700; }
    .decision-hold { color: #b54708; font-weight: 700; }
    .decision-sell { color: #b42318; font-weight: 700; }
    .muted { color: #667085; font-size: 0.9rem; line-height: 1.35; }
    .label { color: #475467; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_tickers(raw: str) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[\s,;]+", raw):
        ticker = part.strip().upper()
        if ticker and not ticker.startswith("#") and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    return tickers


def tickers_from_groups(groups: list[str]) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for ticker in NOTABLE_STOCK_GROUPS.get(group, []):
            if ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)
    return tickers


def decision_class(decision: str) -> str:
    if decision == "buy":
        return "decision-buy"
    if decision == "sell":
        return "decision-sell"
    return "decision-hold"


def decision_label(decision: str) -> str:
    return {"buy": "Buy", "hold": "Watch", "sell": "Sell / Avoid"}.get(decision, "Watch")


def fmt_money(value: Any, currency: str = "$") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{currency}{number:,.2f}"


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/a"


@st.cache_data(ttl=30, show_spinner=False)
def cached_live_quotes(tickers: tuple[str, ...]) -> pd.DataFrame:
    rows = fetch_yahoo_quotes(list(tickers))
    for row in rows:
        ticker = str(row.get("ticker") or "")
        row["Yahoo Quote"] = yahoo_quote_url(ticker)
        row["Yahoo News"] = yahoo_news_url(ticker)
        row["Moomoo"] = moomoo_stock_url(ticker)
    return pd.DataFrame(rows)


@st.cache_data(ttl=60 * 15, show_spinner=False)
def cached_reports(
    tickers: tuple[str, ...],
    strategy: str,
    news_source: str,
    news_limit: int,
    alpha_vantage_key: str,
) -> tuple[list[DSAStockReport], dict[str, Any]]:
    return build_reports(list(tickers), strategy, news_source, news_limit, alpha_vantage_key)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_price_history(ticker: str) -> pd.DataFrame:
    rows = [
        {
            "Date": item.date,
            "Open": item.open,
            "High": item.high,
            "Low": item.low,
            "Close": item.close,
            "Volume": item.volume,
        }
        for item in fetch_price_history(ticker)
    ]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    return frame


@st.cache_data(ttl=300, show_spinner=False)
def cached_sgd_myr_history(chart_range: str, interval: str) -> tuple[dict[str, Any], pd.DataFrame]:
    payload = fetch_sgd_myr_history(chart_range, interval)
    frame = pd.DataFrame(payload.get("rows", []))
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values("datetime")
    return payload.get("meta", {}), frame


@st.cache_data(ttl=55, show_spinner=False)
def cached_sgd_myr_live_history() -> tuple[dict[str, Any], pd.DataFrame]:
    payload = fetch_sgd_myr_history("1d", "1m")
    frame = pd.DataFrame(payload.get("rows", []))
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values("datetime")
    return payload.get("meta", {}), frame


def decision_frame(reports: list[DSAStockReport]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ticker": report.code,
                "Name": report.name,
                "Decision": decision_label(report.decision_type),
                "Score": report.sentiment_score,
                "Trend": report.trend_prediction,
                "Confidence": report.confidence_level,
                "Advice": report.operation_advice,
                "Risks": len(report.risk_warning),
                "Catalysts": len(report.positive_catalysts),
                "Yahoo": report.source_links.get("Yahoo Quote"),
                "Moomoo": report.source_links.get("Moomoo"),
            }
            for report in reports
        ]
    ).sort_values("Score", ascending=False)


def news_frame(reports: list[DSAStockReport]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for report in reports:
        for item in report.news:
            rows.append(
                {
                    "Ticker": report.code,
                    "Impact": item.impact,
                    "Sentiment": item.sentiment,
                    "Source": item.source,
                    "Published": item.published,
                    "Headline": item.title,
                    "URL": item.url,
                }
            )
    return pd.DataFrame(rows)


def score_components_frame(reports: list[DSAStockReport]) -> pd.DataFrame:
    rows = []
    for report in reports:
        technical_signal = report.technical.get("signal", "hold")
        intel_signal = report.intelligence.get("signal", "hold")
        rows.extend(
            [
                {"Ticker": report.code, "Component": "Decision score", "Score": report.sentiment_score},
                {"Ticker": report.code, "Component": "Technical confidence", "Score": report.technical.get("confidence", 0) * 100},
                {"Ticker": report.code, "Component": "Intel confidence", "Score": report.intelligence.get("confidence", 0) * 100},
                {"Ticker": report.code, "Component": "Technical signal", "Score": signal_score(technical_signal)},
                {"Ticker": report.code, "Component": "Intel signal", "Score": signal_score(intel_signal)},
            ]
        )
    return pd.DataFrame(rows)


def signal_score(signal: str) -> int:
    return {"buy": 75, "hold": 50, "sell": 25}.get(signal, 50)


def render_stock_workspace() -> None:
    st.title("Daily Stock Analysis Workspace")
    st.caption(
        "Rebuilt as a Streamlit version of ZhuLinsen/daily_stock_analysis: watchlist analysis, "
        "decision dashboard, risk alerts, catalysts, market review, and report export."
    )

    with st.sidebar:
        st.header("Watchlist")
        selected_groups = st.multiselect(
            "Stock groups",
            options=list(NOTABLE_STOCK_GROUPS.keys()),
            default=DEFAULT_GROUPS,
        )
        group_tickers = tickers_from_groups(selected_groups)
        ticker_input = st.text_area(
            "Stock list",
            value=", ".join(group_tickers or parse_tickers(DEFAULT_TICKERS)),
            height=130,
        )
        max_tickers = st.slider("Max stocks per run", min_value=3, max_value=40, value=18)
        strategy = st.selectbox("Analysis strategy", STRATEGIES)
        news_source = st.selectbox("News source", ["Yahoo Finance", "Yahoo + Alpha Vantage", "Alpha Vantage", "None"])
        alpha_vantage_key = st.text_input("Alpha Vantage API key", value=DEFAULT_ALPHA_VANTAGE_KEY, type="password")
        news_limit = st.slider("News items per stock", min_value=0, max_value=15, value=6)
        refresh_quotes = st.button("Refresh quotes", use_container_width=True)
        run_analysis = st.button("Run DSA analysis", type="primary", use_container_width=True)
        st.divider()
        st.markdown(
            "<p class='muted'>Yahoo Finance is used for quotes/news. Moomoo pages are linked for manual checks; this app does not scrape authenticated Moomoo data.</p>",
            unsafe_allow_html=True,
        )

    tickers = parse_tickers(ticker_input)[:max_tickers]
    if not tickers:
        st.info("Add at least one ticker to run the dashboard.")
        return
    if refresh_quotes:
        cached_live_quotes.clear()
    if run_analysis:
        cached_reports.clear()

    quotes = pd.DataFrame()
    try:
        quotes = cached_live_quotes(tuple(tickers))
    except Exception as exc:
        st.warning(f"Live quotes unavailable: {exc}")

    if run_analysis or "dsa_reports" not in st.session_state:
        with st.spinner("Building DSA decision dashboard..."):
            source = "None" if news_source == "None" else news_source
            reports, market_review = cached_reports(
                tuple(tickers),
                strategy,
                source,
                news_limit,
                alpha_vantage_key,
            )
        st.session_state["dsa_reports"] = reports
        st.session_state["dsa_market_review"] = market_review
        history = st.session_state.setdefault("dsa_history", [])
        history.insert(
            0,
            {
                "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "strategy": strategy,
                "tickers": ", ".join(tickers),
                "summary": market_review.get("summary", ""),
            },
        )
        st.session_state["dsa_history"] = history[:10]

    reports: list[DSAStockReport] = st.session_state.get("dsa_reports", [])
    market_review: dict[str, Any] = st.session_state.get("dsa_market_review", {})
    if not reports:
        st.info("Run DSA analysis to generate the decision dashboard.")
        return

    render_decision_header(reports, market_review)

    tabs = st.tabs(["Decision Dashboard", "Stock Reports", "News & Intel", "Backtest", "History & Downloads"])
    with tabs[0]:
        render_decision_dashboard(reports, quotes, market_review)
    with tabs[1]:
        render_stock_reports(reports)
    with tabs[2]:
        render_news_intel(reports)
    with tabs[3]:
        render_backtest(reports)
    with tabs[4]:
        render_history_downloads(reports, market_review)


def render_decision_header(reports: list[DSAStockReport], market_review: dict[str, Any]) -> None:
    buy = sum(1 for report in reports if report.decision_type == "buy")
    hold = sum(1 for report in reports if report.decision_type == "hold")
    sell = sum(1 for report in reports if report.decision_type == "sell")
    avg_score = sum(report.sentiment_score for report in reports) / len(reports)
    risk_count = sum(len(report.risk_warning) for report in reports)
    top = max(reports, key=lambda item: item.sentiment_score)

    cols = st.columns(6)
    cols[0].metric("Buy", buy)
    cols[1].metric("Watch", hold)
    cols[2].metric("Sell / Avoid", sell)
    cols[3].metric("Avg score", f"{avg_score:.1f}")
    cols[4].metric("Risk alerts", risk_count)
    cols[5].metric("Top stock", top.code)
    st.info(market_review.get("summary", "Market review unavailable."))


def render_decision_dashboard(
    reports: list[DSAStockReport],
    quotes: pd.DataFrame,
    market_review: dict[str, Any],
) -> None:
    ranked = sorted(reports, key=lambda item: item.sentiment_score, reverse=True)
    table = decision_frame(ranked)

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Decision Board")
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "Yahoo": st.column_config.LinkColumn("Yahoo"),
                "Moomoo": st.column_config.LinkColumn("Moomoo"),
            },
        )
    with right:
        st.subheader("Signal Mix")
        mix = table.groupby("Decision", as_index=False).size().rename(columns={"size": "Count"})
        chart = (
            alt.Chart(mix)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("Decision:N", sort=None),
                y=alt.Y("Count:Q", title="Stocks"),
                color=alt.Color("Decision:N", legend=None),
                tooltip=["Decision", "Count"],
            )
            .properties(height=270)
        )
        st.altair_chart(chart, use_container_width=True)

    st.subheader("Score Breakdown")
    components = score_components_frame(ranked[:10])
    score_chart = (
        alt.Chart(components)
        .mark_bar()
        .encode(
            x=alt.X("Score:Q", title="0-100 score"),
            y=alt.Y("Ticker:N", sort=[report.code for report in ranked[:10]]),
            color=alt.Color("Component:N"),
            tooltip=["Ticker", "Component", alt.Tooltip("Score:Q", format=".1f")],
        )
        .properties(height=320)
    )
    st.altair_chart(score_chart, use_container_width=True)

    st.subheader("Top Decision Cards")
    for start in range(0, min(6, len(ranked)), 3):
        cols = st.columns(3)
        for col, report in zip(cols, ranked[start : start + 3]):
            with col:
                with st.container(border=True):
                    st.markdown(f"<div class='label'>{decision_label(report.decision_type)}</div>", unsafe_allow_html=True)
                    st.markdown(
                        f"### {report.code} <span class='{decision_class(report.decision_type)}'>{report.sentiment_score}/100</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(report.name)
                    st.write(report.analysis_summary)
                    for item in report.checklist[:3]:
                        st.write(f"- {item}")
                    st.link_button("Yahoo", report.source_links["Yahoo Quote"], use_container_width=True)

    if not quotes.empty:
        st.subheader("Live Quote Board")
        st.dataframe(
            quotes,
            use_container_width=True,
            hide_index=True,
            column_config={
                "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                "change_percent": st.column_config.NumberColumn("Change %", format="%.2f%%"),
                "market_cap": st.column_config.NumberColumn("Market Cap", format="$%d"),
                "Yahoo Quote": st.column_config.LinkColumn("Yahoo Quote"),
                "Yahoo News": st.column_config.LinkColumn("Yahoo News"),
                "Moomoo": st.column_config.LinkColumn("Moomoo"),
            },
        )


def render_stock_reports(reports: list[DSAStockReport]) -> None:
    ranked = sorted(reports, key=lambda item: item.sentiment_score, reverse=True)
    selected = st.selectbox("Stock", [report.code for report in ranked])
    report = next(item for item in ranked if item.code == selected)

    top_cols = st.columns([1, 1, 1, 1])
    top_cols[0].metric("Decision", decision_label(report.decision_type))
    top_cols[1].metric("Score", f"{report.sentiment_score}/100")
    top_cols[2].metric("Trend", report.trend_prediction)
    top_cols[3].metric("Confidence", report.confidence_level)
    st.write(report.analysis_summary)

    chart_col, detail_col = st.columns([1.35, 1])
    with chart_col:
        try:
            history = cached_price_history(report.code)
            if history.empty:
                st.info("No price history available.")
            else:
                st.line_chart(history.set_index("Date")[["Close"]].tail(260), use_container_width=True)
        except Exception as exc:
            st.warning(f"Price chart unavailable: {exc}")
    with detail_col:
        st.subheader("Operation Advice")
        st.write(report.operation_advice)
        st.subheader("Phase Decision")
        phase = report.dashboard.get("phase_decision", {})
        st.write(f"Window: {phase.get('action_window', 'n/a')}")
        st.write(f"Next check: {phase.get('next_check_time', 'n/a')}")
        st.write(phase.get("confidence_reason", ""))

    sub_tabs = st.tabs(["Key Points", "Risks", "Catalysts", "News", "Raw"])
    with sub_tabs[0]:
        for item in report.key_points or ["No key points available."]:
            st.write(f"- {item}")
    with sub_tabs[1]:
        for item in report.risk_warning or ["No major risk alerts detected."]:
            st.warning(item)
    with sub_tabs[2]:
        for item in report.positive_catalysts or ["No positive catalysts detected."]:
            st.success(item)
    with sub_tabs[3]:
        if not report.news:
            st.info("No news collected.")
        for item in report.news:
            st.markdown(f"- [{item.title}]({item.url}) - {item.source} ({item.impact})")
            if item.summary:
                st.caption(item.summary[:260])
    with sub_tabs[4]:
        st.json(report_to_dict(report))


def render_news_intel(reports: list[DSAStockReport]) -> None:
    st.subheader("News And Intelligence")
    news = news_frame(reports)
    if news.empty:
        st.info("No news rows were collected. Use Yahoo Finance news or configure Alpha Vantage.")
        return
    impact = st.multiselect("Impact filter", sorted(news["Impact"].dropna().unique()), default=sorted(news["Impact"].dropna().unique()))
    filtered = news[news["Impact"].isin(impact)] if impact else news
    st.dataframe(
        filtered.sort_values(["Ticker", "Sentiment"], ascending=[True, False]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sentiment": st.column_config.NumberColumn("Sentiment", format="%.2f"),
            "URL": st.column_config.LinkColumn("Link"),
        },
    )


def render_backtest(reports: list[DSAStockReport]) -> None:
    st.subheader("Simple Historical Check")
    st.caption("A lightweight DSA-style review of recent returns. It is not a full strategy simulator.")
    rows = []
    for report in reports:
        tech = report.technical
        rows.append(
            {
                "Ticker": report.code,
                "Decision": decision_label(report.decision_type),
                "Score": report.sentiment_score,
                "1M return": tech.get("return_1m_pct"),
                "3M return": tech.get("return_3m_pct"),
                "1Y return": tech.get("return_1y_pct"),
                "RSI14": tech.get("rsi14"),
                "Support": tech.get("support"),
                "Resistance": tech.get("resistance"),
            }
        )
    st.dataframe(
        pd.DataFrame(rows).sort_values("Score", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
            "1M return": st.column_config.NumberColumn("1M return", format="%.2f%%"),
            "3M return": st.column_config.NumberColumn("3M return", format="%.2f%%"),
            "1Y return": st.column_config.NumberColumn("1Y return", format="%.2f%%"),
            "RSI14": st.column_config.NumberColumn("RSI14", format="%.1f"),
            "Support": st.column_config.NumberColumn("Support", format="$%.2f"),
            "Resistance": st.column_config.NumberColumn("Resistance", format="$%.2f"),
        },
    )


def render_history_downloads(reports: list[DSAStockReport], market_review: dict[str, Any]) -> None:
    st.subheader("Session Analysis History")
    history = pd.DataFrame(st.session_state.get("dsa_history", []))
    if history.empty:
        st.info("No session history yet.")
    else:
        st.dataframe(history, use_container_width=True, hide_index=True)

    markdown = render_markdown(reports, market_review)
    raw_json = reports_to_json(reports, market_review)
    col1, col2 = st.columns(2)
    col1.download_button("Download Markdown Report", markdown, "daily_stock_analysis_report.md", "text/markdown", use_container_width=True)
    col2.download_button("Download JSON Payload", raw_json, "daily_stock_analysis_report.json", "application/json", use_container_width=True)


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
    live_rates = rates.dropna(subset=["close"]).tail(30)
    if live_rates.empty:
        st.info("No live SGD/MYR close values available.")
        return
    latest = float(live_rates["close"].iloc[-1])
    first = float(live_rates["close"].iloc[0])
    change_pct = (latest / first - 1.0) * 100.0 if first else 0.0
    high = float(live_rates["high"].dropna().max()) if "high" in live_rates else latest
    low = float(live_rates["low"].dropna().min()) if "low" in live_rates else latest
    st.session_state["sgd_myr_latest_rate"] = latest

    cols = st.columns(3)
    cols[0].metric("SGD/MYR", f"{latest:.4f}", f"{change_pct:.2f}% / 30m")
    cols[1].metric("30m high", f"{high:.4f}")
    cols[2].metric("30m low", f"{low:.4f}")

    padding = max((high - low) * 0.2, 0.0005)
    chart = (
        alt.Chart(live_rates)
        .mark_line(point=True)
        .encode(
            x=alt.X("datetime:T", title="Time"),
            y=alt.Y("close:Q", title="SGD/MYR", scale=alt.Scale(domain=[low - padding, high + padding])),
            tooltip=[alt.Tooltip("datetime:T", title="Time"), alt.Tooltip("close:Q", title="Rate", format=".5f")],
        )
        .properties(height=320)
    )
    st.subheader("Live 30-Minute Rate Chart")
    st.altair_chart(chart, use_container_width=True)
    st.caption(f"Yahoo symbol: SGDMYR=X. Exchange timezone: {meta.get('exchangeTimezoneName', 'n/a')}.")

    with st.expander("Live 30-Minute Rate Table"):
        display = live_rates.sort_values("datetime", ascending=False).copy()
        display["datetime"] = display["datetime"].dt.strftime("%Y-%m-%d %H:%M UTC")
        st.dataframe(display.rename(columns={"datetime": "Time", "close": "Rate"}), use_container_width=True, hide_index=True)


def render_sgd_myr_historical_section() -> None:
    with st.expander("Historical data", expanded=True):
        period = st.selectbox("Historical range", list(SGD_MYR_PERIODS.keys()), index=2)
        chart_range, interval = SGD_MYR_PERIODS[period]
        try:
            _, history = cached_sgd_myr_history(chart_range, interval)
        except Exception as exc:
            st.warning(f"Could not load historical SGD/MYR data: {exc}")
            return
        if history.empty:
            st.info("No historical rows available.")
            return
        valid = history.dropna(subset=["close"])
        chart = (
            alt.Chart(valid)
            .mark_line()
            .encode(
                x=alt.X("datetime:T", title="Time"),
                y=alt.Y("close:Q", title="SGD/MYR", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("datetime:T", title="Time"), alt.Tooltip("close:Q", title="Rate", format=".5f")],
            )
            .properties(height=320)
        )
        st.altair_chart(chart, use_container_width=True)


def render_sgd_myr_tracker() -> None:
    st.title("Singapore to Malaysia Live Rate Tracker")
    st.caption("SGD/MYR reference dashboard using Yahoo Finance chart data. Only the live block refreshes every minute.")
    if st.button("Refresh now", use_container_width=True):
        cached_sgd_myr_live_history.clear()
    render_sgd_myr_live_fragment()
    render_sgd_myr_historical_section()

    st.subheader("SGD to MYR Converter")
    amount = st.number_input("Amount in SGD", min_value=0.0, value=1000.0, step=50.0)
    rate = st.session_state.get("sgd_myr_latest_rate")
    cols = st.columns(3)
    cols[0].metric("SGD amount", f"S${amount:,.2f}")
    cols[1].metric("Estimated MYR", f"RM{amount * rate:,.2f}" if rate else "n/a")
    cols[2].metric("Rate used", f"{rate:.4f}" if rate else "n/a")
    st.info("For actual transfers, compare this market reference rate with your bank or money-transfer provider's quoted rate and fees.")


def main() -> None:
    with st.sidebar:
        page = st.radio("Page", ["Daily Stock Analysis", "SGD/MYR rate tracker"], index=0)
        st.divider()
    if page == "SGD/MYR rate tracker":
        render_sgd_myr_tracker()
    else:
        render_stock_workspace()


if __name__ == "__main__":
    main()
