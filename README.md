# Daily Stock Analysis Streamlit Dashboard

This Streamlit app follows the source configuration style from `ZhuLinsen/daily_stock_analysis`: multi-source market data, search-provider news, source health checks, and DSA-style decision output.

It is automated research support only. It is not financial advice.

## Stock Dashboard Sources

The stock dashboard no longer uses the old Yahoo quote endpoint, Yahoo/Alpha Vantage news controls, SEC data path, ticker-detail page, ranking/download workflow, or Moomoo link-only source shortcuts.

Current source configuration:

- A-share historical data: `akshare,tushare,baostock,efinance`
- A-share real-time priority: `tencent,akshare_sina,efinance,akshare_em`
- US/HK data: `yfinance,longbridge`
- News/search intelligence: `brave,tavily,serpapi,searxng`

`YFinance` is used for US/HK stock data because the upstream project recommends it for those markets. Longbridge is treated as an optional US/HK fallback when credentials are configured.

## Environment Variables

Set these in Streamlit Community Cloud secrets or your local shell:

```toml
STOCK_LIST = "600519,300750,002594,AAPL,NVDA,MSFT,hk00700"

REALTIME_SOURCE_PRIORITY = "tencent,akshare_sina,efinance,akshare_em"
CN_HISTORY_SOURCE_PRIORITY = "akshare,tushare,baostock,efinance"
US_HK_HISTORY_SOURCE_PRIORITY = "yfinance,longbridge"
NEWS_PROVIDER_PRIORITY = "brave,tavily,serpapi,searxng"

TUSHARE_TOKEN = ""
BRAVE_API_KEYS = ""
TAVILY_API_KEYS = ""
SERPAPI_API_KEYS = ""
SEARXNG_BASE_URLS = ""

ENABLE_REALTIME_QUOTE = true
ENABLE_REALTIME_TECHNICAL_INDICATORS = true
ENABLE_FUNDAMENTAL_PIPELINE = true
ENABLE_CHIP_DISTRIBUTION = false
ENABLE_EASTMONEY_PATCH = false
NEWS_MAX_AGE_DAYS = 3
```

For best stock-news coverage, configure at least one of `BRAVE_API_KEYS`, `TAVILY_API_KEYS`, `SERPAPI_API_KEYS`, or `SEARXNG_BASE_URLS`.

## Run Locally

```powershell
pip install -r .\requirements.txt
streamlit run .\streamlit_app.py
```

Open the local URL printed by Streamlit, usually:

```text
http://localhost:8501
```

## Deploy On Streamlit Community Cloud

1. Push this repository to GitHub.
2. Go to `https://share.streamlit.io`.
3. Create an app from the GitHub repo and branch.
4. Set the main file path to:

```text
streamlit_app.py
```

5. Add the environment variables above in app secrets.
6. Deploy.

## SGD/MYR Tracker

The separate SGD/MYR page remains a reference exchange-rate tracker. Its live 30-minute block refreshes independently every minute. Compare the displayed market reference rate with your bank or transfer provider before making an actual transfer.
