from __future__ import annotations

import os
import json
import re
from datetime import datetime, timezone
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from stock_market_research import (
    DSAConfig,
    DSAStockReport,
    build_reports,
    config_from_env,
    fetch_price_history,
    fetch_sgd_myr_history,
    provider_health,
    report_to_dict,
)


st.set_page_config(
    page_title="Daily Stock Analysis Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


DEFAULT_TICKERS = os.getenv("STOCK_LIST", "600519, 300750, 002594, AAPL, NVDA, MSFT, hk00700")
NOTABLE_STOCK_GROUPS = {
    "A-share Core": ["600519", "300750", "002594", "000858", "601318", "600036"],
    "A-share Growth": ["300760", "300124", "002475", "603259", "688981", "300014"],
    "HK Tech": ["hk00700", "hk09988", "hk03690", "hk01810", "hk09868", "hk01211"],
    "US AI & Mega-Cap": ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "TSLA"],
    "US Semiconductors": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "QCOM", "MU"],
    "Market ETFs": ["SPY", "QQQ", "DIA", "IWM", "SMH", "XLK", "XLF"],
}
DEFAULT_GROUPS = ["A-share Core", "HK Tech", "US AI & Mega-Cap"]
STRATEGIES = ["Balanced", "Bull trend", "Event driven", "Risk first", "Growth quality"]
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
        ticker = part.strip()
        normalized = ticker.lower() if ticker.lower().startswith("hk") else ticker.upper()
        if normalized and not normalized.startswith("#") and normalized not in seen:
            tickers.append(normalized)
            seen.add(normalized)
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


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def fmt_price(value: Any, currency: str | None = None) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    prefix = {"USD": "$", "HKD": "HK$", "CNY": "¥"}.get(str(currency or "").upper(), "")
    return f"{prefix}{number:,.2f}"


