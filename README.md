# Personal Portfolio Intelligence Bot

## Overview

This project is a Docker-first, self-hosted Telegram portfolio intelligence bot for a single user. It tracks portfolio positions stored in JSON, collects market and news data from public sources, analyzes whether anything important changed, and sends summaries or urgent alerts through Telegram. The design keeps the entire system isolated inside containers instead of installing the runtime directly on the host machine, which is a common pattern for Ollama-based local LLM projects and containerized Telegram bot setups.[cite:37][cite:43]

The bot is intended to act as a personal monitoring and decision-support assistant, not as an auto-executing trading system. It keeps portfolio memory, watches selected industries, fetches fresh data on a schedule, and turns raw updates into concise messages that are easier to review than manually checking many sites.[cite:13][cite:15]

## Why Docker

Docker is the preferred runtime for this project because it keeps Python dependencies, scheduled jobs, and the bot process isolated from the main operating system. This makes the project easier to reproduce, restart, move to another machine, and maintain over time.[cite:37][cite:43]

Running the bot in containers is also a good fit for a multi-service design where the Telegram bot and local LLM are separate processes connected over an internal Docker network. Existing Ollama Telegram examples commonly use Docker Compose with one application container plus one Ollama container, persistent model volumes, and service-to-service communication over `http://ollama:11434`.[cite:37][cite:46]

## Project Goals

- Keep everything internal and self-hosted.
- Avoid paid agent platforms and keep recurring costs close to zero.
- Store the user's portfolio, watchlist, and focus industries locally.
- Continuously pull market and news data for current holdings and tracked sectors.
- Detect urgent changes and send Telegram alerts.
- Generate concise suggestions using rules first and a local LLM second.
- Run the whole stack through Docker Compose rather than the host environment.[cite:37][cite:43]

## Core Idea

The project combines four practical layers:

1. **Portfolio memory**: local JSON files store positions, settings, watched tickers, and current bot state.
2. **External awareness**: market data and news collectors fetch current information related to holdings and focus industries.[cite:13]
3. **Decision support**: a rules engine and optionally a local Ollama model summarize changes into useful guidance.[cite:15][cite:43]
4. **Delivery**: a Telegram bot handles commands, daily digests, and urgent notifications.[cite:37]

The bot should only recommend actions such as review, trim, hold, or investigate. It should not place trades automatically.

## Docker-First Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                     Docker Compose                       │
│                                                          │
│  ┌────────────────────┐      ┌────────────────────────┐  │
│  │ portfolio-bot      │─────▶│ ollama                 │  │
│  │ Python app         │      │ local LLM API          │  │
│  │ Telegram handlers  │      │ port 11434             │  │
│  │ Scheduler          │      │ persistent model store │  │
│  └─────────┬──────────┘      └────────────────────────┘  │
│            │                                             │
│            ▼                                             │
│   Mounted project volumes                                │
│   - ./data  -> JSON state                                │
│   - ./logs  -> runtime logs                              │
│   - ollama_data -> model files                           │
└──────────────────────────────────────────────────────────┘
```

## Recommended Folder Structure

```text
portfolio-intelligence-bot/
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── main.py
├── bot/
│   ├── __init__.py
│   ├── handlers.py
│   ├── commands.py
│   └── formatter.py
├── collectors/
│   ├── __init__.py
│   ├── market_data.py
│   ├── news_data.py
│   └── sector_data.py
├── analysis/
│   ├── __init__.py
│   ├── rules.py
│   ├── llm.py
│   └── summarizer.py
├── scheduler/
│   ├── __init__.py
│   └── jobs.py
├── storage/
│   ├── __init__.py
│   ├── json_store.py
│   └── locking.py
├── data/
│   ├── config.json
│   ├── portfolio.json
│   ├── state.json
│   └── news_cache.json
└── logs/
    └── .gitkeep
```

## Docker Configuration

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     curl     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### `docker-compose.yml`

```yaml
services:
  portfolio-bot:
    build: .
    container_name: portfolio-bot
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      - ollama
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    working_dir: /app
    command: ["python", "main.py"]

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  ollama_data:
```

## Environment Variables

### `.env.example`

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b
TZ=Asia/Hong_Kong
```

## Running the Project

1. Copy `.env.example` to `.env` and fill in your Telegram values.
2. Edit the JSON files in `data/`.
   - Add holdings to `data/portfolio.json` under `positions` (each entry needs a `ticker` and `shares`).
   - The bot reads those tickers and fetches quotes via yfinance on a 30-minute schedule.
   - Successful fetches are written to `data/state.json` as `latest_prices` with `last_market_fetch_at`.
3. Start the containers with `docker compose up --build -d`.[cite:37][cite:42]
4. Pull a model with `docker exec -it ollama ollama pull llama3.1:8b`.[cite:43]
5. View logs with `docker compose logs -f portfolio-bot`.
6. Stop the stack with `docker compose down`.

### Manual market fetch smoke test

Run a one-off fetch against your mounted `data/` directory:

```bash
docker compose run --rm --no-deps portfolio-bot python scripts/test_market_data.py
```

This loads `portfolio.json`, fetches quotes for each ticker, updates `state.json`, and prints a short summary. A single bad ticker is logged and skipped without failing the rest of the batch.
