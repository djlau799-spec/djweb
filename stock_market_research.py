from __future__ import annotations

import csv
import json
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
ALPHA_VANTAGE_NEWS_URL = "https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&limit={limit}&apikey={api_key}"
STOOQ_DAILY_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"


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
class DSAStockReport:
    code: str
    name: str = ""
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
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_limitations: list[str] = field(default_factory=list)


def fetch_json(url: str, timeout: int = 20) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-analysis-dashboard/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 stock-analysis-dashboard/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def yahoo_symbol(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def stooq_symbol(ticker: str) -> str:
    ticker = ticker.strip().lower()
    if ticker.endswith(".us") or ticker.startswith("^"):
        return ticker
    if "." not in ticker:
        return f"{ticker}.us"
    return ticker


def yahoo_news_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{urllib.parse.quote(yahoo_symbol(ticker))}/news/"


def yahoo_quote_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{urllib.parse.quote(yahoo_symbol(ticker))}/"


def moomoo_stock_url(ticker: str) -> str:
    normalized = ticker.strip().upper().replace(".", "-")
    return f"https://www.moomoo.com/stock/{urllib.parse.quote(normalized)}-US"


def latest_non_null(values: list[Any]) -> Any:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def fetch_yahoo_quotes(tickers: list[str]) -> list[dict[str, Any]]:
    if not tickers:
        return []
    encoded = ",".join(urllib.parse.quote(yahoo_symbol(ticker)) for ticker in tickers)
    try:
        data = fetch_json(YAHOO_QUOTE_URL.format(symbols=encoded))
    except Exception:
        return [fetch_yahoo_chart_quote(ticker) for ticker in tickers]
    rows: list[dict[str, Any]] = []
    for item in data.get("quoteResponse", {}).get("result", []):
        ticker = str(item.get("symbol", "")).replace("-", ".").upper()
        rows.append(
            {
                "ticker": ticker,
                "name": item.get("shortName") or item.get("longName") or ticker,
                "price": item.get("regularMarketPrice"),
                "change": item.get("regularMarketChange"),
                "change_percent": item.get("regularMarketChangePercent"),
                "volume": item.get("regularMarketVolume"),
                "market_cap": item.get("marketCap"),
                "trailing_pe": item.get("trailingPE"),
                "day_high": item.get("regularMarketDayHigh"),
                "day_low": item.get("regularMarketDayLow"),
                "market_state": item.get("marketState"),
                "exchange": item.get("fullExchangeName") or item.get("exchange"),
                "currency": item.get("currency"),
                "quote_source": item.get("quoteSourceName") or "Yahoo Finance",
                "updated": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def fetch_yahoo_chart_quote(ticker: str) -> dict[str, Any]:
    symbol = yahoo_symbol(ticker)
    try:
        payload = fetch_yahoo_chart_history(symbol, "1d", "1m")
        meta = payload.get("meta", {})
        rows = payload.get("rows", [])
        close_values = [row.get("close") for row in rows if row.get("close") is not None]
        price = meta.get("regularMarketPrice") or latest_non_null(close_values)
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = float(price) - float(previous) if price is not None and previous else None
        change_percent = (change / float(previous) * 100.0) if change is not None and previous else None
        return {
            "ticker": ticker.upper(),
            "name": meta.get("shortName") or meta.get("longName") or ticker.upper(),
            "price": price,
            "change": change,
            "change_percent": change_percent,
            "volume": meta.get("regularMarketVolume") or latest_non_null([row.get("volume") for row in rows]),
            "market_cap": None,
            "trailing_pe": None,
            "day_high": meta.get("regularMarketDayHigh") or latest_non_null([row.get("high") for row in rows]),
            "day_low": meta.get("regularMarketDayLow") or latest_non_null([row.get("low") for row in rows]),
            "market_state": meta.get("marketState"),
            "exchange": meta.get("exchangeName") or meta.get("exchangeTimezoneName"),
            "currency": meta.get("currency"),
            "quote_source": "Yahoo Finance chart",
            "updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "ticker": ticker.upper(),
            "name": ticker.upper(),
            "price": None,
            "change": None,
            "change_percent": None,
            "volume": None,
            "market_cap": None,
            "trailing_pe": None,
            "day_high": None,
            "day_low": None,
            "market_state": "unavailable",
            "exchange": None,
            "currency": None,
            "quote_source": f"Unavailable: {exc}",
            "updated": datetime.now(timezone.utc).isoformat(),
        }


def fetch_price_history(ticker: str) -> list[PricePoint]:
    url = STOOQ_DAILY_URL.format(symbol=urllib.parse.quote(stooq_symbol(ticker), safe="^.-"))
    text = fetch_text(url)
    rows = list(csv.DictReader(text.splitlines()))
    points: list[PricePoint] = []
    for row in rows:
        try:
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append(
            PricePoint(
                date=row.get("Date", ""),
                open=_float(row.get("Open")),
                high=_float(row.get("High")),
                low=_float(row.get("Low")),
                close=close,
                volume=_float(row.get("Volume")),
            )
        )
    return points


def fetch_yahoo_chart_history(symbol: str, chart_range: str, interval: str) -> dict[str, Any]:
    url = YAHOO_CHART_URL.format(
        symbol=urllib.parse.quote(symbol),
        range=urllib.parse.quote(chart_range),
        interval=urllib.parse.quote(interval),
    )
    data = fetch_json(url)
    result = (data.get("chart", {}).get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators", {}).get("quote") or [{}])[0]) or {}
    rows = []
    for index, ts in enumerate(timestamps):
        rows.append(
            {
                "datetime": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "open": _list_at(quote.get("open"), index),
                "high": _list_at(quote.get("high"), index),
                "low": _list_at(quote.get("low"), index),
                "close": _list_at(quote.get("close"), index),
                "volume": _list_at(quote.get("volume"), index),
            }
        )
    return {"meta": result.get("meta", {}), "rows": rows}


def fetch_sgd_myr_history(chart_range: str, interval: str) -> dict[str, Any]:
    return fetch_yahoo_chart_history("SGDMYR=X", chart_range, interval)


def fetch_yahoo_rss_news(ticker: str, limit: int) -> list[NewsItem]:
    if limit <= 0:
        return []
    try:
        xml_text = fetch_text(YAHOO_RSS_URL.format(ticker=urllib.parse.quote(yahoo_symbol(ticker))), timeout=15)
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    items: list[NewsItem] = []
    for node in root.findall(".//item")[:limit]:
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        summary = (node.findtext("description") or "").strip()
        sentiment = news_sentiment_score(f"{title} {summary}")
        items.append(
            NewsItem(
                title=title,
                url=(node.findtext("link") or "").strip(),
                source="Yahoo Finance",
                published=(node.findtext("pubDate") or "").strip(),
                summary=summary,
                impact=impact_from_sentiment(sentiment),
                sentiment=sentiment,
            )
        )
    return items


def fetch_alpha_vantage_news(ticker: str, api_key: str, limit: int) -> list[NewsItem]:
    if not api_key or limit <= 0:
        return []
    url = ALPHA_VANTAGE_NEWS_URL.format(
        ticker=urllib.parse.quote(ticker.upper()),
        limit=max(1, min(limit, 50)),
        api_key=urllib.parse.quote(api_key),
    )
    try:
        data = fetch_json(url, timeout=20)
    except Exception:
        return []
    items: list[NewsItem] = []
    for entry in data.get("feed", [])[:limit]:
        sentiment = _float(entry.get("overall_sentiment_score")) or news_sentiment_score(
            f"{entry.get('title', '')} {entry.get('summary', '')}"
        )
        items.append(
            NewsItem(
                title=str(entry.get("title") or "Untitled"),
                url=str(entry.get("url") or ""),
                source=str(entry.get("source") or "Alpha Vantage"),
                published=str(entry.get("time_published") or ""),
                summary=str(entry.get("summary") or ""),
                impact=impact_from_sentiment(sentiment),
                sentiment=sentiment,
            )
        )
    return items


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


def build_reports(
    tickers: list[str],
    strategy: str,
    news_source: str,
    news_limit: int,
    alpha_vantage_key: str = "",
) -> tuple[list[DSAStockReport], dict[str, Any]]:
    quotes = {row["ticker"].replace("-", ".").upper(): row for row in fetch_yahoo_quotes(tickers)}
    reports = []
    for ticker in tickers:
        code = ticker.upper()
        quote = quotes.get(code.replace("-", "."), {})
        history: list[PricePoint] = []
        limitations: list[str] = []
        try:
            history = fetch_price_history(code)
        except Exception as exc:
            limitations.append(f"Price history unavailable: {exc}")
        news = []
        if news_source in {"Yahoo Finance", "Yahoo + Alpha Vantage"}:
            news.extend(fetch_yahoo_rss_news(code, news_limit))
        if news_source in {"Alpha Vantage", "Yahoo + Alpha Vantage"} and alpha_vantage_key:
            news.extend(fetch_alpha_vantage_news(code, alpha_vantage_key, news_limit))
        news = dedupe_news(news, news_limit)
        report = synthesize_dsa_report(code, quote, history, news, strategy, limitations)
        reports.append(report)
        time.sleep(0.03)
    return reports, build_market_review(reports)


def synthesize_dsa_report(
    ticker: str,
    quote: dict[str, Any],
    history: list[PricePoint],
    news: list[NewsItem],
    strategy: str,
    limitations: list[str],
) -> DSAStockReport:
    technical = analyze_technical(history, quote)
    intelligence = analyze_intelligence(news)
    risk_alerts = list(intelligence["risk_alerts"])
    risk_alerts.extend(technical["risk_alerts"])
    catalysts = list(intelligence["positive_catalysts"])
    catalysts.extend(technical["positive_catalysts"])
    score = score_decision(technical, intelligence, risk_alerts, strategy)
    decision = decision_from_score(score, risk_alerts)
    operation = operation_advice(decision, technical)
    trend = trend_label(technical)
    confidence = confidence_level(score, limitations, len(news))

    checklist = build_checklist(decision, technical, risk_alerts)
    summary = build_summary(ticker, decision, score, trend, operation, risk_alerts, catalysts)
    phase_decision = build_phase_decision(decision, technical, risk_alerts, limitations)

    return DSAStockReport(
        code=ticker,
        name=str(quote.get("name") or ticker),
        sentiment_score=score,
        decision_type=decision,
        confidence_level=confidence,
        trend_prediction=trend,
        operation_advice=operation,
        analysis_summary=summary,
        key_points=technical["key_points"] + intelligence["key_points"],
        risk_warning=risk_alerts,
        positive_catalysts=catalysts,
        checklist=checklist,
        dashboard={
            "technical": technical,
            "intelligence": intelligence,
            "risk": {"risk_alerts": risk_alerts},
            "phase_decision": phase_decision,
            "strategy": strategy,
        },
        quote=quote,
        technical=technical,
        intelligence=intelligence,
        news=news,
        source_links={
            "Yahoo Quote": yahoo_quote_url(ticker),
            "Yahoo News": yahoo_news_url(ticker),
            "Moomoo": moomoo_stock_url(ticker),
        },
        data_limitations=limitations,
    )


def analyze_technical(history: list[PricePoint], quote: dict[str, Any]) -> dict[str, Any]:
    closes = [point.close for point in history if point.close is not None]
    volumes = [point.volume for point in history if point.volume is not None]
    close = _float(quote.get("price")) or (closes[-1] if closes else None)
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
    if close and ma20 and ma50 and close > ma20 > ma50:
        signal = "buy"
    if close and ma20 and ma50 and close < ma20 < ma50:
        signal = "sell"

    return {
        "signal": signal,
        "confidence": 0.7 if len(closes) >= 200 else 0.5 if len(closes) >= 50 else 0.35,
        "close": close,
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
        return {
            "signal": "hold",
            "confidence": 0.35,
            "sentiment_label": "neutral",
            "risk_alerts": ["No fresh finance headlines were collected."],
            "positive_catalysts": [],
            "key_news": [],
            "key_points": ["News coverage unavailable or empty."],
        }
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


def score_decision(
    technical: dict[str, Any],
    intelligence: dict[str, Any],
    risk_alerts: list[str],
    strategy: str,
) -> int:
    score = 50.0
    signal_delta = {"buy": 18.0, "hold": 0.0, "sell": -18.0}
    score += signal_delta.get(technical.get("signal"), 0.0) * 0.45
    score += signal_delta.get(intelligence.get("signal"), 0.0) * 0.3
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
        return "Buy only after trend and volume confirmation."
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


def confidence_level(score: int, limitations: list[str], news_count: int) -> str:
    if limitations or news_count == 0:
        return "Low"
    if score >= 70 or score <= 35:
        return "High"
    return "Medium"


def build_checklist(decision: str, technical: dict[str, Any], risk_alerts: list[str]) -> list[str]:
    checks = []
    if technical.get("signal") == "buy":
        checks.append("Pass: technical trend is constructive.")
    elif technical.get("signal") == "sell":
        checks.append("Fail: technical trend is weak.")
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


def build_summary(
    ticker: str,
    decision: str,
    score: int,
    trend: str,
    operation: str,
    risks: list[str],
    catalysts: list[str],
) -> str:
    decision_text = {"buy": "buy-watchlist", "hold": "watch", "sell": "avoid/sell"}[decision]
    summary = f"{ticker} is a {decision_text} setup with score {score}/100 and {trend.lower()} trend. {operation}"
    if risks:
        summary += f" Main risk: {risks[0]}"
    elif catalysts:
        summary += f" Main catalyst: {catalysts[0]}"
    return summary


def build_phase_decision(
    decision: str,
    technical: dict[str, Any],
    risk_alerts: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "phase_context": {
            "trend": trend_label(technical),
            "support": technical.get("support"),
            "resistance": technical.get("resistance"),
        },
        "action_window": "Next market session / next confirmed quote update",
        "immediate_action": operation_advice(decision, technical),
        "watch_conditions": build_checklist(decision, technical, risk_alerts),
        "next_check_time": "After next market close or major headline",
        "confidence_reason": "Confidence reflects technical history depth, headline coverage, and risk flags.",
        "data_limitations": limitations,
    }


def build_market_review(reports: list[DSAStockReport]) -> dict[str, Any]:
    if not reports:
        return {"summary": "No watchlist data available.", "risk_tone": "Unknown", "breadth": {}}
    buy = sum(1 for report in reports if report.decision_type == "buy")
    hold = sum(1 for report in reports if report.decision_type == "hold")
    sell = sum(1 for report in reports if report.decision_type == "sell")
    avg_score = sum(report.sentiment_score for report in reports) / len(reports)
    risk_count = sum(len(report.risk_warning) for report in reports)
    tone = "Constructive" if avg_score >= 60 and buy >= sell else "Defensive" if avg_score < 45 or sell > buy else "Selective"
    return {
        "summary": f"Watchlist tone is {tone.lower()}: {buy} buy, {hold} hold/watch, {sell} sell/avoid; average score {avg_score:.1f}.",
        "risk_tone": tone,
        "breadth": {"buy": buy, "hold": hold, "sell": sell, "average_score": avg_score, "risk_alerts": risk_count},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_markdown(reports: list[DSAStockReport], market_review: dict[str, Any]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Daily Stock Analysis Decision Dashboard",
        "",
        f"Generated: {generated}",
        "",
        "> Automated research support only. Not financial advice.",
        "",
        "## Market Review",
        "",
        market_review.get("summary", "No market review available."),
        "",
        "## Summary",
        "",
    ]
    for report in sorted(reports, key=lambda item: item.sentiment_score, reverse=True):
        lines.append(
            f"- {report.code}: {report.decision_type.upper()} | Score {report.sentiment_score} | {report.trend_prediction}"
        )
    for report in sorted(reports, key=lambda item: item.sentiment_score, reverse=True):
        lines.extend(
            [
                "",
                f"## {report.code} - {report.name}",
                "",
                f"- Decision: {report.decision_type}",
                f"- Score: {report.sentiment_score}/100",
                f"- Trend: {report.trend_prediction}",
                f"- Advice: {report.operation_advice}",
                f"- Summary: {report.analysis_summary}",
                "",
                "### Checklist",
            ]
        )
        lines.extend(f"- {item}" for item in report.checklist)
        if report.positive_catalysts:
            lines.append("")
            lines.append("### Catalysts")
            lines.extend(f"- {item}" for item in report.positive_catalysts[:5])
        if report.risk_warning:
            lines.append("")
            lines.append("### Risks")
            lines.extend(f"- {item}" for item in report.risk_warning[:5])
        if report.news:
            lines.append("")
            lines.append("### News")
            for item in report.news[:5]:
                lines.append(f"- [{item.title}]({item.url}) - {item.source}")
    return "\n".join(lines)


def reports_to_json(reports: list[DSAStockReport], market_review: dict[str, Any]) -> str:
    return json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "market_review": market_review,
            "reports": [report_to_dict(report) for report in reports],
        },
        indent=2,
        default=str,
    )


def report_to_dict(report: DSAStockReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["news"] = [asdict(item) for item in report.news]
    return payload


POSITIVE_TERMS = {
    "beat",
    "beats",
    "growth",
    "upgrade",
    "raises",
    "record",
    "profit",
    "partnership",
    "approval",
    "surge",
    "strong",
    "bullish",
}
NEGATIVE_TERMS = {
    "miss",
    "cuts",
    "downgrade",
    "lawsuit",
    "probe",
    "investigation",
    "recall",
    "loss",
    "weak",
    "warning",
    "bearish",
    "falls",
}
RISK_TERMS = NEGATIVE_TERMS | {"selloff", "guidance cut", "regulatory", "debt", "layoff"}
CATALYST_TERMS = POSITIVE_TERMS | {"contract", "launch", "approval", "demand", "earnings"}


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
