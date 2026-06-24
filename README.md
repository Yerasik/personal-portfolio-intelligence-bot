# Personal Portfolio Intelligence Bot

Docker-first, self-hosted Telegram bot for monitoring a personal portfolio. It stores holdings and settings in JSON, fetches market and news data on a schedule, evaluates rule-based alerts, optionally summarizes with Ollama, and delivers messages to a single Telegram chat.

News collection, sector alerts, `/industries`, and LLM prompts all use the same **focus industry list**: entries from `focus_industries` in `config.json` plus industries inferred from your holdings via `ticker_industries.json`. Significant price moves can be explained on demand (`/analyze <ticker>`) or attached to alerts with a best-effort LLM rationale.

Advisory only — the bot never executes trades.

**Note:** Application Python code is copied into the Docker image at build time. Only `./data` and `./logs` are mounted from the host — after pulling or editing source code, run `docker compose up --build -d` to pick up changes.

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

**Git:** live `data/*.json` files are gitignored (holdings, Telegram chat IDs, strategies, caches). Use `data/examples/` as templates — on a fresh clone run `cp data/examples/*.json data/` then edit locally.

Edit files under `data/` on the host (mounted into the container):

| File | Purpose |
|------|---------|
| `data/portfolio.json` | Holdings (`ticker`, `shares`, optional `cost_basis`) |
| `data/config.json` | Timezone, RSS feeds, alert thresholds, scheduler intervals |
| `data/ticker_industries.json` | Static `ticker` → industry map; merged with `focus_industries` for news, rules, `/industries`, and LLM context |
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

Example `data/ticker_industries.json`:

```json
{
  "ticker_to_industry": {
    "AAPL": "Consumer Electronics",
    "MSFT": "Software - Infrastructure",
    "NVDA": "Semiconductors",
    "1810.HK": "Consumer Electronics"
  }
}
```

Map every holding ticker you care about. Industries from this file are **automatically added** to the tracked list alongside `focus_industries` in `config.json` — you do not need to duplicate them in both places.

On first startup, missing JSON files are created with defaults and logged as warnings. Invalid JSON (including `ticker_industries.json`) fails fast at startup with a clear error.

### Focus industries (how tracking works)

The bot builds one combined industry list from:

1. `focus_industries` in `data/config.json` (manual watchlist, e.g. `"AI"`, `"Hong Kong"`)
2. Industries looked up from `data/ticker_industries.json` for tickers in `data/portfolio.json`

That list drives:

| Feature | Behavior |
|---------|----------|
| News RSS tagging | Articles mentioning a focus industry get `sector_tags` |
| Sector alerts | `sector_attention` when an industry gets many articles in a window |
| `/industries` | Shows each tracked industry and cached article count |
| `/analyze` LLM prompt | Includes news tagged to portfolio tickers or focus industries |

Industry keywords use **word-boundary matching** (so short labels like `"AI"` do not match inside unrelated words such as *said*).

Price alerts only evaluate **current** portfolio tickers plus `extra_watchlist` in config; removed holdings are pruned from `state.json` → `latest_prices` on the next market fetch.

### RSS feed URLs

Use direct RSS/Atom XML endpoints in `rss_feed_urls`, not HTML index or landing pages. Good examples: `https://feeds.reuters.com/reuters/businessNews`, `https://techcrunch.com/feed/`. Bad examples: site homepages or `/rss-feeds/` directory pages. Failed feeds are logged and skipped; if every URL fails, the news job reports failure.

### 3. Build and start

```bash
docker compose up --build -d
```

On NVIDIA hosts with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed, **you must use the GPU override** — plain `docker compose up` does not pass a GPU to Ollama:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

Verify GPU inside the container (Ollama logs should show `inference compute` with your GPU name, not `id=cpu`):

```bash
docker logs ollama 2>&1 | grep "inference compute"
```