def config_overrides_from_sidebar() -> DSAConfig:
    st.header("DSA Configuration")
    with st.expander("Source priorities", expanded=True):
        realtime_priority = st.text_input(
            "REALTIME_SOURCE_PRIORITY",
            value=os.getenv("REALTIME_SOURCE_PRIORITY", "tencent,akshare_sina,efinance,akshare_em"),
            help="Same environment variable used by ZhuLinsen/daily_stock_analysis for real-time quote priority.",
        )
        cn_history_priority = st.text_input(
            "CN_HISTORY_SOURCE_PRIORITY",
            value=os.getenv("CN_HISTORY_SOURCE_PRIORITY", "akshare,tushare,baostock,efinance"),
        )
        us_hk_history_priority = st.text_input(
            "US_HK_HISTORY_SOURCE_PRIORITY",
            value=os.getenv("US_HK_HISTORY_SOURCE_PRIORITY", "yfinance,longbridge"),
        )
        news_priority = st.text_input(
            "NEWS_PROVIDER_PRIORITY",
            value=os.getenv("NEWS_PROVIDER_PRIORITY", "brave,tavily,serpapi,searxng"),
        )
    with st.expander("Keys and switches", expanded=False):
        tushare_token = st.text_input("TUSHARE_TOKEN", value=os.getenv("TUSHARE_TOKEN", ""), type="password")
        brave_keys = st.text_input("BRAVE_API_KEYS", value=os.getenv("BRAVE_API_KEYS", ""), type="password")
        tavily_keys = st.text_input("TAVILY_API_KEYS", value=os.getenv("TAVILY_API_KEYS", ""), type="password")
        serpapi_keys = st.text_input("SERPAPI_API_KEYS", value=os.getenv("SERPAPI_API_KEYS", ""), type="password")
        searxng_urls = st.text_input("SEARXNG_BASE_URLS", value=os.getenv("SEARXNG_BASE_URLS", ""))
        enable_realtime = st.toggle("ENABLE_REALTIME_QUOTE", value=_env_bool("ENABLE_REALTIME_QUOTE", True))
        enable_realtime_tech = st.toggle("ENABLE_REALTIME_TECHNICAL_INDICATORS", value=_env_bool("ENABLE_REALTIME_TECHNICAL_INDICATORS", True))
        enable_fundamental = st.toggle("ENABLE_FUNDAMENTAL_PIPELINE", value=_env_bool("ENABLE_FUNDAMENTAL_PIPELINE", True))
        enable_chip = st.toggle("ENABLE_CHIP_DISTRIBUTION", value=_env_bool("ENABLE_CHIP_DISTRIBUTION", False))
        enable_eastmoney_patch = st.toggle("ENABLE_EASTMONEY_PATCH", value=_env_bool("ENABLE_EASTMONEY_PATCH", False))
    return config_from_env(
        {
            "REALTIME_SOURCE_PRIORITY": realtime_priority,
            "CN_HISTORY_SOURCE_PRIORITY": cn_history_priority,
            "US_HK_HISTORY_SOURCE_PRIORITY": us_hk_history_priority,
            "NEWS_PROVIDER_PRIORITY": news_priority,
            "TUSHARE_TOKEN": tushare_token,
            "BRAVE_API_KEYS": brave_keys,
            "TAVILY_API_KEYS": tavily_keys,
            "SERPAPI_API_KEYS": serpapi_keys,
            "SEARXNG_BASE_URLS": searxng_urls,
            "ENABLE_REALTIME_QUOTE": enable_realtime,
            "ENABLE_REALTIME_TECHNICAL_INDICATORS": enable_realtime_tech,
            "ENABLE_FUNDAMENTAL_PIPELINE": enable_fundamental,
            "ENABLE_CHIP_DISTRIBUTION": enable_chip,
            "ENABLE_EASTMONEY_PATCH": enable_eastmoney_patch,
        }
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@st.cache_data(ttl=60 * 15, show_spinner=False)
def cached_reports(
    tickers: tuple[str, ...],
    strategy: str,
    news_limit: int,
    config_payload: str,
) -> tuple[list[DSAStockReport], dict[str, Any]]:
    config = config_from_env(json.loads(config_payload))
    return build_reports(list(tickers), strategy, config=config, news_limit=news_limit)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_price_history(ticker: str, config_payload: str) -> pd.DataFrame:
    config = config_from_env(json.loads(config_payload))
    rows = [
        {
            "Date": item.date,
            "Open": item.open,
            "High": item.high,
            "Low": item.low,
            "Close": item.close,
            "Volume": item.volume,
        }
        for item in fetch_price_history(ticker, config=config)
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


def config_payload(config: DSAConfig) -> str:
    return json.dumps(
        {
            "REALTIME_SOURCE_PRIORITY": ",".join(config.realtime_source_priority),
            "CN_HISTORY_SOURCE_PRIORITY": ",".join(config.cn_history_priority),
            "US_HK_HISTORY_SOURCE_PRIORITY": ",".join(config.us_hk_history_priority),
            "NEWS_PROVIDER_PRIORITY": ",".join(config.news_provider_priority),
            "TUSHARE_TOKEN": config.tushare_token,
            "BRAVE_API_KEYS": config.brave_api_key,
            "TAVILY_API_KEYS": config.tavily_api_keys,
            "SERPAPI_API_KEYS": config.serpapi_api_keys,
            "SEARXNG_BASE_URLS": config.searxng_base_urls,
            "ENABLE_REALTIME_QUOTE": config.enable_realtime_quote,
            "ENABLE_REALTIME_TECHNICAL_INDICATORS": config.enable_realtime_technical_indicators,
            "ENABLE_FUNDAMENTAL_PIPELINE": config.enable_fundamental_pipeline,
            "ENABLE_CHIP_DISTRIBUTION": config.enable_chip_distribution,
            "ENABLE_EASTMONEY_PATCH": config.enable_eastmoney_patch,
        },
        sort_keys=True,
    )


def decision_frame(reports: list[DSAStockReport]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ticker": report.code,
                "Market": report.market.upper(),
                "Name": report.name,
                "Decision": decision_label(report.decision_type),
                "Score": report.sentiment_score,
                "Trend": report.trend_prediction,
                "Price": report.quote.get("price"),
                "Change %": report.quote.get("change_percent"),
                "Quote Source": report.quote.get("quote_source"),
                "Confidence": report.confidence_level,
                "Risks": len(report.risk_warning),
                "Catalysts": len(report.positive_catalysts),
            }
            for report in reports
        ]
    )


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
        fundamental_signal = report.dashboard.get("fundamental_proxy", {}).get("signal", "hold")
        rows.extend(
            [
                {"Ticker": report.code, "Component": "Decision score", "Score": report.sentiment_score},
                {"Ticker": report.code, "Component": "Technical confidence", "Score": report.technical.get("confidence", 0) * 100},
                {"Ticker": report.code, "Component": "Intel confidence", "Score": report.intelligence.get("confidence", 0) * 100},
                {"Ticker": report.code, "Component": "Technical signal", "Score": signal_score(technical_signal)},
                {"Ticker": report.code, "Component": "Intel signal", "Score": signal_score(intel_signal)},
                {"Ticker": report.code, "Component": "Fundamental proxy", "Score": signal_score(fundamental_signal)},
            ]
        )
    return pd.DataFrame(rows)


