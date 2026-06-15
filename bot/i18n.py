"""Lightweight UI translations and LLM language hints."""

from __future__ import annotations

from storage.languages import SUPPORTED_LANGUAGES, normalize_language

__all__ = ["SUPPORTED_LANGUAGES", "normalize_language", "t", "llm_language_clause"]

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "unauthorized": "This bot is restricted to authorized users only.",
        "developer_only": "This command is available to developers only.",
        "command_unavailable": "This command is not available.",
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_greeting": (
            "Welcome! I help you follow a shared investment portfolio — "
            "prices, news, and alerts — and offer guidance only."
        ),
        "welcome_features": (
            "What I can do\n"
            "  • Holdings and latest prices — /portfolio\n"
            "  • Industry news and headlines — /industries, /news_summary\n"
            "  • Portfolio or single-stock review — /analyze or /analyze AAPL\n"
            "  • Urgent alerts and daily summaries — sent automatically"
        ),
        "welcome_quick_start": (
            "Quick start\n"
            "  1. Tap a button below (or type /menu to show the keyboard)\n"
            "  2. Run /portfolio to see your positions\n"
            "  3. Run /analyze for an on-demand portfolio review\n"
            "  4. Run /analyze AAPL to explain one stock's price move"
        ),
        "welcome_tip": (
            "Tip: type /help for the full command list. "
            "Change language with /set_language en (also de, zh, ru)."
        ),
        "welcome_dev_extra": (
            "Developer tools\n"
            "  /add_ticker · /remove_ticker — edit holdings\n"
            "  /list_users · /add_user · /remove_user — manage access\n"
            "  /reload_config · /debug_state — diagnostics"
        ),
        "help_header": "Command reference",
        "help_commands": (
            "Portfolio\n"
            "  /portfolio — holdings and latest prices\n\n"
            "News\n"
            "  /industries — sectors and headline counts\n"
            "  /news_summary — news digest by sector and stock\n\n"
            "Analysis\n"
            "  /analyze — portfolio review\n"
            "  /analyze <TICKER> — explain a price move\n\n"
            "Settings\n"
            "  /set_language <code> — language (en, de, zh, ru)\n"
            "  /menu — show keyboard\n"
            "  /help — this list"
        ),
        "help_dev_commands": (
            "Portfolio edits\n"
            "  /add_ticker <TICKER> [qty] — add or increase a position\n"
            "  /remove_ticker <TICKER> — remove a position\n\n"
            "User management\n"
            "  /list_users — show authorized users\n"
            "  /add_user <chat_id> [role] [lang] — authorize a user\n"
            "  /remove_user <chat_id> — revoke access\n\n"
            "Diagnostics\n"
            "  /reload_config — reload config from disk\n"
            "  /debug_state — internal runtime counters"
        ),
        "menu_hint": (
            "Tap a button below or type a command.\n\n"
            "Portfolio — /portfolio\n"
            "News — /industries · /news_summary\n"
            "Analysis — /analyze\n"
            "Settings — /set_language · /help"
        ),
        "menu_hint_dev": (
            "Developer menu is active.\n\n"
            "User management buttons:\n"
            "/list_users — show authorized users\n"
            "/add_user <chat_id> [role] [lang] — authorize a user\n"
            "/remove_user <chat_id> — revoke access\n\n"
            "Portfolio edits, e.g.:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
        ),
        "add_user_usage": (
            "Usage: /add_user <chat_id> [role] [lang]\n"
            "Example: /add_user 456 ordinary ru"
        ),
        "remove_user_usage": "Usage: /remove_user <chat_id>",
        "add_user_invalid_id": "Invalid chat id: {value!r}",
        "language_current": "Your current language: {language}.",
        "portfolio_empty": "Portfolio is empty.",
        "portfolio_empty_dev": "Portfolio is empty. Use /add_ticker to add a position.",
        "portfolio_header": "Portfolio ({count} position(s))",
        "portfolio_shares": "{symbol} — {shares:g} shares",
        "portfolio_cost_basis": "  Cost basis: {value:.2f}",
        "portfolio_price_unavailable": "  Price: unavailable",
        "portfolio_last_price": "  Last price: {price:.2f} ({change})",
        "portfolio_company": "  Company: {name}",
        "portfolio_quote_as_of": "  Quote as of: {timestamp}",
        "portfolio_quote_as_of_user": "  Price as of {date}",
        "portfolio_position_notes": "  Notes: {notes}",
        "portfolio_notes_header": "Portfolio notes:",
        "portfolio_last_fetch": "Last market fetch: {timestamp}",
        "portfolio_last_fetch_user": "Prices last updated: {date}",
        "industries_empty": (
            "No focus industries configured.\n"
            "Add focus_industries in config.json or map tickers in ticker_industries.json."
        ),
        "industries_empty_user": "No industries to display yet.",
        "industries_header": "Focus industries",
        "industries_line": "- {label}: {count} cached article(s)",
        "industries_line_user": "- {label}: {count} headline(s)",
        "industries_line_none_user": "- {label}: no recent headlines",
        "industries_total": "Total cached news items: {count}",
        "industries_total_user": "{count} headline(s) tracked",
        "industries_updated": "News cache updated: {timestamp}",
        "industries_updated_user": "Last updated: {date}",
        "analyze_header": "Portfolio analysis",
        "analyze_alerts_count": "Rule alerts ({count}):",
        "analyze_no_alerts": "Rule alerts: none triggered.",
        "analyze_llm_disabled": "LLM advisory: disabled (enable_llm_summaries in config.json).",
        "analyze_llm_disabled_user": "AI summary is not available right now.",
        "analyze_llm_empty": "LLM advisory: enabled but no result returned.",
        "analyze_llm_empty_user": "AI summary could not be generated.",
        "analyze_llm_header": "LLM advisory ({source}, {urgency}):",
        "analyze_suggested": "Suggested actions: {actions}",
        "analyze_llm_note": "LLM note: {note}",
        "ticker_header": "Analysis: {symbol}",
        "ticker_no_price": "No cached price available. Run a market fetch first, then retry.",
        "ticker_company": "Company: {name}",
        "ticker_last_price": "Last price: {price:.2f} ({change}) over {window}",
        "ticker_sector": "Sector: {sector}",
        "ticker_llm_disabled": "LLM explanation: disabled (enable_llm_summaries in config.json).",
        "ticker_llm_disabled_user": "AI explanation is not available right now.",
        "ticker_llm_empty": "LLM explanation: unavailable.",
        "ticker_llm_empty_user": "AI explanation could not be generated.",
        "add_ticker_ok": "Added: {message}",
        "add_ticker_fail": "Could not add ticker: {message}",
        "remove_ticker_ok": "Removed: {message}",
        "remove_ticker_fail": "Could not remove ticker: {message}",
        "urgent_alert": "URGENT ALERT",
        "target": "Target",
        "suggested": "Suggested",
        "daily_summary": "Daily Portfolio Summary",
        "holdings_alerts": "Holdings: {holdings} | Active alerts: {alerts}",
        "alerts_header": "Alerts:",
        "plus_more": "- plus {count} more",
        "advisory": "Advisory:",
        "actions": "Actions:",
        "news_by_sector": "News by sector",
        "news_by_ticker": "News by ticker",
        "news_summary_title": "News summary",
        "advisory_footer": "Advisory only — no trades executed.",
        "news_footer": "Advisory only — summaries are based on cached headlines.",
        "review": "Review {target}",
        "monitor": "Monitor {target}",
        "investigate": "Investigate {target}",
        "review_monitor": "Review and monitor",
        "news_no_sector_cache": "No recent news items for this sector in the cache.",
        "news_no_ticker_cache": "No recent news items for this ticker in the cache.",
        "news_no_items_cache": "No recent news items for {label} in the cache.",
        "news_fallback_headlines": "Recent headlines for {label} (AI unavailable):",
        "news_fallback_plus_more": "- plus {count} more",
        "news_llm_disabled": "AI news summaries are not available right now.",
        "alert_urgency_info": "info",
        "alert_urgency_warning": "warning",
        "alert_urgency_urgent": "urgent",
        "alert_nonurgent_header": "{urgency} update",
        "alert_summary_line": "- [{urgency}] {title} ({target})",
        "alert_target_na": "n/a",
        "alert_price_drop_title": "{symbol} down {pct:.1f}% today",
        "alert_price_drop_explanation": (
            "{symbol} fell {pct:.2f}% since the last market fetch, "
            "breaching the {threshold:.1f}% drop threshold."
        ),
        "alert_price_rise_title": "{symbol} up {pct:.1f}% today",
        "alert_price_rise_explanation": (
            "{symbol} rose {pct:.2f}% since the last market fetch, "
            "breaching the {threshold:.1f}% rise threshold."
        ),
        "alert_negative_news_title": "Repeated negative news for {symbol}",
        "alert_negative_news_explanation": (
            "{count} negative articles tagged to {symbol} were found in "
            "the last {hours} hour(s)."
        ),
        "alert_sector_title": "Sector attention: {industry}",
        "alert_sector_explanation": (
            "{count} articles tagged to {industry} were found in the "
            "last {hours} hour(s)."
        ),
        "language_set": "Language updated to {language}.",
        "language_invalid": "Unsupported language. Use: en, de, zh, ru",
        "language_usage": "Usage: /set_language <code>\nExample: /set_language de",
        "reload_ok": "Configuration reloaded from disk.",
        "debug_state": (
            "Debug state:\n"
            "- Positions: {positions}\n"
            "- Cached news: {news}\n"
            "- Pending alerts: {pending}\n"
            "- Authorized users: {users}"
        ),
        "users_list": "Authorized users:\n{lines}",
        "add_user_ok": "Added user {chat_id} ({role}, {language}).",
        "remove_user_ok": "Removed user {chat_id}.",
        "cannot_remove_self": "You cannot remove your own developer account.",
        "user_not_found": "User {chat_id} is not authorized.",
        "user_exists": "User {chat_id} is already authorized.",
    },
    "de": {
        "unauthorized": "Dieser Bot ist nur für autorisierte Benutzer.",
        "developer_only": "Dieser Befehl ist nur für Entwickler verfügbar.",
        "command_unavailable": "Dieser Befehl ist nicht verfügbar.",
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_greeting": (
            "Willkommen! Ich helfe Ihnen, ein gemeinsames Portfolio zu verfolgen — "
            "Kurse, Nachrichten und Warnungen — nur als Beratung."
        ),
        "welcome_features": (
            "Was ich kann\n"
            "  • Bestände und aktuelle Kurse — /portfolio\n"
            "  • Branchennews und Schlagzeilen — /industries, /news_summary\n"
            "  • Portfolio- oder Einzelaktien-Analyse — /analyze oder /analyze AAPL\n"
            "  • Dringende Warnungen und Tageszusammenfassungen — automatisch"
        ),
        "welcome_quick_start": (
            "Schnellstart\n"
            "  1. Tippen Sie unten auf eine Schaltfläche (oder /menu für die Tastatur)\n"
            "  2. /portfolio — Ihre Positionen anzeigen\n"
            "  3. /analyze — Portfolio-Beratung auf Abruf\n"
            "  4. /analyze AAPL — Kursbewegung einer Aktie erklären"
        ),
        "welcome_tip": (
            "Tipp: /help zeigt alle Befehle. "
            "Sprache ändern mit /set_language de (auch en, zh, ru)."
        ),
        "welcome_dev_extra": (
            "Entwickler-Tools\n"
            "  /add_ticker · /remove_ticker — Bestände bearbeiten\n"
            "  /list_users · /add_user · /remove_user — Zugriff verwalten\n"
            "  /reload_config · /debug_state — Diagnose"
        ),
        "help_header": "Befehlsübersicht",
        "help_commands": (
            "Portfolio\n"
            "  /portfolio — Bestände und Kurse\n\n"
            "Nachrichten\n"
            "  /industries — Branchen und Schlagzeilen\n"
            "  /news_summary — Nachrichten nach Sektor und Ticker\n\n"
            "Analyse\n"
            "  /analyze — Portfolio-Beratung\n"
            "  /analyze <TICKER> — Kursbewegung erklären\n\n"
            "Einstellungen\n"
            "  /set_language <code> — Sprache (en, de, zh, ru)\n"
            "  /menu — Tastatur anzeigen\n"
            "  /help — diese Liste"
        ),
        "help_dev_commands": (
            "Bestandsänderungen\n"
            "  /add_ticker <TICKER> [Anzahl] — Position hinzufügen/erhöhen\n"
            "  /remove_ticker <TICKER> — Position entfernen\n\n"
            "Benutzerverwaltung\n"
            "  /list_users — autorisierte Benutzer\n"
            "  /add_user <chat_id> [role] [lang] — Benutzer autorisieren\n"
            "  /remove_user <chat_id> — Zugriff entziehen\n\n"
            "Diagnose\n"
            "  /reload_config — config.json neu laden\n"
            "  /debug_state — interne Laufzeitwerte"
        ),
        "menu_hint": (
            "Tippen Sie unten oder geben Sie einen Befehl ein.\n\n"
            "Portfolio — /portfolio\n"
            "Nachrichten — /industries · /news_summary\n"
            "Analyse — /analyze\n"
            "Einstellungen — /set_language · /help"
        ),
        "menu_hint_dev": (
            "Entwickler-Menü aktiv.\n\n"
            "Benutzerverwaltung:\n"
            "/list_users — autorisierte Benutzer\n"
            "/add_user <chat_id> [role] [lang] — Benutzer hinzufügen\n"
            "/remove_user <chat_id> — Zugriff entziehen\n\n"
            "Bestandsänderungen, z. B.:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
        ),
        "add_user_usage": (
            "Verwendung: /add_user <chat_id> [role] [lang]\n"
            "Beispiel: /add_user 456 ordinary de"
        ),
        "remove_user_usage": "Verwendung: /remove_user <chat_id>",
        "add_user_invalid_id": "Ungültige Chat-ID: {value!r}",
        "language_current": "Ihre aktuelle Sprache: {language}.",
        "portfolio_empty": "Portfolio ist leer.",
        "portfolio_empty_dev": "Portfolio ist leer. Nutzen Sie /add_ticker.",
        "portfolio_header": "Portfolio ({count} Position(en))",
        "portfolio_shares": "{symbol} — {shares:g} Anteile",
        "portfolio_cost_basis": "  Einstand: {value:.2f}",
        "portfolio_price_unavailable": "  Kurs: nicht verfügbar",
        "portfolio_last_price": "  Letzter Kurs: {price:.2f} ({change})",
        "portfolio_company": "  Unternehmen: {name}",
        "portfolio_quote_as_of": "  Kurs vom: {timestamp}",
        "portfolio_quote_as_of_user": "  Kurs vom {date}",
        "portfolio_position_notes": "  Notizen: {notes}",
        "portfolio_notes_header": "Portfolio-Notizen:",
        "portfolio_last_fetch": "Letzter Marktabruf: {timestamp}",
        "portfolio_last_fetch_user": "Kurse zuletzt aktualisiert: {date}",
        "industries_empty": (
            "Keine Branchen konfiguriert.\n"
            "Einträge in config.json oder ticker_industries.json hinzufügen."
        ),
        "industries_empty_user": "Noch keine Branchen zum Anzeigen.",
        "industries_header": "Fokus-Branchen",
        "industries_line": "- {label}: {count} Artikel im Cache",
        "industries_line_user": "- {label}: {count} Schlagzeile(n)",
        "industries_line_none_user": "- {label}: keine aktuellen Schlagzeilen",
        "industries_total": "Nachrichten im Cache gesamt: {count}",
        "industries_total_user": "{count} Schlagzeile(n) erfasst",
        "industries_updated": "Cache aktualisiert: {timestamp}",
        "industries_updated_user": "Zuletzt aktualisiert: {date}",
        "analyze_header": "Portfolio-Analyse",
        "analyze_alerts_count": "Regel-Warnungen ({count}):",
        "analyze_no_alerts": "Regel-Warnungen: keine ausgelöst.",
        "analyze_llm_disabled": "LLM-Beratung: deaktiviert (enable_llm_summaries in config.json).",
        "analyze_llm_disabled_user": "KI-Zusammenfassung derzeit nicht verfügbar.",
        "analyze_llm_empty": "LLM-Beratung: aktiviert, aber kein Ergebnis.",
        "analyze_llm_empty_user": "KI-Zusammenfassung konnte nicht erstellt werden.",
        "analyze_llm_header": "LLM-Beratung ({source}, {urgency}):",
        "analyze_suggested": "Empfohlene Aktionen: {actions}",
        "analyze_llm_note": "LLM-Hinweis: {note}",
        "ticker_header": "Analyse: {symbol}",
        "ticker_no_price": "Kein Kurs im Cache. Marktdaten abrufen und erneut versuchen.",
        "ticker_company": "Unternehmen: {name}",
        "ticker_last_price": "Letzter Kurs: {price:.2f} ({change}) über {window}",
        "ticker_sector": "Sektor: {sector}",
        "ticker_llm_disabled": "LLM-Erklärung: deaktiviert (enable_llm_summaries in config.json).",
        "ticker_llm_disabled_user": "KI-Erklärung derzeit nicht verfügbar.",
        "ticker_llm_empty": "LLM-Erklärung: nicht verfügbar.",
        "ticker_llm_empty_user": "KI-Erklärung konnte nicht erstellt werden.",
        "add_ticker_ok": "Hinzugefügt: {message}",
        "add_ticker_fail": "Ticker nicht hinzugefügt: {message}",
        "remove_ticker_ok": "Entfernt: {message}",
        "remove_ticker_fail": "Ticker nicht entfernt: {message}",
        "urgent_alert": "DRINGENDE WARNUNG",
        "target": "Ziel",
        "suggested": "Empfehlung",
        "daily_summary": "Tägliche Portfolio-Zusammenfassung",
        "holdings_alerts": "Bestände: {holdings} | Aktive Warnungen: {alerts}",
        "alerts_header": "Warnungen:",
        "plus_more": "- plus {count} weitere",
        "advisory": "Beratung:",
        "actions": "Aktionen:",
        "news_by_sector": "Nachrichten nach Sektor",
        "news_by_ticker": "Nachrichten nach Ticker",
        "news_summary_title": "Nachrichten-Zusammenfassung",
        "advisory_footer": "Nur Beratung — keine Trades.",
        "news_footer": "Nur Beratung — basierend auf zwischengespeicherten Schlagzeilen.",
        "review": "{target} prüfen",
        "monitor": "{target} beobachten",
        "investigate": "{target}-Sektor untersuchen",
        "review_monitor": "Prüfen und beobachten",
        "news_no_sector_cache": "Keine aktuellen Nachrichten zu diesem Sektor im Cache.",
        "news_no_ticker_cache": "Keine aktuellen Nachrichten zu diesem Ticker im Cache.",
        "news_no_items_cache": "Keine aktuellen Nachrichten zu {label} im Cache.",
        "news_fallback_headlines": "Aktuelle Schlagzeilen zu {label} (KI nicht verfügbar):",
        "news_fallback_plus_more": "- plus {count} weitere",
        "news_llm_disabled": "KI-Nachrichtenzusammenfassungen sind derzeit nicht verfügbar.",
        "alert_urgency_info": "Info",
        "alert_urgency_warning": "Warnung",
        "alert_urgency_urgent": "Dringend",
        "alert_nonurgent_header": "{urgency}-Update",
        "alert_summary_line": "- [{urgency}] {title} ({target})",
        "alert_target_na": "k. A.",
        "alert_price_drop_title": "{symbol} heute -{pct:.1f}%",
        "alert_price_drop_explanation": (
            "{symbol} ist seit dem letzten Marktabruf um {pct:.2f}% gefallen "
            "und hat die Schwelle von {threshold:.1f}% unterschritten."
        ),
        "alert_price_rise_title": "{symbol} heute +{pct:.1f}%",
        "alert_price_rise_explanation": (
            "{symbol} ist seit dem letzten Marktabruf um {pct:.2f}% gestiegen "
            "und hat die Schwelle von {threshold:.1f}% überschritten."
        ),
        "alert_negative_news_title": "Wiederholte negative Nachrichten zu {symbol}",
        "alert_negative_news_explanation": (
            "{count} negative Artikel zu {symbol} in den letzten {hours} Stunde(n) gefunden."
        ),
        "alert_sector_title": "Branchenaufmerksamkeit: {industry}",
        "alert_sector_explanation": (
            "{count} Artikel zu {industry} in den letzten {hours} Stunde(n) gefunden."
        ),
        "language_set": "Sprache auf {language} geändert.",
        "language_invalid": "Sprache nicht unterstützt. Verwenden: en, de, zh, ru",
        "language_usage": "Verwendung: /set_language <code>\nBeispiel: /set_language de",
        "reload_ok": "Konfiguration von der Festplatte neu geladen.",
        "debug_state": (
            "Debug-Status:\n"
            "- Positionen: {positions}\n"
            "- Nachrichten-Cache: {news}\n"
            "- Ausstehende Warnungen: {pending}\n"
            "- Autorisierte Benutzer: {users}"
        ),
        "users_list": "Autorisierte Benutzer:\n{lines}",
        "add_user_ok": "Benutzer {chat_id} hinzugefügt ({role}, {language}).",
        "remove_user_ok": "Benutzer {chat_id} entfernt.",
        "cannot_remove_self": "Sie können Ihr eigenes Entwickler-Konto nicht entfernen.",
        "user_not_found": "Benutzer {chat_id} ist nicht autorisiert.",
        "user_exists": "Benutzer {chat_id} ist bereits autorisiert.",
    },
    "zh": {
        "unauthorized": "此机器人仅限授权用户使用。",
        "developer_only": "此命令仅开发者可用。",
        "command_unavailable": "此命令不可用。",
        "welcome_title": "投资组合智能助手",
        "welcome_greeting": (
            "欢迎！我帮助您跟踪共享投资组合——价格、新闻和预警——仅提供建议，不执行交易。"
        ),
        "welcome_features": (
            "我能做什么\n"
            "  • 持仓与最新价格 — /portfolio\n"
            "  • 行业新闻与头条 — /industries、/news_summary\n"
            "  • 组合或单股分析 — /analyze 或 /analyze AAPL\n"
            "  • 紧急预警与每日摘要 — 自动推送"
        ),
        "welcome_quick_start": (
            "快速开始\n"
            "  1. 点击下方按钮（或输入 /menu 显示键盘）\n"
            "  2. 运行 /portfolio 查看持仓\n"
            "  3. 运行 /analyze 获取组合建议\n"
            "  4. 运行 /analyze AAPL 解释单只股票涨跌"
        ),
        "welcome_tip": (
            "提示：输入 /help 查看全部命令。\n"
            "使用 /set_language zh 切换语言（也支持 en、de、ru）。"
        ),
        "welcome_dev_extra": (
            "开发者工具\n"
            "  /add_ticker · /remove_ticker — 编辑持仓\n"
            "  /list_users · /add_user · /remove_user — 管理访问权限\n"
            "  /reload_config · /debug_state — 诊断"
        ),
        "help_header": "命令参考",
        "help_commands": (
            "投资组合\n"
            "  /portfolio — 持仓与最新价格\n\n"
            "新闻\n"
            "  /industries — 行业与新闻数量\n"
            "  /news_summary — 按行业/股票的新闻摘要\n\n"
            "分析\n"
            "  /analyze — 投资组合建议\n"
            "  /analyze <代码> — 解释价格变动\n\n"
            "设置\n"
            "  /set_language <code> — 语言 (en, de, zh, ru)\n"
            "  /menu — 显示键盘\n"
            "  /help — 本列表"
        ),
        "help_dev_commands": (
            "编辑持仓\n"
            "  /add_ticker <代码> [数量] — 添加或增加持仓\n"
            "  /remove_ticker <代码> — 移除持仓\n\n"
            "用户管理\n"
            "  /list_users — 查看授权用户\n"
            "  /add_user <chat_id> [role] [lang] — 授权用户\n"
            "  /remove_user <chat_id> — 撤销访问\n\n"
            "诊断\n"
            "  /reload_config — 重新加载 config.json\n"
            "  /debug_state — 显示内部状态"
        ),
        "menu_hint": (
            "点击下方按钮或输入命令。\n\n"
            "投资组合 — /portfolio\n"
            "新闻 — /industries · /news_summary\n"
            "分析 — /analyze\n"
            "设置 — /set_language · /help"
        ),
        "menu_hint_dev": (
            "开发者菜单已启用。\n\n"
            "用户管理：\n"
            "/list_users — 查看授权用户\n"
            "/add_user <chat_id> [role] [lang] — 添加用户\n"
            "/remove_user <chat_id> — 移除访问\n\n"
            "编辑持仓示例：\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
        ),
        "add_user_usage": (
            "用法：/add_user <chat_id> [role] [lang]\n"
            "示例：/add_user 456 ordinary zh"
        ),
        "remove_user_usage": "用法：/remove_user <chat_id>",
        "add_user_invalid_id": "无效的 chat id：{value!r}",
        "language_current": "您当前的语言：{language}。",
        "portfolio_empty": "投资组合为空。",
        "portfolio_empty_dev": "投资组合为空。请使用 /add_ticker 添加。",
        "portfolio_header": "投资组合（{count} 个持仓）",
        "portfolio_shares": "{symbol} — {shares:g} 股",
        "portfolio_cost_basis": "  成本：{value:.2f}",
        "portfolio_price_unavailable": "  价格：不可用",
        "portfolio_last_price": "  最新价：{price:.2f}（{change}）",
        "portfolio_company": "  公司：{name}",
        "portfolio_quote_as_of": "  报价时间：{timestamp}",
        "portfolio_quote_as_of_user": "  价格日期 {date}",
        "portfolio_position_notes": "  备注：{notes}",
        "portfolio_notes_header": "组合备注：",
        "portfolio_last_fetch": "上次行情更新：{timestamp}",
        "portfolio_last_fetch_user": "价格最后更新：{date}",
        "industries_empty": "未配置关注行业。请在 config.json 或 ticker_industries.json 中设置。",
        "industries_empty_user": "暂无行业数据。",
        "industries_header": "关注行业",
        "industries_line": "- {label}：缓存 {count} 条新闻",
        "industries_line_user": "- {label}：{count} 条新闻",
        "industries_line_none_user": "- {label}：暂无新闻",
        "industries_total": "缓存新闻总数：{count}",
        "industries_total_user": "共 {count} 条新闻",
        "industries_updated": "新闻缓存更新：{timestamp}",
        "industries_updated_user": "最后更新：{date}",
        "analyze_header": "投资组合分析",
        "analyze_alerts_count": "规则预警（{count}）：",
        "analyze_no_alerts": "规则预警：无触发项。",
        "analyze_llm_disabled": "LLM 建议：已禁用（config.json 中 enable_llm_summaries）。",
        "analyze_llm_disabled_user": "AI 摘要暂不可用。",
        "analyze_llm_empty": "LLM 建议：已启用但未返回结果。",
        "analyze_llm_empty_user": "无法生成 AI 摘要。",
        "analyze_llm_header": "LLM 建议（{source}，{urgency}）：",
        "analyze_suggested": "建议行动：{actions}",
        "analyze_llm_note": "LLM 说明：{note}",
        "ticker_header": "分析：{symbol}",
        "ticker_no_price": "无缓存价格。请先获取行情后重试。",
        "ticker_company": "公司：{name}",
        "ticker_last_price": "最新价：{price:.2f}（{change}），周期 {window}",
        "ticker_sector": "行业：{sector}",
        "ticker_llm_disabled": "LLM 解释：已禁用（config.json 中 enable_llm_summaries）。",
        "ticker_llm_disabled_user": "AI 解释暂不可用。",
        "ticker_llm_empty": "LLM 解释：不可用。",
        "ticker_llm_empty_user": "无法生成 AI 解释。",
        "add_ticker_ok": "已添加：{message}",
        "add_ticker_fail": "无法添加：{message}",
        "remove_ticker_ok": "已移除：{message}",
        "remove_ticker_fail": "无法移除：{message}",
        "urgent_alert": "紧急预警",
        "target": "目标",
        "suggested": "建议",
        "daily_summary": "每日投资组合摘要",
        "holdings_alerts": "持仓：{holdings} | 活跃预警：{alerts}",
        "alerts_header": "预警：",
        "plus_more": "- 另有 {count} 条",
        "advisory": "建议：",
        "actions": "行动：",
        "news_by_sector": "按行业新闻",
        "news_by_ticker": "按股票新闻",
        "news_summary_title": "新闻摘要",
        "advisory_footer": "仅供参考 — 不执行交易。",
        "news_footer": "仅供参考 — 基于缓存新闻标题。",
        "review": "复查 {target}",
        "monitor": "关注 {target}",
        "investigate": "调查 {target} 行业",
        "review_monitor": "复查并关注",
        "news_no_sector_cache": "缓存中暂无该行业的近期新闻。",
        "news_no_ticker_cache": "缓存中暂无该股票的近期新闻。",
        "news_no_items_cache": "缓存中暂无 {label} 的近期新闻。",
        "news_fallback_headlines": "{label} 近期头条（AI 暂不可用）：",
        "news_fallback_plus_more": "- 另有 {count} 条",
        "news_llm_disabled": "AI 新闻摘要暂不可用。",
        "alert_urgency_info": "提示",
        "alert_urgency_warning": "警告",
        "alert_urgency_urgent": "紧急",
        "alert_nonurgent_header": "{urgency} 更新",
        "alert_summary_line": "- [{urgency}] {title}（{target}）",
        "alert_target_na": "无",
        "alert_price_drop_title": "{symbol} 今日下跌 {pct:.1f}%",
        "alert_price_drop_explanation": (
            "自上次行情更新以来，{symbol} 下跌 {pct:.2f}%，"
            "超过 {threshold:.1f}% 的下跌阈值。"
        ),
        "alert_price_rise_title": "{symbol} 今日上涨 {pct:.1f}%",
        "alert_price_rise_explanation": (
            "自上次行情更新以来，{symbol} 上涨 {pct:.2f}%，"
            "超过 {threshold:.1f}% 的上涨阈值。"
        ),
        "alert_negative_news_title": "{symbol} 重复负面新闻",
        "alert_negative_news_explanation": (
            "过去 {hours} 小时内发现 {count} 条与 {symbol} 相关的负面新闻。"
        ),
        "alert_sector_title": "行业关注：{industry}",
        "alert_sector_explanation": (
            "过去 {hours} 小时内发现 {count} 条与 {industry} 相关的新闻。"
        ),
        "language_set": "语言已更新为 {language}。",
        "language_invalid": "不支持的语言。请使用：en, de, zh, ru",
        "language_usage": "用法：/set_language <code>\n示例：/set_language zh",
        "reload_ok": "已从磁盘重新加载配置。",
        "debug_state": (
            "调试状态：\n"
            "- 持仓数：{positions}\n"
            "- 缓存新闻：{news}\n"
            "- 待处理预警：{pending}\n"
            "- 授权用户：{users}"
        ),
        "users_list": "授权用户：\n{lines}",
        "add_user_ok": "已添加用户 {chat_id}（{role}，{language}）。",
        "remove_user_ok": "已移除用户 {chat_id}。",
        "cannot_remove_self": "无法移除您自己的开发者账户。",
        "user_not_found": "用户 {chat_id} 未授权。",
        "user_exists": "用户 {chat_id} 已在授权列表中。",
    },
    "ru": {
        "unauthorized": "Этот бот доступен только авторизованным пользователям.",
        "developer_only": "Эта команда доступна только разработчикам.",
        "command_unavailable": "Эта команда недоступна.",
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_greeting": (
            "Добро пожаловать! Я помогаю следить за общим портфелем — "
            "котировки, новости и предупреждения — только в режиме консультации."
        ),
        "welcome_features": (
            "Что я умею\n"
            "  • Позиции и актуальные цены — /portfolio\n"
            "  • Новости по отраслям — /industries, /news_summary\n"
            "  • Обзор портфеля или одной акции — /analyze или /analyze AAPL\n"
            "  • Срочные предупреждения и ежедневные сводки — автоматически"
        ),
        "welcome_quick_start": (
            "Быстрый старт\n"
            "  1. Нажмите кнопку ниже (или введите /menu для клавиатуры)\n"
            "  2. /portfolio — ваши позиции\n"
            "  3. /analyze — обзор портфеля по запросу\n"
            "  4. /analyze AAPL — объяснить движение цены одной акции"
        ),
        "welcome_tip": (
            "Подсказка: /help — полный список команд. "
            "Сменить язык: /set_language ru (также en, de, zh)."
        ),
        "welcome_dev_extra": (
            "Инструменты разработчика\n"
            "  /add_ticker · /remove_ticker — изменение портфеля\n"
            "  /list_users · /add_user · /remove_user — управление доступом\n"
            "  /reload_config · /debug_state — диагностика"
        ),
        "help_header": "Справка по командам",
        "help_commands": (
            "Портфель\n"
            "  /portfolio — позиции и котировки\n\n"
            "Новости\n"
            "  /industries — отрасли и количество новостей\n"
            "  /news_summary — сводка по секторам и тикерам\n\n"
            "Анализ\n"
            "  /analyze — обзор портфеля\n"
            "  /analyze <ТИКЕР> — объяснить движение цены\n\n"
            "Настройки\n"
            "  /set_language <code> — язык (en, de, zh, ru)\n"
            "  /menu — показать клавиатуру\n"
            "  /help — этот список"
        ),
        "help_dev_commands": (
            "Изменение портфеля\n"
            "  /add_ticker <ТИКЕР> [кол-во] — добавить или увеличить позицию\n"
            "  /remove_ticker <ТИКЕР> — удалить позицию\n\n"
            "Управление пользователями\n"
            "  /list_users — список пользователей\n"
            "  /add_user <chat_id> [role] [lang] — добавить пользователя\n"
            "  /remove_user <chat_id> — удалить доступ\n\n"
            "Диагностика\n"
            "  /reload_config — перезагрузить config.json\n"
            "  /debug_state — внутреннее состояние"
        ),
        "menu_hint": (
            "Нажмите кнопку ниже или введите команду.\n\n"
            "Портфель — /portfolio\n"
            "Новости — /industries · /news_summary\n"
            "Анализ — /analyze\n"
            "Настройки — /set_language · /help"
        ),
        "menu_hint_dev": (
            "Меню разработчика активно.\n\n"
            "Управление пользователями:\n"
            "/list_users — список пользователей\n"
            "/add_user <chat_id> [role] [lang] — добавить пользователя\n"
            "/remove_user <chat_id> — удалить доступ\n\n"
            "Примеры изменения портфеля:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
        ),
        "add_user_usage": (
            "Использование: /add_user <chat_id> [role] [lang]\n"
            "Пример: /add_user 456 ordinary ru"
        ),
        "remove_user_usage": "Использование: /remove_user <chat_id>",
        "add_user_invalid_id": "Неверный chat id: {value!r}",
        "language_current": "Ваш текущий язык: {language}.",
        "portfolio_empty": "Портфель пуст.",
        "portfolio_empty_dev": "Портфель пуст. Добавьте позиции через /add_ticker.",
        "portfolio_header": "Портфель ({count} поз.)",
        "portfolio_shares": "{symbol} — {shares:g} акций",
        "portfolio_cost_basis": "  Средняя цена: {value:.2f}",
        "portfolio_price_unavailable": "  Цена: недоступна",
        "portfolio_last_price": "  Последняя цена: {price:.2f} ({change})",
        "portfolio_company": "  Компания: {name}",
        "portfolio_quote_as_of": "  Котировка на: {timestamp}",
        "portfolio_quote_as_of_user": "  Цена на {date}",
        "portfolio_position_notes": "  Заметки: {notes}",
        "portfolio_notes_header": "Заметки по портфелю:",
        "portfolio_last_fetch": "Последнее обновление рынка: {timestamp}",
        "portfolio_last_fetch_user": "Цены обновлены: {date}",
        "industries_empty": (
            "Отрасли не настроены.\n"
            "Добавьте focus_industries в config.json или тикеры в ticker_industries.json."
        ),
        "industries_empty_user": "Пока нет данных по отраслям.",
        "industries_header": "Отслеживаемые отрасли",
        "industries_line": "- {label}: {count} статей в кэше",
        "industries_line_user": "- {label}: {count} новостей",
        "industries_line_none_user": "- {label}: нет свежих новостей",
        "industries_total": "Всего новостей в кэше: {count}",
        "industries_total_user": "Всего новостей: {count}",
        "industries_updated": "Кэш новостей обновлён: {timestamp}",
        "industries_updated_user": "Обновлено: {date}",
        "analyze_header": "Анализ портфеля",
        "analyze_alerts_count": "Предупреждения по правилам ({count}):",
        "analyze_no_alerts": "Предупреждения по правилам: нет срабатываний.",
        "analyze_llm_disabled": "LLM-рекомендация: отключена (enable_llm_summaries в config.json).",
        "analyze_llm_disabled_user": "ИИ-сводка сейчас недоступна.",
        "analyze_llm_empty": "LLM-рекомендация: включена, но результат не получен.",
        "analyze_llm_empty_user": "Не удалось сформировать ИИ-сводку.",
        "analyze_llm_header": "LLM-рекомендация ({source}, {urgency}):",
        "analyze_suggested": "Рекомендуемые действия: {actions}",
        "analyze_llm_note": "Примечание LLM: {note}",
        "ticker_header": "Анализ: {symbol}",
        "ticker_no_price": "Нет кэшированной цены. Дождитесь обновления рынка и повторите.",
        "ticker_company": "Компания: {name}",
        "ticker_last_price": "Последняя цена: {price:.2f} ({change}) за {window}",
        "ticker_sector": "Сектор: {sector}",
        "ticker_llm_disabled": "LLM-объяснение: отключено (enable_llm_summaries в config.json).",
        "ticker_llm_disabled_user": "ИИ-объяснение сейчас недоступно.",
        "ticker_llm_empty": "LLM-объяснение: недоступно.",
        "ticker_llm_empty_user": "Не удалось сформировать ИИ-объяснение.",
        "add_ticker_ok": "Добавлено: {message}",
        "add_ticker_fail": "Не удалось добавить: {message}",
        "remove_ticker_ok": "Удалено: {message}",
        "remove_ticker_fail": "Не удалось удалить: {message}",
        "urgent_alert": "СРОЧНОЕ ПРЕДУПРЕЖДЕНИЕ",
        "target": "Цель",
        "suggested": "Рекомендация",
        "daily_summary": "Ежедневная сводка по портфелю",
        "holdings_alerts": "Позиции: {holdings} | Активные предупреждения: {alerts}",
        "alerts_header": "Предупреждения:",
        "plus_more": "- ещё {count}",
        "advisory": "Рекомендация:",
        "actions": "Действия:",
        "news_by_sector": "Новости по секторам",
        "news_by_ticker": "Новости по тикерам",
        "news_summary_title": "Сводка новостей",
        "advisory_footer": "Только консультации — сделки не выполняются.",
        "news_footer": "Только консультации — на основе кэшированных заголовков.",
        "review": "Проверить {target}",
        "monitor": "Наблюдать за {target}",
        "investigate": "Изучить сектор {target}",
        "review_monitor": "Проверить и наблюдать",
        "news_no_sector_cache": "В кэше нет свежих новостей по этому сектору.",
        "news_no_ticker_cache": "В кэше нет свежих новостей по этому тикеру.",
        "news_no_items_cache": "В кэше нет свежих новостей по {label}.",
        "news_fallback_headlines": "Свежие заголовки по {label} (ИИ недоступен):",
        "news_fallback_plus_more": "- ещё {count}",
        "news_llm_disabled": "ИИ-сводки новостей сейчас недоступны.",
        "alert_urgency_info": "инфо",
        "alert_urgency_warning": "предупреждение",
        "alert_urgency_urgent": "срочно",
        "alert_nonurgent_header": "Обновление: {urgency}",
        "alert_summary_line": "- [{urgency}] {title} ({target})",
        "alert_target_na": "н/д",
        "alert_price_drop_title": "{symbol} сегодня -{pct:.1f}%",
        "alert_price_drop_explanation": (
            "С момента последнего обновления рынка {symbol} упал на {pct:.2f}% "
            "и превысил порог падения {threshold:.1f}%."
        ),
        "alert_price_rise_title": "{symbol} сегодня +{pct:.1f}%",
        "alert_price_rise_explanation": (
            "С момента последнего обновления рынка {symbol} вырос на {pct:.2f}% "
            "и превысил порог роста {threshold:.1f}%."
        ),
        "alert_negative_news_title": "Повторяющиеся негативные новости по {symbol}",
        "alert_negative_news_explanation": (
            "За последние {hours} ч. найдено {count} негативных статей по {symbol}."
        ),
        "alert_sector_title": "Внимание к сектору: {industry}",
        "alert_sector_explanation": (
            "За последние {hours} ч. найдено {count} статей по сектору {industry}."
        ),
        "language_set": "Язык изменён на {language}.",
        "language_invalid": "Язык не поддерживается. Используйте: en, de, zh, ru",
        "language_usage": "Использование: /set_language <code>\nПример: /set_language ru",
        "reload_ok": "Конфигурация перезагружена с диска.",
        "debug_state": (
            "Отладочное состояние:\n"
            "- Позиции: {positions}\n"
            "- Кэш новостей: {news}\n"
            "- Ожидающие предупреждения: {pending}\n"
            "- Авторизованные пользователи: {users}"
        ),
        "users_list": "Авторизованные пользователи:\n{lines}",
        "add_user_ok": "Добавлен пользователь {chat_id} ({role}, {language}).",
        "remove_user_ok": "Пользователь {chat_id} удалён.",
        "cannot_remove_self": "Нельзя удалить собственную учётную запись разработчика.",
        "user_not_found": "Пользователь {chat_id} не авторизован.",
        "user_exists": "Пользователь {chat_id} уже авторизован.",
    },
}


def t(key: str, lang: str, **kwargs: object) -> str:
    """Translate a message key for the given language."""
    bundle = _MESSAGES.get(normalize_language(lang), _MESSAGES["en"])
    template = bundle.get(key, _MESSAGES["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def llm_language_clause(lang: str) -> str:
    """Instruction appended to LLM prompts for localized responses."""
    labels = {"en": "English", "de": "German", "zh": "Chinese", "ru": "Russian"}
    label = labels.get(normalize_language(lang), "English")
    return f"Write your entire response in {label}."