Without the GPU override, Ollama runs on CPU (slower for large models like `qwen3:30b`).

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
- Validated JSON documents: `config`, `portfolio`, `ticker_industries`, `state`, `news_cache` (or initialized defaults)
- Scheduler interval summary
- `Starting Telegram polling (single-process mode)`
- Ollama status (reachable, or warning if optional LLM unavailable)

### 6. Talk to the bot

Message your bot in Telegram (from a chat id listed in `data/users.json`):

**Everyone**

- `/start` — welcome (shows the tap-to-run menu keyboard)
- `/menu` — show the reply keyboard menu again
- `/help` — command reference
- `/portfolio` — holdings grouped by long/short horizon, with prices and P/L when cost basis is set
- `/strategy` — investment idea behind each holding
- `/strategy <SYMBOL>` — full idea for one ticker
- `/industries` — tracked industries (config + portfolio map) and cached news counts per industry
- `/news_summary` — LLM summaries of cached news by sector and by portfolio ticker
- `/analyze` — rules + optional LLM portfolio advisory
- `/analyze <ticker>` — explain a ticker's recent price move using ticker-tagged news (e.g. `/analyze AAPL`)
- `/set_language <code>` — change reply language (`en`, `de`, `zh`, `ru`)

**Developers only** (portfolio edits notify ordinary users; sells require confirmation)

- `/dev_menu` — inline menu for all portfolio edits; each button shows the full how-to guide
- `/deposit_cash <amount> [note]` — credit cash balance (developer-only in `/portfolio`; undo supported)
- `/add_ticker <SYMBOL> [shares [cost_basis]]` — add or increase a holding with optional per-share cost basis (blended when adding to an existing position)
- `/add_ticker_strategy <SYMBOL> <long|short> [shares [cost_basis]] <reasoning>` — add a holding with investment idea; for one share with cost use `1 <cost> <reasoning>`
- `/edit_strategy <SYMBOL> <text>` — hard-overwrite the stored strategy text
- `/sell_ticker <SYMBOL> [shares] <price> <reasoning>` — sell at price per share; omit shares to sell the full position; confirm before users are notified
- `/undo` — reverse the last completed add/remove/sell notification
- `/remove_ticker <SYMBOL>` — remove a holding and its strategy
- `/list_users` · `/add_user <chat_id> [role] [lang]` · `/remove_user <chat_id>` — manage access
- `/reload_config` · `/debug_state` — diagnostics

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
| `news_fetch_interval_minutes` | 60 | Refresh RSS news cache, focused on portfolio industries |
| `rule_evaluation_interval_minutes` | 60 | Evaluate rules, send urgent Telegram alerts |
| `enable_daily_summary` + `digest_hour/minute` | 08:00 | Daily digest to Telegram |

Job failures are logged and do not crash the bot process.

When `enable_llm_summaries` is `true`:

- Price-move alerts (`price_drop`/`price_rise`) are enriched with a best-effort LLM explanation (recent **ticker-tagged** news). The same explainer powers `/analyze <ticker>`.
- `/news_summary` and the daily digest include grounded LLM summaries of cached news **by sector** and **by portfolio ticker** (headline-only fallback when the LLM is unavailable).

Large models on CPU can take several minutes per LLM request (default timeout: 300s). Use the GPU compose override on supported hardware for faster inference.

## Smoke tests

Run without starting the long-lived bot:

```bash
docker compose run --rm --no-deps portfolio-bot python scripts/test_storage.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_market_data.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_news_data.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_industries.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_portfolio_edits.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_news_summarizer.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_rules.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_llm.py
docker compose run --rm --no-deps portfolio-bot python scripts/test_move_explainer.py
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
- `FATAL: Invalid config JSON` (or `portfolio`, `ticker_industries`, `state`, `news_cache`) — fix syntax in the affected file under `data/`
- Pydantic validation error in JSON schema — compare with defaults in `storage/models.py`

### Code changes not reflected in the running bot

Python source is baked into the image (`COPY . .` in the Dockerfile), not bind-mounted. After editing `.py` files locally:

```bash
docker compose up --build -d
```

Verify the container has new code, e.g. `docker compose exec portfolio-bot grep build_news_focus_industries /app/bot/commands.py`.

### Ollama slow or using CPU only

**Symptom:** `docker logs ollama` shows `inference compute id=cpu` and `offloaded 0/N layers to GPU`.

**Cause:** The stack was started with `docker compose up` only. GPU access requires the override file.

**Fix:**

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d ollama
docker logs ollama 2>&1 | grep "inference compute"
# Should show your GPU, e.g. "NVIDIA GeForce RTX 4090"
```

