# Personal Portfolio Intelligence Bot

Docker-first, self-hosted Telegram bot for monitoring a personal portfolio. It stores holdings and settings in JSON, fetches market and news data on a schedule, evaluates rule-based alerts, optionally summarizes with Ollama, and delivers messages to a single Telegram chat.

Advisory only — the bot never executes trades.

## Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                     Docker Compose                       │
│                                                          │
│  ┌────────────────────┐      ┌────────────────────────┐  │
│  │ portfolio-bot      │─────▶│ ollama (optional LLM)  │  │
│  │ single Python proc │      │ http://ollama:11434    │  │
│  │ Telegram + scheduler│     │ volume: ollama_data    │  │
│  └─────────┬──────────┘      └────────────────────────┘  │
│            │                                             │
│            ▼                                             │
│   ./data  -> /app/data   (JSON persistence)             │
│   ./logs  -> /app/logs   (application logs)              │
└──────────────────────────────────────────────────────────┘
```

The `portfolio-bot` container runs **one Python process** (`python main.py`):
- Main thread: Telegram polling
- Background daemon thread: APScheduler jobs

## Prerequisites

- Docker and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram chat id (message [@userinfobot](https://t.me/userinfobot) or inspect bot updates)

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set **required** values:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...your-real-token
TELEGRAM_CHAT_ID=123456789
```

Optional overrides (defaults work inside Docker):

```env
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen3:30b
LOG_LEVEL=INFO
DATA_DIR=/app/data
LOG_DIR=/app/logs
TZ=Asia/Hong_Kong
```

The app **exits immediately** if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is missing or still a placeholder. Ollama is **optional** — the bot starts without it and uses fallback summaries when LLM is enabled but unreachable.

### 2. Configure portfolio data

Edit files under `data/` on the host (mounted into the container):

| File | Purpose |
|------|---------|
| `data/portfolio.json` | Holdings (`ticker`, `shares`, optional `cost_basis`) |
| `data/config.json` | Timezone, RSS feeds, alert thresholds, scheduler intervals |
| `data/state.json` | Runtime state (prices, alerts) — usually auto-managed |
| `data/news_cache.json` | Cached news — usually auto-managed |

Example `data/portfolio.json`:

```json
{
  "positions": [
    { "ticker": "AAPL", "shares": 10, "cost_basis": 150.0 }
  ],
  "notes": ""
}
```

On first startup, missing JSON files are created with defaults and logged as warnings.

### 3. Build and start

```bash
docker compose up --build -d
```

### 4. Pull an Ollama model (optional)

Only needed if `enable_llm_summaries` is `true` in `data/config.json`:

```bash
docker exec -it ollama ollama pull qwen3:30b
```

Verify models:

```bash
docker exec -it ollama ollama list
```

### 5. Verify logs

```bash
docker compose logs -f portfolio-bot
```

Healthy startup logs include:
- Validated JSON documents (or initialized defaults)
- Scheduler interval summary
- `Starting Telegram polling (single-process mode)`
- Ollama status (reachable, or warning if optional LLM unavailable)

### 6. Talk to the bot

Message your bot in Telegram (from the configured chat id only):

- `/start` — welcome
- `/help` — commands
- `/portfolio` — holdings and latest prices
- `/industries` — focus industries and news counts
- `/analyze` — rules + optional LLM summary

## Volume behavior

| Host path | Container path | Behavior |
|-----------|----------------|----------|
| `./data` | `/app/data` | **Persistent.** Survives container rebuilds. Edit JSON here. |
| `./logs` | `/app/logs` | **Persistent.** `portfolio-bot.log` written here. |
| `ollama_data` (named volume) | `/root/.ollama` | **Persistent.** Stores downloaded models. |

Rebuilding the image does **not** delete `./data` or `./logs`. `docker compose down -v` removes the Ollama named volume (models must be re-pulled).

## Scheduler jobs

Configured in `data/config.json`:

| Setting | Default | Job |
|---------|---------|-----|
| `market_fetch_interval_minutes` | 30 | Refresh yfinance quotes |
| `news_fetch_interval_minutes` | 60 | Refresh RSS news cache |
| `rule_evaluation_interval_minutes` | 60 | Evaluate rules, send urgent Telegram alerts |
| `enable_daily_summary` + `digest_hour/minute` | 08:00 | Daily digest to Telegram |

