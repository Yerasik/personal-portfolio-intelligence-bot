# Data file templates

Live JSON under `data/` is **not** committed to git (holdings, Telegram chat IDs, strategies, caches).

On a fresh clone, copy these templates into `data/`:

```bash
cp data/examples/*.json data/
```

Then edit `data/portfolio.json`, `data/config.json`, and authorize users via `TELEGRAM_CHAT_ID` on first run (or edit `data/users.json` locally).

The bot also creates missing files with defaults on startup.
