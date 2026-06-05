from __future__ import annotations

import csv
import json
import math
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search?q={query}&count={limit}&freshness=pd"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SERPAPI_NEWS_URL = "https://serpapi.com/search.json?engine=google_news&q={query}&api_key={api_key}"


@dataclass
class PricePoint:
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


@dataclass
class NewsItem:
    title: str
    url: str = ""
    source: str = ""
    published: str = ""
    summary: str = ""
    impact: str = "neutral"
    sentiment: float = 0.0


@dataclass
class DSAConfig:
    realtime_source_priority: list[str] = field(default_factory=lambda: ["tencent", "akshare_sina", "efinance", "akshare_em"])
    cn_history_priority: list[str] = field(default_factory=lambda: ["akshare", "tushare", "baostock", "efinance"])
    us_hk_history_priority: list[str] = field(default_factory=lambda: ["yfinance", "longbridge"])
    news_provider_priority: list[str] = field(default_factory=lambda: ["brave", "tavily", "serpapi", "searxng"])
    enable_realtime_quote: bool = True
    enable_realtime_technical_indicators: bool = True
    enable_fundamental_pipeline: bool = True
    enable_chip_distribution: bool = False
    enable_eastmoney_patch: bool = False
    news_max_age_days: int = 3
    tushare_token: str = ""
    brave_api_key: str = ""
    tavily_api_keys: str = ""
    serpapi_api_keys: str = ""
    searxng_base_urls: str = ""
    longbridge_configured: bool = False


@dataclass
class DSAStockReport:
    code: str
    name: str = ""
    market: str = "us"
    sentiment_score: int = 50
    decision_type: str = "hold"
    confidence_level: str = "Medium"
    trend_prediction: str = "Range-bound"
    operation_advice: str = "Watch for confirmation"
    analysis_summary: str = ""
    key_points: list[str] = field(default_factory=list)
    risk_warning: list[str] = field(default_factory=list)
    positive_catalysts: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    dashboard: dict[str, Any] = field(default_factory=dict)
    quote: dict[str, Any] = field(default_factory=dict)
    technical: dict[str, Any] = field(default_factory=dict)
    intelligence: dict[str, Any] = field(default_factory=dict)
    news: list[NewsItem] = field(default_factory=list)
    source_links: dict[str, str] = field(default_factory=dict)
    source_status: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_limitations: list[str] = field(default_factory=list)


