"""Lightweight UI translations and LLM language hints."""

from __future__ import annotations

from storage.languages import SUPPORTED_LANGUAGES, normalize_language

__all__ = ["SUPPORTED_LANGUAGES", "normalize_language", "t", "llm_language_clause"]

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "unauthorized": "This bot is restricted to authorized users only.",
        "developer_only": "This command is available to developers only.",
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_body": (
            "This bot monitors your portfolio, news, and rule-based alerts. "
            "It provides advisory guidance only and does not execute trades."
        ),
        "welcome_menu": "Use the menu below or /help to see available commands.",
        "welcome_edit": "Edit holdings: /add_ticker AAPL 5 · /remove_ticker MSFT",
        "help_header": "Available commands:",
        "help_commands": (
            "/start — welcome message\n"
            "/menu — show the tap-to-run menu\n"
            "/help — show this help\n"
            "/portfolio — holdings and latest prices\n"
            "/industries — focus industries and news counts\n"
            "/news_summary — LLM news by sector and ticker\n"
            "/add_ticker <SYMBOL> [shares] — add or increase a holding\n"
            "/remove_ticker <SYMBOL> — remove a holding\n"
            "/analyze — portfolio advisory\n"
            "/analyze <ticker> — explain a price move\n"
            "/set_language <code> — set language (en, de, zh, ru)"
        ),
        "help_dev_commands": (
            "Developer commands:\n"
            "/reload_config — reload config.json from disk\n"
            "/debug_state — show internal runtime counters\n"
            "/add_user <chat_id> [role] [lang] — authorize a user\n"
            "/remove_user <chat_id> — revoke user access\n"
            "/list_users — show authorized users"
        ),
        "menu_hint": (
            "Choose an action from the menu below.\n\n"
            "Portfolio edits need a symbol, e.g.:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
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
        "portfolio_empty": "Portfolio is empty. Add positions with /add_ticker.",
        "portfolio_header": "Portfolio ({count} position(s))",
        "portfolio_shares": "{symbol} — {shares:g} shares",
        "portfolio_cost_basis": "  Cost basis: {value:.2f}",
        "portfolio_price_unavailable": "  Price: unavailable",
        "portfolio_last_price": "  Last price: {price:.2f} ({change})",
        "portfolio_company": "  Company: {name}",
        "portfolio_quote_as_of": "  Quote as of: {timestamp}",
        "portfolio_position_notes": "  Notes: {notes}",
        "portfolio_notes_header": "Portfolio notes:",
        "portfolio_last_fetch": "Last market fetch: {timestamp}",
        "industries_empty": (
            "No focus industries configured.\n"
            "Add focus_industries in config.json or map tickers in ticker_industries.json."
        ),
        "industries_header": "Focus industries",
        "industries_line": "- {label}: {count} cached article(s)",
        "industries_total": "Total cached news items: {count}",
        "industries_updated": "News cache updated: {timestamp}",
        "analyze_header": "Portfolio analysis",
        "analyze_alerts_count": "Rule alerts ({count}):",
        "analyze_no_alerts": "Rule alerts: none triggered.",
        "analyze_llm_disabled": "LLM advisory: disabled (enable_llm_summaries in config.json).",
        "analyze_llm_empty": "LLM advisory: enabled but no result returned.",
        "analyze_llm_header": "LLM advisory ({source}, {urgency}):",
        "analyze_suggested": "Suggested actions: {actions}",
        "analyze_llm_note": "LLM note: {note}",
        "ticker_header": "Analysis: {symbol}",
        "ticker_no_price": "No cached price available. Run a market fetch first, then retry.",
        "ticker_company": "Company: {name}",
        "ticker_last_price": "Last price: {price:.2f} ({change}) over {window}",
        "ticker_sector": "Sector: {sector}",
        "ticker_llm_disabled": "LLM explanation: disabled (enable_llm_summaries in config.json).",
        "ticker_llm_empty": "LLM explanation: unavailable.",
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
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_body": (
            "Dieser Bot überwacht Ihr Portfolio, Nachrichten und regelbasierte Warnungen. "
            "Nur Beratung — keine Trades."
        ),
        "welcome_menu": "Nutzen Sie das Menü unten oder /help für alle Befehle.",
        "welcome_edit": "Bestände: /add_ticker AAPL 5 · /remove_ticker MSFT",
        "help_header": "Verfügbare Befehle:",
        "help_commands": (
            "/start — Willkommensnachricht\n"
            "/menu — Tipp-Menü anzeigen\n"
            "/help — diese Hilfe\n"
            "/portfolio — Bestände und Kurse\n"
            "/industries — Branchen und Nachrichten\n"
            "/news_summary — LLM-Nachrichten nach Sektor/Ticker\n"
            "/add_ticker <SYMBOL> [Anteile] — Position hinzufügen/erhöhen\n"
            "/remove_ticker <SYMBOL> — Position entfernen\n"
            "/analyze — Portfolio-Beratung\n"
            "/analyze <ticker> — Kursbewegung erklären\n"
            "/set_language <code> — Sprache (en, de, zh, ru)"
        ),
        "help_dev_commands": (
            "Entwickler-Befehle:\n"
            "/reload_config — config.json neu laden\n"
            "/debug_state — interne Laufzeitwerte\n"
            "/add_user <chat_id> [role] [lang] — Benutzer autorisieren\n"
            "/remove_user <chat_id> — Zugriff entziehen\n"
            "/list_users — autorisierte Benutzer"
        ),
        "menu_hint": (
            "Wählen Sie eine Aktion im Menü unten.\n\n"
            "Beispiele für Bestandsänderungen:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
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
        "portfolio_empty": "Portfolio ist leer. Nutzen Sie /add_ticker.",
        "portfolio_header": "Portfolio ({count} Position(en))",
        "portfolio_shares": "{symbol} — {shares:g} Anteile",
        "portfolio_cost_basis": "  Einstand: {value:.2f}",
        "portfolio_price_unavailable": "  Kurs: nicht verfügbar",
        "portfolio_last_price": "  Letzter Kurs: {price:.2f} ({change})",
        "portfolio_company": "  Unternehmen: {name}",
        "portfolio_quote_as_of": "  Kurs vom: {timestamp}",
        "portfolio_position_notes": "  Notizen: {notes}",
        "portfolio_notes_header": "Portfolio-Notizen:",
        "portfolio_last_fetch": "Letzter Marktabruf: {timestamp}",
        "industries_empty": (
            "Keine Branchen konfiguriert.\n"
            "Einträge in config.json oder ticker_industries.json hinzufügen."
        ),
        "industries_header": "Fokus-Branchen",
        "industries_line": "- {label}: {count} Artikel im Cache",
        "industries_total": "Nachrichten im Cache gesamt: {count}",
        "industries_updated": "Cache aktualisiert: {timestamp}",
        "analyze_header": "Portfolio-Analyse",
        "analyze_alerts_count": "Regel-Warnungen ({count}):",
        "analyze_no_alerts": "Regel-Warnungen: keine ausgelöst.",
        "analyze_llm_disabled": "LLM-Beratung: deaktiviert (enable_llm_summaries in config.json).",
        "analyze_llm_empty": "LLM-Beratung: aktiviert, aber kein Ergebnis.",
        "analyze_llm_header": "LLM-Beratung ({source}, {urgency}):",
        "analyze_suggested": "Empfohlene Aktionen: {actions}",
        "analyze_llm_note": "LLM-Hinweis: {note}",
        "ticker_header": "Analyse: {symbol}",
        "ticker_no_price": "Kein Kurs im Cache. Marktdaten abrufen und erneut versuchen.",
        "ticker_company": "Unternehmen: {name}",
        "ticker_last_price": "Letzter Kurs: {price:.2f} ({change}) über {window}",
        "ticker_sector": "Sektor: {sector}",
        "ticker_llm_disabled": "LLM-Erklärung: deaktiviert (enable_llm_summaries in config.json).",
        "ticker_llm_empty": "LLM-Erklärung: nicht verfügbar.",
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
        "welcome_title": "投资组合智能助手",
        "welcome_body": "本机器人监控您的投资组合、新闻和规则预警。仅提供建议，不执行交易。",
        "welcome_menu": "请使用下方菜单或 /help 查看命令。",
        "welcome_edit": "编辑持仓：/add_ticker AAPL 5 · /remove_ticker MSFT",
        "help_header": "可用命令：",
        "help_commands": (
            "/start — 欢迎消息\n"
            "/menu — 显示菜单\n"
            "/help — 显示帮助\n"
            "/portfolio — 持仓与最新价格\n"
            "/industries — 关注行业与新闻\n"
            "/news_summary — 按行业/股票的新闻摘要\n"
            "/add_ticker <代码> [数量] — 添加或增加持仓\n"
            "/remove_ticker <代码> — 移除持仓\n"
            "/analyze — 投资组合建议\n"
            "/analyze <代码> — 解释价格变动\n"
            "/set_language <code> — 设置语言 (en, de, zh, ru)"
        ),
        "help_dev_commands": (
            "开发者命令：\n"
            "/reload_config — 重新加载 config.json\n"
            "/debug_state — 显示内部状态\n"
            "/add_user <chat_id> [role] [lang] — 授权用户\n"
            "/remove_user <chat_id> — 撤销访问\n"
            "/list_users — 显示授权用户"
        ),
        "menu_hint": (
            "请从下方菜单选择操作。\n\n"
            "编辑持仓示例：\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
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
        "portfolio_empty": "投资组合为空。请使用 /add_ticker 添加。",
        "portfolio_header": "投资组合（{count} 个持仓）",
        "portfolio_shares": "{symbol} — {shares:g} 股",
        "portfolio_cost_basis": "  成本：{value:.2f}",
        "portfolio_price_unavailable": "  价格：不可用",
        "portfolio_last_price": "  最新价：{price:.2f}（{change}）",
        "portfolio_company": "  公司：{name}",
        "portfolio_quote_as_of": "  报价时间：{timestamp}",
        "portfolio_position_notes": "  备注：{notes}",
        "portfolio_notes_header": "组合备注：",
        "portfolio_last_fetch": "上次行情更新：{timestamp}",
        "industries_empty": "未配置关注行业。请在 config.json 或 ticker_industries.json 中设置。",
        "industries_header": "关注行业",
        "industries_line": "- {label}：缓存 {count} 条新闻",
        "industries_total": "缓存新闻总数：{count}",
        "industries_updated": "新闻缓存更新：{timestamp}",
        "analyze_header": "投资组合分析",
        "analyze_alerts_count": "规则预警（{count}）：",
        "analyze_no_alerts": "规则预警：无触发项。",
        "analyze_llm_disabled": "LLM 建议：已禁用（config.json 中 enable_llm_summaries）。",
        "analyze_llm_empty": "LLM 建议：已启用但未返回结果。",
        "analyze_llm_header": "LLM 建议（{source}，{urgency}）：",
        "analyze_suggested": "建议行动：{actions}",
        "analyze_llm_note": "LLM 说明：{note}",
        "ticker_header": "分析：{symbol}",
        "ticker_no_price": "无缓存价格。请先获取行情后重试。",
        "ticker_company": "公司：{name}",
        "ticker_last_price": "最新价：{price:.2f}（{change}），周期 {window}",
        "ticker_sector": "行业：{sector}",
        "ticker_llm_disabled": "LLM 解释：已禁用（config.json 中 enable_llm_summaries）。",
        "ticker_llm_empty": "LLM 解释：不可用。",
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
        "welcome_title": "Portfolio Intelligence Bot",
        "welcome_body": (
            "Этот бот отслеживает ваш портфель, новости и предупреждения по правилам. "
            "Только консультации — сделки не выполняются."
        ),
        "welcome_menu": "Используйте меню ниже или /help для списка команд.",
        "welcome_edit": "Редактирование: /add_ticker AAPL 5 · /remove_ticker MSFT",
        "help_header": "Доступные команды:",
        "help_commands": (
            "/start — приветствие\n"
            "/menu — показать меню\n"
            "/help — эта справка\n"
            "/portfolio — позиции и котировки\n"
            "/industries — отрасли и новости\n"
            "/news_summary — сводка новостей по секторам/тикерам\n"
            "/add_ticker <ТИКЕР> [кол-во] — добавить или увеличить позицию\n"
            "/remove_ticker <ТИКЕР> — удалить позицию\n"
            "/analyze — рекомендация по портфелю\n"
            "/analyze <тикер> — объяснить движение цены\n"
            "/set_language <code> — язык (en, de, zh, ru)"
        ),
        "help_dev_commands": (
            "Команды разработчика:\n"
            "/reload_config — перезагрузить config.json\n"
            "/debug_state — внутреннее состояние\n"
            "/add_user <chat_id> [role] [lang] — добавить пользователя\n"
            "/remove_user <chat_id> — удалить доступ\n"
            "/list_users — список пользователей"
        ),
        "menu_hint": (
            "Выберите действие в меню ниже.\n\n"
            "Примеры изменения портфеля:\n"
            "/add_ticker AAPL 5\n"
            "/remove_ticker MSFT"
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
        "portfolio_empty": "Портфель пуст. Добавьте позиции через /add_ticker.",
        "portfolio_header": "Портфель ({count} поз.)",
        "portfolio_shares": "{symbol} — {shares:g} акций",
        "portfolio_cost_basis": "  Средняя цена: {value:.2f}",
        "portfolio_price_unavailable": "  Цена: недоступна",
        "portfolio_last_price": "  Последняя цена: {price:.2f} ({change})",
        "portfolio_company": "  Компания: {name}",
        "portfolio_quote_as_of": "  Котировка на: {timestamp}",
        "portfolio_position_notes": "  Заметки: {notes}",
        "portfolio_notes_header": "Заметки по портфелю:",
        "portfolio_last_fetch": "Последнее обновление рынка: {timestamp}",
        "industries_empty": (
            "Отрасли не настроены.\n"
            "Добавьте focus_industries в config.json или тикеры в ticker_industries.json."
        ),
        "industries_header": "Отслеживаемые отрасли",
        "industries_line": "- {label}: {count} статей в кэше",
        "industries_total": "Всего новостей в кэше: {count}",
        "industries_updated": "Кэш новостей обновлён: {timestamp}",
        "analyze_header": "Анализ портфеля",
        "analyze_alerts_count": "Предупреждения по правилам ({count}):",
        "analyze_no_alerts": "Предупреждения по правилам: нет срабатываний.",
        "analyze_llm_disabled": "LLM-рекомендация: отключена (enable_llm_summaries в config.json).",
        "analyze_llm_empty": "LLM-рекомендация: включена, но результат не получен.",
        "analyze_llm_header": "LLM-рекомендация ({source}, {urgency}):",
        "analyze_suggested": "Рекомендуемые действия: {actions}",
        "analyze_llm_note": "Примечание LLM: {note}",
        "ticker_header": "Анализ: {symbol}",
        "ticker_no_price": "Нет кэшированной цены. Дождитесь обновления рынка и повторите.",
        "ticker_company": "Компания: {name}",
        "ticker_last_price": "Последняя цена: {price:.2f} ({change}) за {window}",
        "ticker_sector": "Сектор: {sector}",
        "ticker_llm_disabled": "LLM-объяснение: отключено (enable_llm_summaries в config.json).",
        "ticker_llm_empty": "LLM-объяснение: недоступно.",
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