Job failures are logged and do not crash the bot process.

## Smoke tests

Run without starting the long-lived bot:

```bash
docker compose run --rm --no-deps portfolio-bot python scripts/test_storage.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_market_data.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_news_data.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_rules.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_llm.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_bot_commands.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_notifier.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_scheduler_jobs.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_startup.py
```

## Troubleshooting

### Bot exits immediately on startup

**Symptom:** Container restarts or exits with code 1.

**Checks:**

```bash
docker compose logs portfolio-bot
```

Common causes:
- `FATAL: TELEGRAM_BOT_TOKEN is missing or still set to a placeholder` — set real values in `.env`
- `FATAL: Invalid config JSON` — fix syntax in the affected file under `data/`
- Pydantic validation error in JSON schema — compare with defaults in `storage/models.py`

### No Telegram responses

- Confirm `TELEGRAM_CHAT_ID` matches the chat sending commands (not the bot id)
- Check logs for `Ignoring unauthorized Telegram chat_id=...`
- Ensure the bot process is running: `docker compose ps`

### Ollama / LLM warnings but bot runs

Expected when `enable_llm_summaries` is true but Ollama is down or the model is not pulled. The bot uses deterministic fallback summaries. Fix:

```bash
docker compose up -d ollama
docker exec -it ollama ollama pull qwen3:30b
docker compose restart portfolio-bot
```

### No market or news data

- Add tickers to `data/portfolio.json`
- Add RSS URLs to `data/config.json` → `rss_feed_urls`
- Inspect logs for collector job results
- Run manual smoke tests (see above)

### Permission errors on `./data` or `./logs`

Ensure the host directories exist and are writable:

```bash
mkdir -p data logs
chmod u+rwX data logs
```

## Environment reference

| Variable | Required | Default (in container) | Description |
|----------|----------|------------------------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized user chat id |
| `OLLAMA_BASE_URL` | No | `http://ollama:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | No | `qwen3:30b` | Model name for summaries |
| `DATA_DIR` | No | `/app/data` | JSON persistence directory |
| `LOG_DIR` | No | `/app/logs` | Log file directory |
| `LOG_LEVEL` | No | `INFO` | Python log level |
| `TZ` | No | `Asia/Hong_Kong` | Container timezone |

Ollama settings can also be overridden in `data/config.json` (`ollama_base_url`, `ollama_model`) when env vars are unset.

## Project layout

```text
portfolio-intelligence-bot/
├── main.py                 # Single-process entrypoint
├── config/                 # Env + startup validation
├── bot/                    # Telegram handlers + notifier
├── collectors/             # Market and news fetchers
├── analysis/               # Rules + Ollama summaries
├── scheduler/              # APScheduler jobs
├── storage/                # JSON persistence
├── scripts/                # Smoke tests
├── data/                   # Mounted JSON state (host)
└── logs/                   # Mounted logs (host)
```

## Manual verification checklist

Use this after deployment or any upgrade:

- [ ] `.env` exists with real `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (not placeholders)
- [ ] `docker compose up --build -d` starts both services without crash loops
- [ ] `docker compose logs portfolio-bot` shows JSON validation and scheduler registration
- [ ] `data/portfolio.json` lists at least one holding (or you accept an empty portfolio)
- [ ] `/portfolio` in Telegram returns holdings or an empty-portfolio message
- [ ] `/help` responds only from the configured chat id
- [ ] After a few minutes, `data/state.json` updates `last_market_fetch_at` (if tickers configured)
- [ ] If RSS feeds configured, `data/news_cache.json` gains items over time
- [ ] If rules trigger urgent alerts, Telegram receives formatted urgent messages (not raw JSON)
- [ ] `./logs/portfolio-bot.log` grows and contains job success/failure lines
- [ ] Rebuild test: `docker compose up --build -d` preserves `./data` contents
- [ ] Optional LLM: `docker exec -it ollama ollama list` shows your model; startup log reports Ollama reachable
- [ ] Optional LLM disabled: bot starts cleanly with `enable_llm_summaries: false` even if Ollama is stopped

## Stop and reset

```bash
# Stop containers (keep data)
docker compose down

# Stop and remove Ollama models volume
docker compose down -v
```
