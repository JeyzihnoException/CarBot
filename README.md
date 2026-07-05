# CarBot

Telegram bot for ranking used car listings with an LLM and a local cache.

## Flow

1. User sends an Auto.ru search URL with filters already selected.
2. Bot extracts listing links from the search page.
3. Bot opens each listing and collects car details.
4. Bot sends only new listings to an LLM.
5. Bot stores scored cars in a local cache grouped by model.
6. Bot returns the top results across all cached cars for that model.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

Fill `.env`:

```text
TELEGRAM_BOT_TOKEN=...
LLM_PROVIDER=gemini
LLM_PROXY_URL=
LLM_SYSTEM_PROMPT=Ты опытный эксперт по подбору автомобилей...
CAR_CACHE_PATH=./data/car_cache.json
GEMINI_API_KEY=...
HEADLESS=true
BROWSER_PERSISTENT_CONTEXT=false
MAX_ADS_TO_SCAN=10
```

The app loads `.env` automatically.

For small VPS instances, keep `BROWSER_PERSISTENT_CONTEXT=false` and start with
`MAX_ADS_TO_SCAN=5` or `10`.

## Run

```powershell
python main.py
```

## Test Without Telegram

Parse a few ads without LLM:

```powershell
python test_run.py "https://auto.ru/..." --limit 5 --no-llm
```

Run the full parser plus cache update:

```powershell
python test_run.py "https://auto.ru/..." --limit 10 --top 5
```

For OpenAI instead of Gemini, set:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

## LLM Proxy Through VPS

If the whole machine is connected to a VPN such as WireGuard, no app setting is needed.
For routing only LLM requests through your VPS, start a local proxy tunnel and set
`LLM_PROXY_URL`.

SSH SOCKS tunnel example:

```powershell
ssh -N -D 127.0.0.1:1080 user@your-vps-ip
```

Then set in `.env`:

```text
LLM_PROXY_URL=socks5://127.0.0.1:1080
```

HTTP proxy URLs also work:

```text
LLM_PROXY_URL=http://127.0.0.1:8080
```

## User Commands

- `/start` - short help.
- `/top 5` - set result count for the current bot process.

## Telegram Menu

- `Показать топ` - choose a cached model and show top 3 ads by rating.
- `Анализ объявлений` - send an Auto.ru search URL, evaluate new ads, update cache, and show the current top.

## Architecture

- `main.py` - Telegram bot entrypoint.
- `providers/base.py` - provider contract for Auto.ru, Drom, and future sources.
- `providers/autoru_provider.py` - Auto.ru scraper.
- `models/car.py` - normalized car and ranking models.
- `service/ai_service.py` - LLM scoring.
- `storage/storage.py` - small JSON storage helper.
- `storage/car_cache.py` - local cache grouped by model.