Also check:
- Host GPU works: `nvidia-smi`
- Docker sees GPU: `docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`
- Model is pulled: `docker exec -it ollama ollama pull qwen3:30b`

### No Telegram responses

- Ensure your chat id is listed in `data/users.json` (or bootstrap via `TELEGRAM_CHAT_ID` on first run)
- Developers can authorize users with `/add_user <chat_id> [role] [lang]`
- Check logs for `Ignoring unauthorized Telegram chat_id=...`
- Ensure the bot process is running: `docker compose ps`

### Multi-user access and languages

- Authorized users live in `data/users.json` with `chat_id`, `language` (`en`, `de`, `zh`, `ru`), and `role` (`developer` or `ordinary`)
- On first run with an empty user list, the bot seeds one **developer** from `TELEGRAM_CHAT_ID`
- All authorized users share the same portfolio; alerts and daily summaries fan out to every user in their language
The developer reply keyboard is intentionally compact: `/deposit_cash` and `/dev_menu` only. All other edit commands are reachable via `/dev_menu` inline buttons (which show usage guides) or by typing the slash command directly.

- Developer-only commands: `/dev_menu`, `/deposit_cash`, `/add_ticker`, `/add_ticker_strategy`, `/edit_strategy`, `/sell_ticker`, `/undo`, `/remove_ticker`, `/reload_config`, `/debug_state`, `/list_users`, `/add_user`, `/remove_user`
- Any authorized user: `/set_language <code>` to change reply language

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
| `TELEGRAM_CHAT_ID` | Bootstrap only | — | Seeds first developer when `users.json` is empty |
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
├── docker-compose.yml      # Base stack (CPU Ollama)
├── docker-compose.gpu.yml  # Optional NVIDIA GPU override for Ollama
├── config/                 # Env + startup validation
├── bot/                    # Telegram handlers + notifier
├── collectors/             # Market and news fetchers
├── analysis/               # Rules, industries, move_explainer, Ollama summaries
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
- [ ] `docker compose logs portfolio-bot` shows JSON validation (including `ticker_industries`) and scheduler registration
- [ ] `data/portfolio.json` lists at least one holding (or you accept an empty portfolio)
- [ ] `data/ticker_industries.json` maps holding tickers to industries where sector tracking matters
- [ ] `/portfolio` in Telegram returns holdings or an empty-portfolio message
- [ ] `/industries` lists both `focus_industries` from config and portfolio-derived industries
- [ ] `/help` responds only from the configured chat id
- [ ] After a few minutes, `data/state.json` updates `last_market_fetch_at` (if tickers configured)
- [ ] If RSS feeds configured, `data/news_cache.json` gains items over time
- [ ] If rules trigger urgent alerts, Telegram receives formatted urgent messages (not raw JSON)
- [ ] `./logs/portfolio-bot.log` grows and contains job success/failure lines
- [ ] Rebuild test: `docker compose up --build -d` preserves `./data` contents
- [ ] Optional LLM: `docker exec -it ollama ollama list` shows your model; startup log reports Ollama reachable
- [ ] Optional GPU: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d` and `docker exec ollama nvidia-smi` show the GPU
- [ ] Optional LLM disabled: bot starts cleanly with `enable_llm_summaries: false` even if Ollama is stopped
- [ ] After source edits: `docker compose up --build -d` and behavior matches the updated code

## Stop and reset

```bash
# Stop containers (keep data)
docker compose down

# Stop and remove Ollama models volume
docker compose down -v
```