def signal_score(signal: str) -> int:
    return {"buy": 75, "hold": 50, "sell": 25}.get(signal, 50)


def render_stock_workspace() -> None:
    st.title("Daily Stock Analysis Workspace")
    st.caption(
        "DSA-style dashboard configured around AkShare, Tushare, Baostock, Efinance, YFinance, Longbridge, and search-provider news. "
        "Automated research support only, not financial advice."
    )

    with st.sidebar:
        st.header("Watchlist")
        selected_groups = st.multiselect("Stock groups", options=list(NOTABLE_STOCK_GROUPS.keys()), default=DEFAULT_GROUPS)
        group_tickers = tickers_from_groups(selected_groups)
        ticker_input = st.text_area("Stock list", value=", ".join(group_tickers or parse_tickers(DEFAULT_TICKERS)), height=130)
        max_tickers = st.slider("Max stocks per run", min_value=3, max_value=60, value=24)
        strategy = st.selectbox("Analysis strategy", STRATEGIES)
        news_limit = st.slider("Search-news items per stock", min_value=0, max_value=20, value=8)
        config = config_overrides_from_sidebar()
        refresh = st.button("Run DSA analysis", type="primary", use_container_width=True)
        st.divider()
        st.markdown(
            "<p class='muted'>Uses the upstream-style source configuration. The old Yahoo quote endpoint, Yahoo/Alpha Vantage news controls, SEC path, ticker-detail page, and downloads are not used on this page.</p>",
            unsafe_allow_html=True,
        )

    tickers = parse_tickers(ticker_input)[:max_tickers]
    if not tickers:
        st.info("Add at least one ticker to run the dashboard.")
        return
    if refresh:
        cached_reports.clear()

    payload = config_payload(config)
    if refresh or "dsa_reports" not in st.session_state or st.session_state.get("dsa_payload") != payload:
        with st.spinner("Building DSA decision dashboard from configured sources..."):
            reports, market_review = cached_reports(tuple(tickers), strategy, news_limit, payload)
        st.session_state["dsa_reports"] = reports
        st.session_state["dsa_market_review"] = market_review
        st.session_state["dsa_payload"] = payload
        history = st.session_state.setdefault("dsa_history", [])
        history.insert(0, {"time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "strategy": strategy, "tickers": ", ".join(tickers), "summary": market_review.get("summary", "")})
        st.session_state["dsa_history"] = history[:10]

    reports: list[DSAStockReport] = st.session_state.get("dsa_reports", [])
    market_review: dict[str, Any] = st.session_state.get("dsa_market_review", {})
    if not reports:
        st.info("Run DSA analysis to generate the decision dashboard.")
        return

    render_decision_header(reports, market_review)
    tabs = st.tabs(["Decision Dashboard", "Model Signals", "News & Catalysts", "Source Health", "Backtest"])
    with tabs[0]:
        render_decision_dashboard(reports)
    with tabs[1]:
        render_model_signals(reports, payload)
    with tabs[2]:
        render_news_intel(reports)
    with tabs[3]:
        render_source_health(reports, config)
    with tabs[4]:
        render_backtest(reports)


def render_decision_header(reports: list[DSAStockReport], market_review: dict[str, Any]) -> None:
    buy = sum(1 for report in reports if report.decision_type == "buy")
    hold = sum(1 for report in reports if report.decision_type == "hold")
    sell = sum(1 for report in reports if report.decision_type == "sell")
    avg_score = sum(report.sentiment_score for report in reports) / len(reports)
    risk_count = sum(len(report.risk_warning) for report in reports)
    low_conf = sum(1 for report in reports if report.confidence_level == "Low")
    cols = st.columns(6)
    cols[0].metric("Buy", buy)
    cols[1].metric("Watch", hold)
    cols[2].metric("Sell / Avoid", sell)
    cols[3].metric("Avg score", f"{avg_score:.1f}")
    cols[4].metric("Risk alerts", risk_count)
    cols[5].metric("Low confidence", low_conf)
    st.info(market_review.get("summary", "Market review unavailable."))


def render_decision_dashboard(reports: list[DSAStockReport]) -> None:
    table = decision_frame(reports)
    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Decision Board")
        st.dataframe(
            table.sort_values(["Decision", "Score"], ascending=[True, False]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "Price": st.column_config.NumberColumn("Price", format="%.2f"),
                "Change %": st.column_config.NumberColumn("Change %", format="%.2f%%"),
            },
        )
    with right:
        st.subheader("Signal Mix")
        mix = table.groupby("Decision", as_index=False).size().rename(columns={"size": "Count"})
        chart = (
            alt.Chart(mix)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(x=alt.X("Decision:N", sort=None), y=alt.Y("Count:Q", title="Stocks"), color=alt.Color("Decision:N", legend=None), tooltip=["Decision", "Count"])
            .properties(height=270)
        )
        st.altair_chart(chart, use_container_width=True)

    st.subheader("Action Feed")
    for start in range(0, min(9, len(reports)), 3):
        cols = st.columns(3)
        for col, report in zip(cols, reports[start : start + 3]):
            with col:
                with st.container(border=True):
                    st.markdown(f"<div class='label'>{report.market.upper()} | {decision_label(report.decision_type)}</div>", unsafe_allow_html=True)
                    st.markdown(f"### {report.code} <span class='{decision_class(report.decision_type)}'>{report.sentiment_score}/100</span>", unsafe_allow_html=True)
                    st.caption(f"{report.name} | {report.quote.get('quote_source', 'source n/a')}")
                    st.write(report.analysis_summary)
                    for item in report.checklist[:3]:
                        st.write(f"- {item}")


def render_model_signals(reports: list[DSAStockReport], payload: str) -> None:
    st.subheader("Model Signal Components")
    components = score_components_frame(reports)
    chart = (
        alt.Chart(components)
        .mark_bar()
        .encode(
            x=alt.X("Score:Q", title="0-100 score"),
            y=alt.Y("Ticker:N", sort=[report.code for report in reports]),
            color=alt.Color("Component:N"),
            tooltip=["Ticker", "Component", alt.Tooltip("Score:Q", format=".1f")],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, use_container_width=True)

    st.subheader("Price Context")
    selected = st.selectbox("Chart symbol", [report.code for report in reports])
    try:
        history = cached_price_history(selected, payload)
        if history.empty:
            st.info("No configured-source price history available.")
        else:
            st.line_chart(history.set_index("Date")[["Close"]].tail(260), use_container_width=True)
    except Exception as exc:
        st.warning(f"Price chart unavailable from configured sources: {exc}")

    st.subheader("Risk And Catalyst Feed")
    rows = []
    for report in reports:
        for item in report.risk_warning:
            rows.append({"Ticker": report.code, "Type": "Risk", "Item": item})
        for item in report.positive_catalysts:
            rows.append({"Ticker": report.code, "Type": "Catalyst", "Item": item})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No risk/catalyst rows generated.")


def render_news_intel(reports: list[DSAStockReport]) -> None:
    st.subheader("Search-Provider News And Intelligence")
    news = news_frame(reports)
    if news.empty:
        st.info("No news rows were collected. Configure BRAVE_API_KEYS, TAVILY_API_KEYS, SERPAPI_API_KEYS, or SEARXNG_BASE_URLS.")
        return
    impact = st.multiselect("Impact filter", sorted(news["Impact"].dropna().unique()), default=sorted(news["Impact"].dropna().unique()))
    filtered = news[news["Impact"].isin(impact)] if impact else news
    st.dataframe(
        filtered.sort_values(["Ticker", "Sentiment"], ascending=[True, False]),
        use_container_width=True,
        hide_index=True,
        column_config={"Sentiment": st.column_config.NumberColumn("Sentiment", format="%.2f"), "URL": st.column_config.LinkColumn("Link")},
    )


def render_source_health(reports: list[DSAStockReport], config: DSAConfig) -> None:
    st.subheader("Configured Provider Health")
    st.dataframe(pd.DataFrame(provider_health(config)), use_container_width=True, hide_index=True)
    st.subheader("Per-Symbol Source Attempts")
    rows = []
    for report in reports:
        rows.append(
            {
                "Ticker": report.code,
                "Successful Sources": ", ".join(report.source_status.get("successful", [])),
                "Attempted Sources": ", ".join(report.source_status.get("attempted", [])),
                "Limitations": " | ".join(report.data_limitations),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_backtest(reports: list[DSAStockReport]) -> None:
    st.subheader("Historical Signal Check")
    st.caption("DSA-style recent-return check using the configured historical source chain.")
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
            "Support": st.column_config.NumberColumn("Support", format="%.2f"),
            "Resistance": st.column_config.NumberColumn("Resistance", format="%.2f"),
        },
    )


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
    st.caption(f"FX reference symbol: SGDMYR=X. Exchange timezone: {meta.get('exchangeTimezoneName', 'n/a')}.")

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
    st.caption("SGD/MYR reference dashboard. Only the live block refreshes every minute.")
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