def split_priority(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    return items or list(default)


def config_from_env(overrides: dict[str, Any] | None = None) -> DSAConfig:
    overrides = overrides or {}
    config = DSAConfig(
        realtime_source_priority=split_priority(
            str(overrides.get("REALTIME_SOURCE_PRIORITY") or os.getenv("REALTIME_SOURCE_PRIORITY", "")),
            ["tencent", "akshare_sina", "efinance", "akshare_em"],
        ),
        cn_history_priority=split_priority(
            str(overrides.get("CN_HISTORY_SOURCE_PRIORITY") or os.getenv("CN_HISTORY_SOURCE_PRIORITY", "")),
            ["akshare", "tushare", "baostock", "efinance"],
        ),
        us_hk_history_priority=split_priority(
            str(overrides.get("US_HK_HISTORY_SOURCE_PRIORITY") or os.getenv("US_HK_HISTORY_SOURCE_PRIORITY", "")),
            ["yfinance", "longbridge"],
        ),
        news_provider_priority=split_priority(
            str(overrides.get("NEWS_PROVIDER_PRIORITY") or os.getenv("NEWS_PROVIDER_PRIORITY", "")),
            ["brave", "tavily", "serpapi", "searxng"],
        ),
        enable_realtime_quote=_env_bool("ENABLE_REALTIME_QUOTE", True, overrides),
        enable_realtime_technical_indicators=_env_bool("ENABLE_REALTIME_TECHNICAL_INDICATORS", True, overrides),
        enable_fundamental_pipeline=_env_bool("ENABLE_FUNDAMENTAL_PIPELINE", True, overrides),
        enable_chip_distribution=_env_bool("ENABLE_CHIP_DISTRIBUTION", False, overrides),
        enable_eastmoney_patch=_env_bool("ENABLE_EASTMONEY_PATCH", False, overrides),
        news_max_age_days=int(overrides.get("NEWS_MAX_AGE_DAYS") or os.getenv("NEWS_MAX_AGE_DAYS", "3") or 3),
        tushare_token=str(overrides.get("TUSHARE_TOKEN") or os.getenv("TUSHARE_TOKEN", "")),
        brave_api_key=str(overrides.get("BRAVE_API_KEYS") or os.getenv("BRAVE_API_KEYS", "")).split(",")[0].strip(),
        tavily_api_keys=str(overrides.get("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEYS", "")),
        serpapi_api_keys=str(overrides.get("SERPAPI_API_KEYS") or os.getenv("SERPAPI_API_KEYS", "")),
        searxng_base_urls=str(overrides.get("SEARXNG_BASE_URLS") or os.getenv("SEARXNG_BASE_URLS", "")),
        longbridge_configured=bool(
            overrides.get("LONGBRIDGE_OAUTH_CLIENT_ID")
            or os.getenv("LONGBRIDGE_OAUTH_CLIENT_ID")
            or os.getenv("LONGBRIDGE_APP_KEY")
        ),
    )
    return config


def _env_bool(name: str, default: bool, overrides: dict[str, Any]) -> bool:
    if name in overrides:
        value = overrides[name]
    else:
        value = os.getenv(name)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def provider_health(config: DSAConfig) -> list[dict[str, Any]]:
    providers = [
        ("akshare", "Market data", _module_available("akshare"), "Default free A-share source using Eastmoney paths."),
        ("tushare", "Market data", _module_available("tushare") and bool(config.tushare_token), "More stable/comprehensive A-share source when TUSHARE_TOKEN is set."),
        ("baostock", "Market data", _module_available("baostock"), "Free A-share fallback."),
        ("efinance", "Market data", _module_available("efinance"), "Eastmoney-based A-share quote/history fallback."),
        ("yfinance", "Market data", _module_available("yfinance"), "Required for US/HK historical and quote data."),
        ("longbridge", "Market data", config.longbridge_configured, "Optional US/HK field fallback when Longbridge credentials are configured."),
        ("brave", "News search", bool(config.brave_api_key), "Recommended external news search provider."),
        ("tavily", "News search", bool(config.tavily_api_keys), "Recommended external search/news provider."),
        ("serpapi", "News search", bool(config.serpapi_api_keys), "Google News search via SerpAPI."),
        ("searxng", "News search", bool(config.searxng_base_urls), "Private/public SearXNG JSON search endpoint."),
    ]
    return [
        {"Provider": name, "Role": role, "Ready": ready, "Notes": notes}
        for name, role, ready, notes in providers
    ]


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def classify_market(ticker: str) -> str:
    code = ticker.strip().lower()
    if code.startswith("hk") or code.endswith(".hk"):
        return "hk"
    if code.isdigit() and len(code) == 6:
        return "cn"
    return "us"


def normalize_code(ticker: str) -> str:
    value = ticker.strip()
    if value.lower().startswith("hk"):
        digits = value[2:].zfill(5)
        return f"hk{digits}"
    return value.upper()


def display_symbol(ticker: str) -> str:
    market = classify_market(ticker)
    code = normalize_code(ticker)
    if market == "hk":
        return code.lower()
    return code.upper()


def yfinance_symbol(ticker: str) -> str:
    code = normalize_code(ticker)
    market = classify_market(code)
    if market == "hk":
        digits = code.lower().replace("hk", "").replace(".hk", "").zfill(4)
        return f"{digits}.HK"
    if market == "cn":
        suffix = ".SS" if code.startswith(("6", "9")) else ".SZ"
        return f"{code}{suffix}"
    return code.replace(".", "-").upper()


def tushare_code(ticker: str) -> str:
    code = normalize_code(ticker)
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def baostock_code(ticker: str) -> str:
    code = normalize_code(ticker)
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    return f"{prefix}.{code}"


def source_url(ticker: str) -> str:
    market = classify_market(ticker)
    code = normalize_code(ticker)
    if market == "cn":
        return f"https://quote.eastmoney.com/{tushare_code(code).replace('.', '')}.html"
    if market == "hk":
        digits = code.lower().replace("hk", "").replace(".hk", "").zfill(5)
        return f"https://www.longbridge.com/hk/quote/hk{digits}"
    return f"https://finance.yahoo.com/quote/{urllib.parse.quote(yfinance_symbol(code))}/"


def fetch_text(url: str, timeout: int = 20, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "Mozilla/5.0 stock-analysis-dashboard/2.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(
    url: str,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    method: str | None = None,
) -> Any:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers or {"User-Agent": "Mozilla/5.0 stock-analysis-dashboard/2.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def build_reports(
    tickers: list[str],
    strategy: str,
    config: DSAConfig | None = None,
    news_limit: int = 6,
) -> tuple[list[DSAStockReport], dict[str, Any]]:
    config = config or config_from_env()
    reports = []
    for ticker in tickers:
        code = display_symbol(ticker)
        limitations: list[str] = []
        source_status: dict[str, Any] = {"attempted": [], "successful": []}
        history = fetch_price_history(code, config, limitations, source_status)
        quote = fetch_realtime_quote(code, config, history, limitations, source_status)
        news = fetch_market_news(code, quote.get("name") or code, news_limit, config, limitations, source_status)
        report = synthesize_dsa_report(code, quote, history, news, strategy, limitations, source_status)
        reports.append(report)
        time.sleep(0.05)
    return reports, build_market_review(reports, config)


def fetch_price_history(
    ticker: str,
    config: DSAConfig | None = None,
    limitations: list[str] | None = None,
    source_status: dict[str, Any] | None = None,
) -> list[PricePoint]:
    config = config or config_from_env()
    limitations = limitations if limitations is not None else []
    source_status = source_status if source_status is not None else {"attempted": [], "successful": []}
    market = classify_market(ticker)
    priority = config.cn_history_priority if market == "cn" else config.us_hk_history_priority
    errors: list[str] = []
    for provider in priority:
        source_status["attempted"].append(f"history:{provider}")
        try:
            if provider == "akshare":
                rows = _fetch_akshare_history(ticker)
            elif provider == "tushare":
                rows = _fetch_tushare_history(ticker, config.tushare_token)
            elif provider == "baostock":
                rows = _fetch_baostock_history(ticker)
            elif provider == "efinance":
                rows = _fetch_efinance_history(ticker)
            elif provider == "yfinance":
                rows = _fetch_yfinance_history(ticker)
            elif provider == "longbridge":
                rows = []
                errors.append("longbridge history is configured as optional field fallback, not primary K-line source in this Streamlit adapter")
            else:
                rows = []
            if rows:
                source_status["successful"].append(f"history:{provider}")
                return rows
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    if errors:
        limitations.append("Price history unavailable from configured DSA sources: " + "; ".join(errors[:4]))
    return []


def fetch_realtime_quote(
    ticker: str,
    config: DSAConfig,
    history: list[PricePoint],
    limitations: list[str],
    source_status: dict[str, Any],
) -> dict[str, Any]:
    if not config.enable_realtime_quote:
        return _quote_from_history(ticker, history, "Realtime disabled; using latest historical close")
    market = classify_market(ticker)
    priority = config.realtime_source_priority if market == "cn" else ["yfinance", "longbridge"]
    errors: list[str] = []
    for provider in priority:
        source_status["attempted"].append(f"quote:{provider}")
        try:
            if provider == "efinance":
                quote = _fetch_efinance_quote(ticker)
            elif provider in {"akshare_sina", "akshare_em", "tencent"}:
                quote = _fetch_akshare_realtime(ticker, provider)
            elif provider == "yfinance":
                quote = _fetch_yfinance_quote(ticker)
            elif provider == "longbridge":
                quote = {}
                errors.append("Longbridge optional fallback requires SDK credentials and is not queried without a configured server token cache")
            else:
                quote = {}
            if quote and quote.get("price") is not None:
                source_status["successful"].append(f"quote:{provider}")
                return quote
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    if errors:
        limitations.append("Realtime quote fallback used after source failures: " + "; ".join(errors[:4]))
    return _quote_from_history(ticker, history, "Latest historical close fallback")


def _fetch_yfinance_history(ticker: str) -> list[PricePoint]:
    import yfinance as yf

    frame = yf.Ticker(yfinance_symbol(ticker)).history(period="1y", interval="1d", auto_adjust=False)
    points: list[PricePoint] = []
    for idx, row in frame.reset_index().iterrows():
        points.append(
            PricePoint(
                date=str(row.get("Date") or row.get("Datetime") or idx)[:10],
                open=_float(row.get("Open")),
                high=_float(row.get("High")),
                low=_float(row.get("Low")),
                close=_float(row.get("Close")),
                volume=_float(row.get("Volume")),
            )
        )
    return [point for point in points if point.close is not None]


def _fetch_yfinance_quote(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    symbol = yfinance_symbol(ticker)
    item = yf.Ticker(symbol)
    fast = getattr(item, "fast_info", {}) or {}
    info = {}
    try:
        info = item.get_info() or {}
    except Exception:
        info = {}
    price = _float(_dict_get(fast, "last_price")) or _float(info.get("currentPrice")) or _float(info.get("regularMarketPrice"))
    previous = _float(_dict_get(fast, "previous_close")) or _float(info.get("previousClose"))
    change = price - previous if price is not None and previous else None
    change_pct = change / previous * 100 if change is not None and previous else None
    return {
        "ticker": display_symbol(ticker),
        "name": info.get("shortName") or info.get("longName") or display_symbol(ticker),
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "volume": _float(_dict_get(fast, "last_volume")) or _float(info.get("volume")),
        "market_cap": _float(info.get("marketCap")),
        "trailing_pe": _float(info.get("trailingPE")),
        "day_high": _float(_dict_get(fast, "day_high")) or _float(info.get("dayHigh")),
        "day_low": _float(_dict_get(fast, "day_low")) or _float(info.get("dayLow")),
        "exchange": info.get("exchange") or info.get("fullExchangeName"),
        "currency": info.get("currency"),
        "quote_source": "YFinance",
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_akshare_history(ticker: str) -> list[PricePoint]:
    import akshare as ak

    code = normalize_code(ticker)
    frame = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    return _frame_to_points(frame, {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"})


def _fetch_tushare_history(ticker: str, token: str) -> list[PricePoint]:
    if not token:
        return []
    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api()
    frame = pro.daily(ts_code=tushare_code(ticker))
    if frame is None or frame.empty:
        return []
    frame = frame.sort_values("trade_date")
    return _frame_to_points(frame, {"date": "trade_date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol"})


def _fetch_baostock_history(ticker: str) -> list[PricePoint]:
    import baostock as bs

    bs.login()
    rs = bs.query_history_k_data_plus(
        baostock_code(ticker),
        "date,open,high,low,close,volume",
        frequency="d",
        adjustflag="2",
    )
    points: list[PricePoint] = []
    while rs.next():
        row = rs.get_row_data()
        points.append(
            PricePoint(
                date=row[0],
                open=_float(row[1]),
                high=_float(row[2]),
                low=_float(row[3]),
                close=_float(row[4]),
                volume=_float(row[5]),
            )
        )
    bs.logout()
    return [point for point in points if point.close is not None]


def _fetch_efinance_history(ticker: str) -> list[PricePoint]:
    import efinance as ef

    frame = ef.stock.get_quote_history(normalize_code(ticker))
    return _frame_to_points(frame, {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"})


def _fetch_efinance_quote(ticker: str) -> dict[str, Any]:
    import efinance as ef

    frame = ef.stock.get_realtime_quotes()
    code = normalize_code(ticker)
    row = frame[frame["股票代码"].astype(str) == code].head(1)
    if row.empty:
        return {}
    item = row.iloc[0].to_dict()
    return {
        "ticker": code,
        "name": item.get("股票名称") or code,
        "price": _float(item.get("最新价")),
        "change": _float(item.get("涨跌额")),
        "change_percent": _float(item.get("涨跌幅")),
        "volume": _float(item.get("成交量")),
        "market_cap": _float(item.get("总市值")),
        "trailing_pe": _float(item.get("市盈率-动态")),
        "day_high": _float(item.get("最高")),
        "day_low": _float(item.get("最低")),
        "exchange": "CN",
        "currency": "CNY",
        "quote_source": "Efinance",
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_akshare_realtime(ticker: str, provider: str) -> dict[str, Any]:
    import akshare as ak

    code = normalize_code(ticker)
    if provider == "tencent":
        fetcher = getattr(ak, "stock_zh_a_spot_tx", None)
        if fetcher is None:
            return {}
        frame = fetcher()
        code_col = "代码"
    elif provider == "akshare_sina":
        frame = ak.stock_zh_a_spot()
        code_col = "代码"
    else:
        frame = ak.stock_zh_a_spot_em()
        code_col = "代码"
    row = frame[frame[code_col].astype(str) == code].head(1)
    if row.empty:
        return {}
    item = row.iloc[0].to_dict()
    return {
        "ticker": code,
        "name": item.get("名称") or code,
        "price": _float(item.get("最新价") or item.get("最新")),
        "change": _float(item.get("涨跌额")),
        "change_percent": _float(item.get("涨跌幅")),
        "volume": _float(item.get("成交量")),
        "market_cap": _float(item.get("总市值")),
        "trailing_pe": _float(item.get("市盈率-动态") or item.get("市盈率")),
        "day_high": _float(item.get("最高")),
        "day_low": _float(item.get("最低")),
        "exchange": "CN",
        "currency": "CNY",
        "quote_source": provider,
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def _quote_from_history(ticker: str, history: list[PricePoint], source: str) -> dict[str, Any]:
    latest = next((point for point in reversed(history) if point.close is not None), None)
    previous = None
    if len(history) >= 2:
        previous = next((point for point in reversed(history[:-1]) if point.close is not None), None)
    price = latest.close if latest else None
    previous_close = previous.close if previous else None
    change = price - previous_close if price is not None and previous_close else None
    change_pct = change / previous_close * 100 if change is not None and previous_close else None
    return {
        "ticker": display_symbol(ticker),
        "name": display_symbol(ticker),
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "volume": latest.volume if latest else None,
        "market_cap": None,
        "trailing_pe": None,
        "day_high": latest.high if latest else None,
        "day_low": latest.low if latest else None,
        "exchange": classify_market(ticker).upper(),
        "currency": "CNY" if classify_market(ticker) == "cn" else "HKD" if classify_market(ticker) == "hk" else "USD",
        "quote_source": source,
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def fetch_market_news(
    ticker: str,
    name: str,
    limit: int,
    config: DSAConfig,
    limitations: list[str],
    source_status: dict[str, Any],
) -> list[NewsItem]:
    if limit <= 0:
        return []
    query = f"{ticker} {name} stock latest earnings guidance risk catalyst"
    collected: list[NewsItem] = []
    errors: list[str] = []
    for provider in config.news_provider_priority:
        if len(collected) >= limit:
            break
        source_status["attempted"].append(f"news:{provider}")
        try:
            if provider == "brave":
                rows = _fetch_brave_news(query, config.brave_api_key, limit)
            elif provider == "tavily":
                rows = _fetch_tavily_news(query, config.tavily_api_keys, limit)
            elif provider == "serpapi":
                rows = _fetch_serpapi_news(query, config.serpapi_api_keys, limit)
            elif provider == "searxng":
                rows = _fetch_searxng_news(query, config.searxng_base_urls, limit)
            else:
                rows = []
            if rows:
                source_status["successful"].append(f"news:{provider}")
                collected.extend(rows)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    news = dedupe_news(collected, limit)
    if not news:
        if errors:
            limitations.append("News search unavailable from configured DSA search providers: " + "; ".join(errors[:4]))
        else:
            limitations.append("No DSA news search provider is configured. Set BRAVE_API_KEYS, TAVILY_API_KEYS, SERPAPI_API_KEYS, or SEARXNG_BASE_URLS.")
    return news


def _fetch_brave_news(query: str, api_key: str, limit: int) -> list[NewsItem]:
    if not api_key:
        return []
    data = fetch_json(
        BRAVE_NEWS_URL.format(query=urllib.parse.quote(query), limit=min(limit, 10)),
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
    )
    items = []
    for row in data.get("results", [])[:limit]:
        title = str(row.get("title") or "")
        desc = str(row.get("description") or "")
        sentiment = news_sentiment_score(f"{title} {desc}")
        items.append(NewsItem(title=title, url=str(row.get("url") or ""), source="Brave Search", summary=desc, impact=impact_from_sentiment(sentiment), sentiment=sentiment))
    return [item for item in items if item.title]


def _fetch_tavily_news(query: str, keys: str, limit: int) -> list[NewsItem]:
    key = next((part.strip() for part in keys.split(",") if part.strip()), "")
    if not key:
        return []
    body = json.dumps({"api_key": key, "query": query, "topic": "news", "max_results": min(limit, 10), "search_depth": "advanced"}).encode("utf-8")
    data = fetch_json(TAVILY_SEARCH_URL, headers={"Content-Type": "application/json"}, body=body, method="POST")
    items = []
    for row in data.get("results", [])[:limit]:
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        sentiment = news_sentiment_score(f"{title} {content}")
        items.append(NewsItem(title=title, url=str(row.get("url") or ""), source="Tavily", summary=content, impact=impact_from_sentiment(sentiment), sentiment=sentiment))
    return [item for item in items if item.title]


def _fetch_serpapi_news(query: str, keys: str, limit: int) -> list[NewsItem]:
    key = next((part.strip() for part in keys.split(",") if part.strip()), "")
    if not key:
        return []
    data = fetch_json(SERPAPI_NEWS_URL.format(query=urllib.parse.quote(query), api_key=urllib.parse.quote(key)))
    items = []
    for row in data.get("news_results", [])[:limit]:
        title = str(row.get("title") or "")
        snippet = str(row.get("snippet") or "")
        sentiment = news_sentiment_score(f"{title} {snippet}")
        items.append(NewsItem(title=title, url=str(row.get("link") or ""), source=str(row.get("source") or "SerpAPI"), published=str(row.get("date") or ""), summary=snippet, impact=impact_from_sentiment(sentiment), sentiment=sentiment))
    return [item for item in items if item.title]


def _fetch_searxng_news(query: str, base_urls: str, limit: int) -> list[NewsItem]:
    bases = [url.strip().rstrip("/") for url in base_urls.split(",") if url.strip()]
    if not bases:
        return []
    url = f"{bases[0]}/search?q={urllib.parse.quote(query)}&format=json&categories=news"
    data = fetch_json(url)
    items = []
    for row in data.get("results", [])[:limit]:
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        sentiment = news_sentiment_score(f"{title} {content}")
        items.append(NewsItem(title=title, url=str(row.get("url") or ""), source="SearXNG", summary=content, impact=impact_from_sentiment(sentiment), sentiment=sentiment))
    return [item for item in items if item.title]


def dedupe_news(items: list[NewsItem], limit: int) -> list[NewsItem]:
    seen: set[str] = set()
    output: list[NewsItem] = []
    for item in items:
        key = (item.title or item.url).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    return output


def synthesize_dsa_report(
    ticker: str,
    quote: dict[str, Any],
    history: list[PricePoint],
    news: list[NewsItem],
    strategy: str,
    limitations: list[str],
    source_status: dict[str, Any],
) -> DSAStockReport:
    technical = analyze_technical(history, quote)
    intelligence = analyze_intelligence(news)
    risk_alerts = list(intelligence["risk_alerts"]) + list(technical["risk_alerts"])
    catalysts = list(intelligence["positive_catalysts"]) + list(technical["positive_catalysts"])
    fundamentals = analyze_fundamental_proxy(quote, history)
    score = score_decision(technical, intelligence, fundamentals, risk_alerts, strategy)
    decision = decision_from_score(score, risk_alerts)
    operation = operation_advice(decision, technical)
    trend = trend_label(technical)
    confidence = confidence_level(score, limitations, len(news), source_status)
    checklist = build_checklist(decision, technical, risk_alerts)
    summary = build_summary(ticker, decision, score, trend, operation, risk_alerts, catalysts)
    phase_decision = build_phase_decision(decision, technical, risk_alerts, limitations)
    return DSAStockReport(
        code=ticker,
        name=str(quote.get("name") or ticker),
        market=classify_market(ticker),
        sentiment_score=score,
        decision_type=decision,
        confidence_level=confidence,
        trend_prediction=trend,
        operation_advice=operation,
        analysis_summary=summary,
        key_points=technical["key_points"] + intelligence["key_points"] + fundamentals["key_points"],
        risk_warning=risk_alerts,
        positive_catalysts=catalysts,
        checklist=checklist,
        dashboard={"technical": technical, "intelligence": intelligence, "fundamental_proxy": fundamentals, "risk": {"risk_alerts": risk_alerts}, "phase_decision": phase_decision, "strategy": strategy},
        quote=quote,
        technical=technical,
        intelligence=intelligence,
        news=news,
        source_links={"Primary Source": source_url(ticker)},
        source_status=source_status,
        data_limitations=limitations,
    )


def analyze_technical(history: list[PricePoint], quote: dict[str, Any]) -> dict[str, Any]:
    closes = [point.close for point in history if point.close is not None]
    volumes = [point.volume for point in history if point.volume is not None]
    close = _float(quote.get("price")) or (closes[-1] if closes else None)
    if close and closes and close != closes[-1]:
        closes = closes[:-1] + [close]
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)
    ma50 = moving_average(closes, 50)
    ma200 = moving_average(closes, 200)
    rsi = rsi_14(closes)
    ret_1m = pct_change(closes, 21)
    ret_3m = pct_change(closes, 63)
    ret_1y = pct_change(closes, 252)
    volume_ratio = None
    if len(volumes) >= 21 and volumes[-21:-1]:
        avg_volume = sum(volumes[-21:-1]) / len(volumes[-21:-1])
        volume_ratio = volumes[-1] / avg_volume if avg_volume else None
    support = min(closes[-20:]) if len(closes) >= 20 else None
    resistance = max(closes[-20:]) if len(closes) >= 20 else None
    risk_alerts: list[str] = []
    catalysts: list[str] = []
    key_points: list[str] = []
    if close and ma5 and ma10 and ma20 and close > ma5 > ma10 > ma20:
        catalysts.append("Bull-trend structure: price is above MA5 > MA10 > MA20.")
    if close and ma50 and close > ma50:
        catalysts.append("Price is above the 50-day moving average.")
    if close and ma200 and close > ma200:
        catalysts.append("Long-term trend is above the 200-day moving average.")
    if close and ma20 and close < ma20:
        risk_alerts.append("Price is below the 20-day moving average.")
    if close and ma200 and close < ma200:
        risk_alerts.append("Price is below the 200-day moving average.")
    if rsi is not None and rsi > 72:
        risk_alerts.append("RSI is elevated; short-term pullback risk is higher.")
    if rsi is not None and rsi < 35:
        risk_alerts.append("RSI is weak; momentum has not confirmed recovery.")
    if ret_1m is not None:
        key_points.append(f"1-month return is {ret_1m:.1f}%.")
    if volume_ratio is not None:
        key_points.append(f"Latest volume is {volume_ratio:.1f}x the recent average.")
    signal = "hold"
    if close and ma5 and ma10 and ma20 and close > ma5 > ma10 > ma20:
        signal = "buy"
    elif close and ma20 and ma50 and close > ma20 > ma50:
        signal = "buy"
    if close and ma20 and ma50 and close < ma20 < ma50:
        signal = "sell"
    return {
        "signal": signal,
        "confidence": 0.75 if len(closes) >= 200 else 0.55 if len(closes) >= 50 else 0.35,
        "close": close,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "rsi14": rsi,
        "return_1m_pct": ret_1m,
        "return_3m_pct": ret_3m,
        "return_1y_pct": ret_1y,
        "volume_ratio": volume_ratio,
        "support": support,
        "resistance": resistance,
        "risk_alerts": risk_alerts,
        "positive_catalysts": catalysts,
        "key_points": key_points,
    }


def analyze_intelligence(news: list[NewsItem]) -> dict[str, Any]:
    if not news:
        return {"signal": "hold", "confidence": 0.25, "sentiment_label": "unavailable", "risk_alerts": ["No configured DSA search-provider headlines were collected."], "positive_catalysts": [], "key_news": [], "key_points": ["News coverage unavailable or empty."]}
    avg = sum(item.sentiment for item in news) / len(news)
    signal = "buy" if avg > 0.18 else "sell" if avg < -0.18 else "hold"
    risks = []
    catalysts = []
    for item in news:
        text = f"{item.title} {item.summary}".lower()
        if item.sentiment < -0.12 or any(term in text for term in RISK_TERMS):
            risks.append(item.title)
        if item.sentiment > 0.12 or any(term in text for term in CATALYST_TERMS):
            catalysts.append(item.title)
    return {
        "signal": signal,
        "confidence": min(0.85, 0.35 + len(news) * 0.06),
        "sentiment_label": "positive" if avg > 0.15 else "negative" if avg < -0.15 else "neutral",
        "risk_alerts": risks[:5],
        "positive_catalysts": catalysts[:5],
        "key_news": [asdict(item) for item in news[:6]],
        "key_points": [f"Average headline sentiment is {avg:.2f} across {len(news)} collected items."],
    }


def analyze_fundamental_proxy(quote: dict[str, Any], history: list[PricePoint]) -> dict[str, Any]:
    pe = _float(quote.get("trailing_pe"))
    market_cap = _float(quote.get("market_cap"))
    closes = [point.close for point in history if point.close is not None]
    drawdown = None
    if closes:
        high = max(closes)
        drawdown = (closes[-1] / high - 1) * 100 if high else None
    key_points = []
    signal = "hold"
    if pe and 0 < pe < 35:
        key_points.append(f"Trailing PE is {pe:.1f}.")
    if market_cap:
        key_points.append(f"Market capitalization field is available from the configured source.")
    if drawdown is not None:
        key_points.append(f"One-year drawdown from high is {drawdown:.1f}%.")
    if pe and 0 < pe < 30 and drawdown is not None and drawdown > -25:
        signal = "buy"
    elif drawdown is not None and drawdown < -45:
        signal = "sell"
    return {"signal": signal, "trailing_pe": pe, "market_cap": market_cap, "drawdown_1y_pct": drawdown, "key_points": key_points}


def score_decision(technical: dict[str, Any], intelligence: dict[str, Any], fundamentals: dict[str, Any], risk_alerts: list[str], strategy: str) -> int:
    score = 50.0
    signal_delta = {"buy": 18.0, "hold": 0.0, "sell": -18.0}
    score += signal_delta.get(technical.get("signal"), 0.0) * 0.5
    score += signal_delta.get(intelligence.get("signal"), 0.0) * 0.25
    score += signal_delta.get(fundamentals.get("signal"), 0.0) * 0.15
    ret_1m = technical.get("return_1m_pct")
    ret_3m = technical.get("return_3m_pct")
    rsi = technical.get("rsi14")
    volume_ratio = technical.get("volume_ratio")
    if ret_1m is not None:
        score += max(-8.0, min(8.0, float(ret_1m) / 2.0))
    if ret_3m is not None:
        score += max(-7.0, min(7.0, float(ret_3m) / 5.0))
    if rsi is not None:
        if 45 <= float(rsi) <= 65:
            score += 4.0
        elif float(rsi) > 75 or float(rsi) < 30:
            score -= 6.0
    if volume_ratio is not None and volume_ratio > 1.4 and technical.get("signal") == "buy":
        score += 5.0
    score -= min(24.0, len(risk_alerts) * 5.0)
    if strategy == "Bull trend":
        score += 6.0 if technical.get("signal") == "buy" else -4.0
    elif strategy == "Event driven":
        score += min(8.0, len(intelligence.get("positive_catalysts", [])) * 2.0)
        score -= min(8.0, len(intelligence.get("risk_alerts", [])) * 2.0)
    elif strategy == "Risk first":
        score -= min(15.0, len(risk_alerts) * 3.0)
    elif strategy == "Growth quality":
        score += 5.0 if fundamentals.get("signal") == "buy" else 0.0
    return int(max(0, min(100, round(score))))


def decision_from_score(score: int, risk_alerts: list[str]) -> str:
    if score >= 68 and len(risk_alerts) <= 2:
        return "buy"
    if score <= 38:
        return "sell"
    return "hold"


def operation_advice(decision: str, technical: dict[str, Any]) -> str:
    support = technical.get("support")
    resistance = technical.get("resistance")
    if decision == "buy":
        if resistance:
            return f"Buy only after price holds trend support or breaks above {resistance:.2f} with confirmation."
        return "Buy only after trend, volume, and fresh-source confirmation."
    if decision == "sell":
        if support:
            return f"Reduce or avoid while price is weak; reassess if it reclaims support near {support:.2f}."
        return "Avoid new buying until price stabilizes."
    if support and resistance:
        return f"Hold/watch between support {support:.2f} and resistance {resistance:.2f}."
    return "Hold/watch until a clearer setup appears."


def trend_label(technical: dict[str, Any]) -> str:
    signal = technical.get("signal")
    ret_1m = technical.get("return_1m_pct")
    if signal == "buy":
        return "Bullish"
    if signal == "sell":
        return "Bearish"
    if ret_1m is not None and abs(float(ret_1m)) < 3:
        return "Range-bound"
    return "Mixed"


def confidence_level(score: int, limitations: list[str], news_count: int, source_status: dict[str, Any]) -> str:
    successes = len(source_status.get("successful", []))
    if limitations or successes < 2 or news_count == 0:
        return "Low"
    if score >= 70 or score <= 35:
        return "High"
    return "Medium"


def build_checklist(decision: str, technical: dict[str, Any], risk_alerts: list[str]) -> list[str]:
    checks = []
    if technical.get("signal") == "buy":
        checks.append("Pass: configured technical trend model is constructive.")
    elif technical.get("signal") == "sell":
        checks.append("Fail: configured technical trend model is weak.")
    else:
        checks.append("Watch: trend signal is mixed.")
    if risk_alerts:
        checks.append(f"Warning: resolve {len(risk_alerts)} risk alert(s).")
    else:
        checks.append("Pass: no major automated risk alert detected.")
    if decision == "buy":
        checks.append("Action: wait for support hold or breakout confirmation before entry.")
    elif decision == "sell":
        checks.append("Action: avoid or reduce exposure until recovery is confirmed.")
    else:
        checks.append("Action: keep on watchlist; do not force a trade.")
    return checks


def build_summary(ticker: str, decision: str, score: int, trend: str, operation: str, risks: list[str], catalysts: list[str]) -> str:
    decision_text = {"buy": "buy-watchlist", "hold": "watch", "sell": "avoid/sell"}[decision]
    summary = f"{ticker} is a {decision_text} setup with score {score}/100 and {trend.lower()} trend. {operation}"
    if risks:
        summary += f" Main risk: {risks[0]}"
    elif catalysts:
        summary += f" Main catalyst: {catalysts[0]}"
    return summary


def build_phase_decision(decision: str, technical: dict[str, Any], risk_alerts: list[str], limitations: list[str]) -> dict[str, Any]:
    return {
        "phase_context": {"trend": trend_label(technical), "support": technical.get("support"), "resistance": technical.get("resistance")},
        "action_window": "Next market session / next confirmed quote update",
        "immediate_action": operation_advice(decision, technical),
        "watch_conditions": build_checklist(decision, technical, risk_alerts),
        "next_check_time": "After next market close or material headline from configured search providers",
        "confidence_reason": "Confidence reflects source coverage, history depth, headline coverage, and risk flags.",
        "data_limitations": limitations,
    }


def build_market_review(reports: list[DSAStockReport], config: DSAConfig | None = None) -> dict[str, Any]:
    if not reports:
        return {"summary": "No watchlist data available.", "risk_tone": "Unknown", "breadth": {}}
    buy = sum(1 for report in reports if report.decision_type == "buy")
    hold = sum(1 for report in reports if report.decision_type == "hold")
    sell = sum(1 for report in reports if report.decision_type == "sell")
    avg_score = sum(report.sentiment_score for report in reports) / len(reports)
    risk_count = sum(len(report.risk_warning) for report in reports)
    tone = "Constructive" if avg_score >= 60 and buy >= sell else "Defensive" if avg_score < 45 or sell > buy else "Selective"
    config_summary = {}
    if config:
        config_summary = {
            "realtime_source_priority": config.realtime_source_priority,
            "cn_history_priority": config.cn_history_priority,
            "us_hk_history_priority": config.us_hk_history_priority,
            "news_provider_priority": config.news_provider_priority,
        }
    return {
        "summary": f"Watchlist tone is {tone.lower()}: {buy} buy, {hold} hold/watch, {sell} sell/avoid; average score {avg_score:.1f}.",
        "risk_tone": tone,
        "breadth": {"buy": buy, "hold": hold, "sell": sell, "average_score": avg_score, "risk_alerts": risk_count},
        "source_configuration": config_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def report_to_dict(report: DSAStockReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["news"] = [asdict(item) for item in report.news]
    return payload


def reports_to_json(reports: list[DSAStockReport], market_review: dict[str, Any]) -> str:
    return json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "market_review": market_review, "reports": [report_to_dict(report) for report in reports]}, indent=2, default=str)


def render_markdown(reports: list[DSAStockReport], market_review: dict[str, Any]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# Daily Stock Analysis Decision Dashboard", "", f"Generated: {generated}", "", "> Automated research support only. Not financial advice.", "", "## Market Review", "", market_review.get("summary", "No market review available."), ""]
    for report in sorted(reports, key=lambda item: item.sentiment_score, reverse=True):
        lines.extend(["", f"## {report.code} - {report.name}", "", f"- Decision: {report.decision_type}", f"- Score: {report.sentiment_score}/100", f"- Trend: {report.trend_prediction}", f"- Advice: {report.operation_advice}", f"- Summary: {report.analysis_summary}", "", "### Checklist"])
        lines.extend(f"- {item}" for item in report.checklist)
    return "\n".join(lines)


def fetch_yahoo_chart_history(symbol: str, chart_range: str, interval: str) -> dict[str, Any]:
    url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol), range=urllib.parse.quote(chart_range), interval=urllib.parse.quote(interval))
    data = fetch_json(url)
    result = (data.get("chart", {}).get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators", {}).get("quote") or [{}])[0]) or {}
    rows = []
    for index, ts in enumerate(timestamps):
        rows.append({"datetime": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), "open": _list_at(quote.get("open"), index), "high": _list_at(quote.get("high"), index), "low": _list_at(quote.get("low"), index), "close": _list_at(quote.get("close"), index), "volume": _list_at(quote.get("volume"), index)})
    return {"meta": result.get("meta", {}), "rows": rows}


def fetch_sgd_myr_history(chart_range: str, interval: str) -> dict[str, Any]:
    return fetch_yahoo_chart_history("SGDMYR=X", chart_range, interval)


def _frame_to_points(frame: Any, columns: dict[str, str]) -> list[PricePoint]:
    if frame is None or getattr(frame, "empty", True):
        return []
    points: list[PricePoint] = []
    for _, row in frame.iterrows():
        close = _float(row.get(columns["close"]))
        if close is None:
            continue
        points.append(
            PricePoint(
                date=str(row.get(columns["date"]) or ""),
                open=_float(row.get(columns["open"])),
                high=_float(row.get(columns["high"])),
                low=_float(row.get(columns["low"])),
                close=close,
                volume=_float(row.get(columns["volume"])),
            )
        )
    return points


def _dict_get(value: Any, key: str) -> Any:
    try:
        return value[key]
    except Exception:
        return None


POSITIVE_TERMS = {"beat", "beats", "growth", "upgrade", "raises", "record", "profit", "partnership", "approval", "surge", "strong", "bullish", "订单", "增长", "上调", "盈利", "突破"}
NEGATIVE_TERMS = {"miss", "cuts", "downgrade", "lawsuit", "probe", "investigation", "recall", "loss", "weak", "warning", "bearish", "falls", "下调", "亏损", "调查", "风险", "下跌"}
RISK_TERMS = NEGATIVE_TERMS | {"selloff", "guidance cut", "regulatory", "debt", "layoff"}
CATALYST_TERMS = POSITIVE_TERMS | {"contract", "launch", "approval", "demand", "earnings", "policy", "政策"}


def news_sentiment_score(text: str) -> float:
    lowered = text.lower()
    positive = sum(1 for term in POSITIVE_TERMS if term in lowered)
    negative = sum(1 for term in NEGATIVE_TERMS if term in lowered)
    if positive == negative:
        return 0.0
    return max(-1.0, min(1.0, (positive - negative) / max(positive + negative, 1)))


def impact_from_sentiment(sentiment: float) -> str:
    if sentiment > 0.12:
        return "positive"
    if sentiment < -0.12:
        return "negative"
    return "neutral"


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] == 0:
        return None
    return (values[-1] / values[-periods - 1] - 1.0) * 100.0


def rsi_14(values: list[float]) -> float | None:
    if len(values) < 15:
        return None
    gains = []
    losses = []
    for previous, current in zip(values[-15:-1], values[-14:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _list_at(values: list[Any] | None, index: int) -> Any:
    if not values or index >= len(values):
        return None
    return values[index]
