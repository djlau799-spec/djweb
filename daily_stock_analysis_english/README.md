# Daily Stock Analysis - English Upstream App

This folder is a separate English-first copy of `ZhuLinsen/daily_stock_analysis`.

It does not replace the Streamlit app in the repository root. The Streamlit app still runs from:

```text
streamlit_app.py
```

This upstream-style app runs as a FastAPI + React/Vite Web workspace on port `8000`.

## English Defaults

Use `env.english.example` as the starting configuration. It sets:

```text
REPORT_LANGUAGE=en
WEBUI_ENABLED=true
WEBUI_HOST=0.0.0.0
WEBUI_PORT=8000
API_PORT=8000
```

Reports, notifications, and report widgets will use English where the upstream project supports English output.

## Run With Docker

```powershell
Copy-Item .\env.english.example .\.env
docker compose -f .\docker-compose.english.yml up --build -d server
```

Open:

```text
http://localhost:8000
```

Stop it:

```powershell
docker compose -f .\docker-compose.english.yml down
```

## Run Locally

```powershell
Copy-Item .\env.english.example .\.env
pip install -r .\requirements.txt
python .\webui.py
```

Open:

```text
http://localhost:8000
```

## Important Configuration

At minimum, set:

```text
STOCK_LIST=600519,hk00700,AAPL,TSLA
REPORT_LANGUAGE=en
```

For higher-quality analysis, configure at least one LLM key:

```text
ANSPIRE_API_KEYS=
AIHUBMIX_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

For better news/catalyst retrieval, configure at least one search provider:

```text
ANSPIRE_API_KEYS=
SERPAPI_API_KEYS=
TAVILY_API_KEYS=
BOCHA_API_KEYS=
BRAVE_API_KEYS=
MINIMAX_API_KEYS=
SEARXNG_BASE_URLS=
```

## Upstream English Docs

- `docs/README_EN.md`
- `docs/full-guide_EN.md`
- `docs/FAQ_EN.md`
- `docs/LLM_CONFIG_GUIDE_EN.md`

This app is research support only and is not financial advice.
