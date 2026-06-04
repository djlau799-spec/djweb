# Stock Market Research Script

This project creates a live-style stock price and finance news dashboard from public data sources. It shows current quote fields, ranks notable stocks as research candidates, highlights market conditions to watch, and shows important headlines from trusted sources.

It is not financial advice. Use the output as a starting point for manual due diligence.

## Sources

- Yahoo Finance quote fields for current stock prices. Availability can be real-time or exchange-delayed depending on the symbol and exchange.
- Stooq daily CSV data for price history and trend indicators.
- SEC EDGAR JSON APIs for company identity, filing history, and basic reported fundamentals.
- News and sentiment from Yahoo Finance RSS and, if you provide an API key, Alpha Vantage.
- Moomoo source links for each ticker. Moomoo's official programmatic data path uses OpenD/API infrastructure, so this Streamlit Cloud app links to Moomoo pages rather than scraping authenticated Moomoo data.

## Quick Start

```powershell
python .\stock_market_research.py --tickers AAPL MSFT NVDA AMZN GOOGL META TSLA --sec-user-agent "Your Name your.email@example.com"
```

Reports are written to the `reports` folder.

## Streamlit Website

Install the website dependencies:

```powershell
pip install -r .\requirements.txt
```

Run the Streamlit dashboard:

```powershell
streamlit run .\streamlit_app.py
```

Streamlit will print a local browser URL, usually `http://localhost:8501`.

## Docker

Build the Docker image:

```powershell
docker build -t stock-research-app .
```

Run the app locally:

```powershell
docker run --rm -p 8501:8501 stock-research-app
```

Open:

```text
http://localhost:8501
```

Or run with Docker Compose:

```powershell
docker compose up --build -d
```

To stop it:

```powershell
docker compose down
```

For SEC fair-access compliance, replace the default `SEC_USER_AGENT` in `docker-compose.yml` with your name and email. If you have an Alpha Vantage key, put it in `ALPHAVANTAGE_API_KEY`.

## Put It Online With Docker

Docker only packages the app. To make it online, run the container on a server with a public IP address, such as a small VPS.

On the server:

```bash
git clone <your-repo-url>
cd <your-project-folder>
docker compose up --build -d
```

Then open:

```text
http://YOUR_SERVER_IP:8501
```

Make sure the server firewall allows inbound TCP traffic on port `8501`.

For a cleaner public URL, point a domain to the server and put Nginx or Caddy in front of Streamlit as a reverse proxy with HTTPS.

## Deploy On Streamlit Community Cloud

Streamlit Community Cloud deploys from GitHub. Docker files are not used for this deployment path.

1. Push this project to a GitHub repository.
2. Go to `https://share.streamlit.io`.
3. Sign in with GitHub.
4. Click `Create app`.
5. Choose the repository and branch.
6. Set the main file path to:

```text
streamlit_app.py
```

7. In app secrets, add:

```toml
SEC_USER_AGENT = "Your Name your.email@example.com"
ALPHAVANTAGE_API_KEY = ""
```

8. Deploy the app.

The required Community Cloud files are already present:

- `streamlit_app.py`
- `stock_market_research.py`
- `requirements.txt`
- `.streamlit/config.toml`

The app opens as a real-time stock price and finance news dashboard. Use the sidebar to choose groups such as AI, semiconductors, financials, healthcare, energy, consumer stocks, and market ETFs.

Free public quote feeds may be delayed. The app shows the quote feed status when the source provides delay metadata.

The sidebar also includes a `SGD/MYR rate tracker` page. It shows the Singapore dollar to Malaysian ringgit reference rate, 30-minute high/low, a separate conversion calculator, a live 30-minute line chart, and a live 30-minute rate table. The live FX block uses a Streamlit fragment that refreshes every 1 minute without rerunning the rest of the app. A separate historical section keeps ranges such as today, past week, past month, past 3 months, and past year. The FX data uses Yahoo Finance chart data for `SGDMYR=X`; compare with your bank or money-transfer provider before making an actual transfer.

## Better News Sentiment

Alpha Vantage provides a market news and sentiment API. Set your key before running:

```powershell
$env:ALPHAVANTAGE_API_KEY="your_api_key_here"
python .\stock_market_research.py --tickers AAPL MSFT NVDA --sec-user-agent "Your Name your.email@example.com"
```

## Analyze Your Own List

Create a text file with one ticker per line:

```text
AAPL
MSFT
NVDA
JPM
XOM
```

Then run:

```powershell
python .\stock_market_research.py --tickers-file .\my_tickers.txt --sec-user-agent "Your Name your.email@example.com"
```

## How The Ranking Works

The score is out of 10:

- 7 points: price trend, momentum, moving averages, drawdown, and volume confirmation.
- 2 points: SEC filing availability, positive net income, and balance-sheet leverage.
- 1 point: recent news sentiment.

Ratings:

- `Buy-watchlist candidate`: strong enough to investigate for a possible buy.
- `Monitor / possible hold`: mixed evidence; watch for confirmation.
- `Avoid or wait`: weak trend, weak fundamentals, negative news, or missing data.

Before buying anything, check valuation, earnings dates, company guidance, portfolio concentration, stop-loss/risk plan, and whether the stock fits your time horizon.
