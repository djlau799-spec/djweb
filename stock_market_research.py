#!/usr/bin/env python3
"""
Build a stock-market research report from public data sources.

This script ranks tickers for further research. It is not financial advice and
does not know your risk tolerance, time horizon, tax position, or portfolio.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


STOOQ_DAILY_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ALPHA_VANTAGE_NEWS_URL = "https://www.alphavantage.co/query"
YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

POSITIVE_WORDS = {
    "beat",
    "beats",
    "boost",
    "bullish",
    "buy",
    "growth",
    "higher",
    "outperform",
    "profit",
    "raises",
    "record",
    "recovery",
    "strong",
    "upgrade",
    "upside",
}

NEGATIVE_WORDS = {
    "bearish",
    "cut",
    "decline",
    "downgrade",
    "falls",
    "fraud",
    "investigation",
    "lawsuit",
    "loss",
    "miss",
    "misses",
    "probe",
    "risk",
    "sell",
    "slump",
    "weak",
}


@dataclass
class PriceBar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class NewsItem:
    title: str
    url: str
    published: str = ""
    sentiment: float | None = None
    summary: str = ""


@dataclass
class StockReport:
    ticker: str
    company: str = ""
    price: dict[str, Any] = field(default_factory=dict)
    filings: dict[str, Any] = field(default_factory=dict)
    fundamentals: dict[str, Any] = field(default_factory=dict)
    news: list[NewsItem] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    rating: str = "Insufficient data"
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def http_get_text(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    return json.loads(http_get_text(url, headers=headers))


def safe_float(value: str) -> float | None:
    try:
        if value is None:
            return None
        value = str(value)
        if value == "" or value.upper() == "N/D":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def stooq_symbol(ticker: str) -> str:
    clean = ticker.strip().lower().replace(".", "-")
    if "." not in clean and not clean.startswith("^"):
        clean = f"{clean}.us"
    return clean


def fetch_price_history(ticker: str) -> list[PriceBar]:
    url = STOOQ_DAILY_URL.format(symbol=urllib.parse.quote(stooq_symbol(ticker), safe="^.-"))
    rows = list(csv.DictReader(http_get_text(url).splitlines()))
    bars: list[PriceBar] = []
    for row in rows:
        close = safe_float(row.get("Close", ""))
        open_ = safe_float(row.get("Open", ""))
        high = safe_float(row.get("High", ""))
        low = safe_float(row.get("Low", ""))
        if close is None or open_ is None or high is None or low is None:
            continue
        try:
            volume = int(float(row.get("Volume", "0") or 0))
            bars.append(
                PriceBar(
                    day=datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )
        except (KeyError, ValueError):
            continue
    return bars


def percent_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return (current / previous - 1.0) * 100.0


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def analyze_price(bars: list[PriceBar]) -> tuple[dict[str, Any], float, list[str]]:
    if len(bars) < 60:
        return {}, 0.0, ["Price history is too short for a reliable trend score."]

    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    latest = bars[-1]

    def prior_close(days: int) -> float | None:
        return closes[-days - 1] if len(closes) > days else None

    ret_1m = percent_change(latest.close, prior_close(21))
    ret_3m = percent_change(latest.close, prior_close(63))
    ret_6m = percent_change(latest.close, prior_close(126))
    ret_1y = percent_change(latest.close, prior_close(252))
    sma_50 = mean(closes[-50:])
    sma_200 = mean(closes[-200:]) if len(closes) >= 200 else None
    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    low_52w = min(closes[-252:]) if len(closes) >= 252 else min(closes)
    drawdown = percent_change(latest.close, high_52w)
    avg_vol_20 = mean([float(v) for v in volumes[-20:] if v > 0])
    avg_vol_60 = mean([float(v) for v in volumes[-60:] if v > 0])
    volume_ratio = avg_vol_20 / avg_vol_60 if avg_vol_20 and avg_vol_60 else None

    score = 0.0
    notes: list[str] = []

    if sma_50 and latest.close > sma_50:
        score += 1.3
        notes.append("Price is above the 50-day moving average.")
    else:
        notes.append("Price is below or near the 50-day moving average.")

    if sma_200 and latest.close > sma_200:
        score += 1.7
        notes.append("Price is above the 200-day moving average.")
    elif sma_200:
        notes.append("Price is below the 200-day moving average.")

    for label, ret, weight in (
        ("1-month", ret_1m, 0.8),
        ("3-month", ret_3m, 1.1),
        ("6-month", ret_6m, 1.0),
        ("1-year", ret_1y, 1.1),
    ):
        if ret is None:
            continue
        if ret > 0:
            score += weight
        if ret > 12 and label in {"3-month", "6-month"}:
            score += 0.4
        if ret < -10 and label in {"1-month", "3-month"}:
            score -= 0.5

    if drawdown is not None:
        if drawdown > -12:
            score += 0.8
        elif drawdown < -30:
            score -= 0.8
            notes.append("The stock is more than 30% below its recent high.")

    if volume_ratio is not None and volume_ratio > 1.25 and ret_1m and ret_1m > 0:
        score += 0.5
        notes.append("Recent volume is expanding alongside positive price movement.")

    score = max(0.0, min(7.0, score))
    data = {
        "as_of": latest.day.isoformat(),
        "close": latest.close,
        "return_1m_pct": ret_1m,
        "return_3m_pct": ret_3m,
        "return_6m_pct": ret_6m,
        "return_1y_pct": ret_1y,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "drawdown_from_52w_high_pct": drawdown,
        "volume_ratio_20d_vs_60d": volume_ratio,
    }
    return data, score, notes


def sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Host": "www.sec.gov",
    }


def sec_data_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Host": "data.sec.gov",
    }


def load_sec_ticker_map(user_agent: str) -> dict[str, dict[str, Any]]:
    data = fetch_json(SEC_TICKERS_URL, headers=sec_headers(user_agent))
    return {entry["ticker"].upper(): entry for entry in data.values()}


def fetch_sec_profile(ticker: str, ticker_map: dict[str, dict[str, Any]], user_agent: str) -> tuple[str, dict[str, Any], dict[str, Any], float, list[str]]:
    entry = ticker_map.get(ticker.upper())
    if not entry:
        return "", {}, {}, 0.0, ["No SEC ticker mapping found. This may be a non-US listing, ETF, or fund."]

    cik = str(entry["cik_str"]).zfill(10)
    company = entry.get("title", "")
    notes: list[str] = []
    score = 0.0
    filings: dict[str, Any] = {"cik": cik, "recent": []}
    fundamentals: dict[str, Any] = {}

    submissions = fetch_json(SEC_SUBMISSIONS_URL.format(cik=cik), headers=sec_data_headers(user_agent))
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])

    selected = []
    for form, filing_date, accession in zip(forms, filing_dates, accession_numbers):
        if form in {"10-K", "10-Q", "8-K", "20-F", "6-K"}:
            selected.append({"form": form, "filing_date": filing_date, "accession": accession})
        if len(selected) >= 8:
            break

    filings["recent"] = selected
    if selected:
        latest_form = selected[0]["form"]
        notes.append(f"Latest notable SEC filing is {latest_form} from {selected[0]['filing_date']}.")
        score += 0.4

    facts = fetch_json(SEC_COMPANY_FACTS_URL.format(cik=cik), headers=sec_data_headers(user_agent))
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    fundamentals = {
        "revenue": latest_usd_fact(
            us_gaap,
            [
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
            ],
        ),
        "net_income": latest_usd_fact(us_gaap, ["NetIncomeLoss"]),
        "assets": latest_usd_fact(us_gaap, ["Assets"]),
        "liabilities": latest_usd_fact(us_gaap, ["Liabilities"]),
    }

    revenue = fundamentals.get("revenue", {}).get("value")
    net_income = fundamentals.get("net_income", {}).get("value")
    assets = fundamentals.get("assets", {}).get("value")
    liabilities = fundamentals.get("liabilities", {}).get("value")

    if revenue:
        score += 0.4
    if net_income and net_income > 0:
        score += 0.6
        notes.append("Latest reported net income is positive.")
    elif net_income is not None:
        notes.append("Latest reported net income is negative.")

    if assets and liabilities is not None:
        liabilities_to_assets = liabilities / assets if assets else None
        fundamentals["liabilities_to_assets"] = liabilities_to_assets
        if liabilities_to_assets is not None and liabilities_to_assets < 0.75:
            score += 0.6
        elif liabilities_to_assets is not None and liabilities_to_assets > 0.9:
            notes.append("Liabilities are high relative to assets.")

    return company, filings, fundamentals, min(2.0, score), notes


def latest_usd_fact(us_gaap: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for tag in tags:
        unit_records = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        for row in unit_records:
            if "val" not in row or "end" not in row:
                continue
            form = row.get("form", "")
            if form not in {"10-K", "10-Q", "20-F", "40-F"}:
                continue
            records.append(
                {
                    "tag": tag,
                    "value": row.get("val"),
                    "end": row.get("end"),
                    "filed": row.get("filed"),
                    "form": form,
                    "fy": row.get("fy"),
                    "fp": row.get("fp"),
                }
            )
    records.sort(key=lambda r: (r.get("end") or "", r.get("filed") or ""), reverse=True)
    return records[0] if records else {}


def fetch_alpha_vantage_news(ticker: str, api_key: str, limit: int) -> list[NewsItem]:
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker.upper(),
        "sort": "LATEST",
        "limit": str(limit),
        "apikey": api_key,
    }
    url = f"{ALPHA_VANTAGE_NEWS_URL}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)
    items: list[NewsItem] = []
    for article in data.get("feed", [])[:limit]:
        sentiment = safe_float(str(article.get("overall_sentiment_score", "")))
        ticker_sentiment = article.get("ticker_sentiment", [])
        for row in ticker_sentiment:
            if row.get("ticker", "").upper() == ticker.upper():
                sentiment = safe_float(str(row.get("ticker_sentiment_score", ""))) or sentiment
                break
        items.append(
            NewsItem(
                title=article.get("title", "").strip(),
                url=article.get("url", "").strip(),
                published=article.get("time_published", ""),
                summary=article.get("summary", "").strip(),
                sentiment=sentiment,
            )
        )
    return items


def fetch_yahoo_rss_news(ticker: str, limit: int) -> list[NewsItem]:
    url = YAHOO_RSS_URL.format(ticker=urllib.parse.quote(ticker.upper()))
    xml_text = http_get_text(url, headers={"User-Agent": "market-research-script/1.0"})
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        summary = (item.findtext("description") or "").strip()
        items.append(
            NewsItem(
                title=title,
                url=link,
                published=published,
                summary=summary,
                sentiment=keyword_sentiment(f"{title} {summary}"),
            )
        )
    return items


def keyword_sentiment(text: str) -> float:
    words = {
        "".join(ch for ch in word.lower() if ch.isalnum())
        for word in text.replace("-", " ").split()
    }
    positives = len(words & POSITIVE_WORDS)
    negatives = len(words & NEGATIVE_WORDS)
    if positives == 0 and negatives == 0:
        return 0.0
    return max(-1.0, min(1.0, (positives - negatives) / max(positives + negatives, 1)))


def analyze_news(items: list[NewsItem]) -> tuple[float, list[str]]:
    if not items:
        return 0.0, ["No recent news items were collected."]

    scores = [item.sentiment for item in items if item.sentiment is not None]
    avg = statistics.fmean(scores) if scores else 0.0
    score = max(0.0, min(1.0, (avg + 1.0) / 2.0))
    notes = []
    if avg > 0.2:
        notes.append("Recent news sentiment is positive.")
    elif avg < -0.2:
        notes.append("Recent news sentiment is negative.")
    else:
        notes.append("Recent news sentiment is mixed or neutral.")
    return score, notes


def classify(total_score: float, warnings: list[str], notes: list[str]) -> str:
    messages = warnings + notes
    if any("too short" in message.lower() for message in messages):
        return "Insufficient data"
    if total_score >= 7.2:
        return "Buy-watchlist candidate"
    if total_score >= 5.2:
        return "Monitor / possible hold"
    return "Avoid or wait"


def analyze_ticker(
    ticker: str,
    sec_ticker_map: dict[str, dict[str, Any]],
    sec_user_agent: str,
    alpha_vantage_key: str | None,
    news_limit: int,
    news_source: str,
) -> StockReport:
    report = StockReport(ticker=ticker.upper())

    try:
        bars = fetch_price_history(ticker)
        report.price, price_score, price_notes = analyze_price(bars)
        report.scores["price_trend"] = price_score
        report.notes.extend(price_notes)
    except Exception as exc:
        report.warnings.append(f"Price fetch failed: {exc}")
        report.scores["price_trend"] = 0.0

    try:
        company, filings, fundamentals, sec_score, sec_notes = fetch_sec_profile(ticker, sec_ticker_map, sec_user_agent)
        report.company = company
        report.filings = filings
        report.fundamentals = fundamentals
        report.scores["sec_fundamentals"] = sec_score
        report.notes.extend(sec_notes)
    except Exception as exc:
        report.warnings.append(f"SEC fetch failed: {exc}")
        report.scores["sec_fundamentals"] = 0.0

    try:
        if news_source == "alpha-vantage":
            if not alpha_vantage_key:
                report.warnings.append("Alpha Vantage news requested but no API key was provided.")
                news_items: list[NewsItem] = []
            else:
                news_items = fetch_alpha_vantage_news(ticker, alpha_vantage_key, news_limit)
        elif news_source == "yahoo-rss":
            news_items = fetch_yahoo_rss_news(ticker, news_limit)
        else:
            news_items = []
        news_score, news_notes = analyze_news(news_items)
        report.news = news_items
        report.scores["news_sentiment"] = news_score
        report.notes.extend(news_notes)
    except Exception as exc:
        report.warnings.append(f"News fetch failed: {exc}")
        report.scores["news_sentiment"] = 0.0

    total_score = sum(report.scores.values())
    report.scores["total"] = round(total_score, 2)
    report.rating = classify(total_score, report.warnings, report.notes)
    return report


def analyze_market_context() -> list[str]:
    notes: list[str] = []
    for ticker, name in (("SPY", "S&P 500 proxy"), ("QQQ", "Nasdaq 100 proxy"), ("DIA", "Dow proxy")):
        try:
            bars = fetch_price_history(ticker)
            price, _, _ = analyze_price(bars)
            close = price.get("close")
            sma_50 = price.get("sma_50")
            sma_200 = price.get("sma_200")
            ret_1m = price.get("return_1m_pct")
            if not close:
                continue
            if sma_200 and close < sma_200:
                notes.append(f"{name} is below its 200-day moving average; broad-market risk is elevated.")
            elif sma_50 and close < sma_50:
                notes.append(f"{name} is below its 50-day moving average; watch for short-term weakness.")
            elif ret_1m is not None and ret_1m > 0:
                notes.append(f"{name} trend is constructive over the last month.")
        except Exception as exc:
            notes.append(f"Could not analyze {name}: {exc}")
    return notes or ["Market context could not be collected."]


def fmt_pct(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        if math.isnan(float(value)):
            return "n/a"
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def fmt_money(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    suffixes = [(1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M")]
    for divisor, suffix in suffixes:
        if abs(value) >= divisor:
            return f"${value / divisor:.2f}{suffix}"
    return f"${value:,.0f}"


def first_sentence(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."


def render_markdown(
    reports: list[StockReport],
    market_notes: list[str],
    news_source: str,
    output_json_name: str,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ranked = sorted(reports, key=lambda report: report.scores.get("total", 0.0), reverse=True)

    lines = [
        "# Stock Market Research Report",
        "",
        f"Generated: {generated}",
        "",
        "> This is an automated research report, not financial advice. Treat the recommendations as a shortlist for manual due diligence.",
        "",
        "## Sources Used",
        "",
        "- Stooq daily price CSV for market prices and trend indicators.",
        "- SEC EDGAR JSON APIs for company identity, filings, and reported fundamentals.",
        f"- News source: {news_source}.",
        f"- Raw structured output: `{output_json_name}`.",
        "",
        "## What To Look Out For",
        "",
    ]
    for note in market_notes:
        lines.append(f"- {note}")
    lines.extend(
        [
            "- Give extra attention to stocks with strong price trend but negative news or high leverage; that combination can reverse quickly.",
            "- Before buying, verify upcoming earnings dates, guidance changes, regulatory issues, valuation, and position sizing.",
            "",
            "## Ranked Watchlist",
            "",
            "| Rank | Ticker | Company | Rating | Score | Close | 1M | 3M | 1Y | Key note |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for index, report in enumerate(ranked, start=1):
        price = report.price
        key_note = first_sentence(report.notes[0] if report.notes else "")
        lines.append(
            "| {rank} | {ticker} | {company} | {rating} | {score:.2f} | {close} | {ret1m} | {ret3m} | {ret1y} | {note} |".format(
                rank=index,
                ticker=report.ticker,
                company=(report.company or "n/a").replace("|", " "),
                rating=report.rating,
                score=report.scores.get("total", 0.0),
                close=f"${price.get('close'):.2f}" if price.get("close") else "n/a",
                ret1m=fmt_pct(price.get("return_1m_pct")),
                ret3m=fmt_pct(price.get("return_3m_pct")),
                ret1y=fmt_pct(price.get("return_1y_pct")),
                note=key_note.replace("|", " "),
            )
        )

    lines.extend(["", "## Ticker Details", ""])
    for report in ranked:
        lines.extend(
            [
                f"### {report.ticker} - {report.rating}",
                "",
                f"- Total score: {report.scores.get('total', 0.0):.2f} / 10.00",
                f"- Price score: {report.scores.get('price_trend', 0.0):.2f} / 7.00",
                f"- SEC/fundamentals score: {report.scores.get('sec_fundamentals', 0.0):.2f} / 2.00",
                f"- News sentiment score: {report.scores.get('news_sentiment', 0.0):.2f} / 1.00",
            ]
        )

        fundamentals = report.fundamentals
        if fundamentals:
            lines.extend(
                [
                    f"- Latest revenue: {fmt_money(fundamentals.get('revenue', {}).get('value'))}",
                    f"- Latest net income: {fmt_money(fundamentals.get('net_income', {}).get('value'))}",
                    f"- Liabilities/assets: {fmt_pct((fundamentals.get('liabilities_to_assets') or 0) * 100) if fundamentals.get('liabilities_to_assets') is not None else 'n/a'}",
                ]
            )

        if report.notes:
            lines.append("- Notes:")
            for note in report.notes[:6]:
                lines.append(f"  - {note}")

        if report.warnings:
            lines.append("- Data warnings:")
            for warning in report.warnings:
                lines.append(f"  - {warning}")

        if report.news:
            lines.append("- Recent headlines:")
            for item in report.news[:5]:
                title = first_sentence(item.title, 140).replace("|", " ")
                if item.url:
                    lines.append(f"  - [{title}]({item.url})")
                else:
                    lines.append(f"  - {title}")
        lines.append("")

    return "\n".join(lines)


def to_jsonable(report: StockReport) -> dict[str, Any]:
    return {
        "ticker": report.ticker,
        "company": report.company,
        "rating": report.rating,
        "scores": report.scores,
        "price": report.price,
        "filings": report.filings,
        "fundamentals": report.fundamentals,
        "notes": report.notes,
        "warnings": report.warnings,
        "news": [item.__dict__ for item in report.news],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a stock research report from Stooq, SEC EDGAR, and optional news sources."
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],
        help="Ticker symbols to analyze. Default: major US large-cap stocks.",
    )
    parser.add_argument(
        "--tickers-file",
        type=Path,
        help="Optional file with one ticker per line. Overrides --tickers.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for markdown and JSON reports.",
    )
    parser.add_argument(
        "--sec-user-agent",
        default=os.getenv("SEC_USER_AGENT") or os.getenv("MARKET_RESEARCH_USER_AGENT"),
        help="SEC requests require a descriptive User-Agent, ideally 'Name email@example.com'.",
    )
    parser.add_argument(
        "--alpha-vantage-key",
        default=os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY"),
        help="Optional Alpha Vantage API key for market news sentiment.",
    )
    parser.add_argument(
        "--news-source",
        choices=["auto", "alpha-vantage", "yahoo-rss", "none"],
        default="auto",
        help="News source. 'auto' uses Alpha Vantage when a key is present, otherwise Yahoo RSS.",
    )
    parser.add_argument("--news-limit", type=int, default=8, help="Number of headlines per ticker.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between ticker requests.")
    return parser.parse_args(argv)


def read_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers_file:
        content = args.tickers_file.read_text(encoding="utf-8")
        raw = [line.strip() for line in content.splitlines()]
    else:
        raw = args.tickers
    tickers = []
    seen = set()
    for ticker in raw:
        ticker = ticker.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        tickers.append(ticker)
        seen.add(ticker)
    return tickers


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    tickers = read_tickers(args)
    if not tickers:
        print("No tickers provided.", file=sys.stderr)
        return 2

    sec_user_agent = args.sec_user_agent or "market-research-script/1.0 contact@example.com"
    if "contact@example.com" in sec_user_agent:
        print(
            "Warning: set --sec-user-agent or SEC_USER_AGENT to your name/email for SEC fair-access compliance.",
            file=sys.stderr,
        )

    news_source = args.news_source
    if news_source == "auto":
        news_source = "alpha-vantage" if args.alpha_vantage_key else "yahoo-rss"

    print("Loading SEC ticker map...")
    try:
        sec_ticker_map = load_sec_ticker_map(sec_user_agent)
    except Exception as exc:
        print(f"Warning: SEC ticker map failed: {exc}", file=sys.stderr)
        sec_ticker_map = {}

    print("Collecting market context...")
    market_notes = analyze_market_context()

    reports: list[StockReport] = []
    for ticker in tickers:
        print(f"Analyzing {ticker}...")
        report = analyze_ticker(
            ticker=ticker,
            sec_ticker_map=sec_ticker_map,
            sec_user_agent=sec_user_agent,
            alpha_vantage_key=args.alpha_vantage_key,
            news_limit=args.news_limit,
            news_source=news_source,
        )
        reports.append(report)
        time.sleep(args.sleep)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"stock_research_{stamp}.json"
    md_path = args.output_dir / f"stock_research_{stamp}.md"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": tickers,
        "news_source": news_source,
        "market_notes": market_notes,
        "reports": [to_jsonable(report) for report in reports],
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(reports, market_notes, news_source, json_path.name), encoding="utf-8")

    print(f"Wrote markdown report: {md_path}")
    print(f"Wrote JSON data:       {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
