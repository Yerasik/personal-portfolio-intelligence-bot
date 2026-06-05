# Codebase tour — how to read this project

This bot runs as **one Python process** inside Docker. The main thread listens for Telegram commands; a background thread runs scheduled jobs (market data, news, rules, daily digest).

## Big picture

```text
Telegram user
     │
     ▼
main.py ──► bot/handlers.py ──► bot/commands.py ──► storage/repository.py ──► data/*.json
     │
     ├──► scheduler/jobs.py (background thread)
     │         │
     │         ├── collectors/market_data.py  ──► yfinance ──► state.json
     │         ├── collectors/news_data.py    ──► RSS feeds ──► news_cache.json
     │         ├── analysis/rules.py          ──► alert candidates
     │         ├── bot/notifier.py            ──► Telegram push messages
     │         └── analysis/summarizer.py     ──► daily digest text
     │
     └──► analysis/llm.py (optional) ──► Ollama API ──► advisory text
```

## Recommended reading order

Read in this order the first time. Each step builds on the previous one.

### Step 1 — Entry and configuration

| Order | File | What you learn |
|-------|------|----------------|
| 1 | `main.py` | Startup sequence: env → JSON → Telegram + scheduler |
| 2 | `config/settings.py` | Environment variables (`.env`) |
| 3 | `config/loader.py` | Loads all JSON files into one bundle |
| 4 | `config/startup.py` | Validates Telegram creds, JSON schema, Ollama probe |
| 5 | `config/ollama.py` | How Ollama URL/model is resolved |

### Step 2 — Data layer

| Order | File | What you learn |
|-------|------|----------------|
| 6 | `storage/models.py` | Shape of every JSON document (Pydantic models) |
| 7 | `storage/paths.py` | Where files live (`/app/data/*.json`) |
| 8 | `storage/locking.py` | File locks prevent corrupt writes |
| 9 | `storage/json_store.py` | Atomic read/write with validation |
| 10 | `storage/repository.py` | High-level `load_portfolio()`, `save_state()`, etc. |

**Try:** open `data/portfolio.json` and `data/config.json` while reading `storage/models.py`.

### Step 3 — Collectors (data ingestion)

| Order | File | What you learn |
|-------|------|----------------|
| 11 | `collectors/base.py` | Shared collector interface |
| 12 | `collectors/market_data.py` | Fetches stock prices via yfinance → `state.json` |
| 13 | `collectors/news_data.py` | Fetches RSS news → `news_cache.json` |

### Step 4 — Analysis (brains)

| Order | File | What you learn |
|-------|------|----------------|
| 14 | `analysis/rules.py` | Rule-based alerts (price moves, news, sectors) |
| 15 | `analysis/llm.py` | Optional Ollama summaries + fallback |
| 16 | `analysis/summarizer.py` | Combines rules + LLM into digest text |

### Step 5 — Telegram interface

| Order | File | What you learn |
|-------|------|----------------|
| 17 | `bot/app.py` | Builds the Telegram Application |
| 18 | `bot/handlers.py` | Maps `/start`, `/portfolio`, etc. to functions |
| 19 | `bot/commands.py` | Business logic for each command |
| 20 | `bot/formatter.py` | Plain-text message formatting |
| 21 | `bot/notifier.py` | Outbound alerts and daily summary to Telegram |

### Step 6 — Scheduler (automation)

| Order | File | What you learn |
|-------|------|----------------|
| 22 | `scheduler/jobs.py` | APScheduler jobs and intervals from `config.json` |

### Step 7 — Smoke tests (optional)

Run these to see each layer in isolation:

```bash
docker compose run --rm --no-deps portfolio-bot python scripts/test_storage.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_market_data.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_rules.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_bot_commands.py
```

## Runtime flows

### Flow A — You send `/portfolio` in Telegram

```text
handlers.py: portfolio_command()
  → commands.py: portfolio_message()
    → repository.load_portfolio() + load_state()
    → formatter.format_portfolio()
  → reply_text() back to Telegram
```

### Flow B — Scheduler runs market fetch (every N minutes)

```text
jobs.py: run_market_data_job()
  → MarketDataCollector.run()
    → MarketDataService.fetch_batch()  (yfinance)
    → repository.save_state()          (latest_prices)
```

### Flow C — Scheduler evaluates rules and sends urgent alert

```text
jobs.py: run_rule_evaluation_job()
  → RulesEngine.evaluate()
  → repository.save_state()            (pending_alerts)
  → TelegramNotifier.deliver_urgent_alerts()
    → formatter.format_urgent_alert()
    → Telegram Bot API sendMessage
```

### Flow D — You send `/analyze`

Same as Flow C, but triggered manually and formatted for chat (`commands.analyze_message()`), optionally calling Ollama if `enable_llm_summaries` is true.

## Key JSON files

| File | Written by | Purpose |
|------|------------|---------|
| `portfolio.json` | You (manual) | Your holdings |
| `config.json` | You (manual) | Thresholds, RSS URLs, scheduler intervals |
| `state.json` | Bot (auto) | Latest prices, pending alerts, last fetch times |
| `news_cache.json` | Bot (auto) | Cached RSS articles with tags |

## Configuration precedence

1. **Environment** (`.env`) — secrets and overrides (`TELEGRAM_*`, `OLLAMA_*`)
2. **`data/config.json`** — app behaviour (intervals, thresholds, RSS feeds)
3. **Code defaults** — e.g. Ollama model in `config/ollama.py`
