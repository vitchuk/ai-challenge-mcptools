# Бэкенд (server/)

> **TL;DR**: FastAPI-приложение в `server/app/`. Точка входа — `main.py` (собирает FastAPI,
> монтирует `/api` и `/mcp`, раздаёт `client/dist`). Бизнес-логика — в отдельных модулях,
> связанных через `config.get_settings()`. Запуск: из папки `server` → `..\.venv\Scripts\python.exe -m app.main`.

## Карта модулей `server/app/`

### `main.py`
Сборка приложения. `lifespan`: `db.init_db()` → `chat_store.init_tables()` → `load_themes()` →
`mcp_server.register_tools(themes)` → `mcp_manager.manager.configure/startup()` →
`session_manager.run()` → `scheduler.start_scheduler()` (если `autostart_parsing`).
`create_app()`: CORS из `cors_origins`, роутер `/api`, маршруты MCP, статика `client/dist`.

### `config.py`
Загрузка `.env` + `server/config.json`. **`get_settings()` кэширован (`lru_cache`)** — правки конфига
видны только после рестарта. `RagSettings` и `Settings.public_config()` (без секретов — отдаётся в UI).
Абсолютные пути резолвятся от корня проекта. Не логировать `deepseek_api_key`.

### `api.py`
Все REST-эндпоинты (router с префиксом `/api`). Pydantic-модели `ChatRequest`, `RagOptionsPayload`.
Полный список — см. [API.md](API.md). Добавляя эндпоинт, сначала проверь, нет ли подходящей функции
в модуле-владельце.

### `db.py`
SQLite (статьи). Схема `articles`, `init_db`, `upsert_articles`, `trim_to_max`, `get_articles`,
`get_articles_for_summary`, `count_articles`, `get_story_ids`, `clear_articles`, `last_parsed_at`.
Только параметризованный SQL. WAL-режим. Паттерн: `with _lock, _connect() as conn`.

### `chat_store.py`
SQLite (чаты): таблицы `chats` (заголовок = первый вопрос, created/updated), `chat_messages`,
`chat_task_states`. `init_tables` (+ бэкфилл метаданных для старых сессий), `append_message`
(создаёт чат и заголовок при первом сообщении), `load_history`, `list_chats` (свежие сверху,
с `messages_count`), `get_chat`, `save_task_state`, `load_task_state`, `delete_chat` (удаляет чат
целиком), `count_messages`. Использует ту же БД, что `db.py`.

### `parser.py`
`fetch_best()` — парсит `/best` (8 постов, реклама отбрасывается), фильтр `max_post_age_hours`;
`fetch_theme(slug)` — посты темы. `ParserError`. Только домены `pikabu.ru` (SSRF).

### `themes.py`
`load_themes()` — список тем с `pikabu_themes_url` + имена тулов `get_theme_<slug>`.

### `scheduler.py`
APScheduler: интервальный парсинг, `start_scheduler`/`stop_scheduler`/`parse_now`, `reset_parse_stats`,
`_auto_summary` (пишет плоский `summary_auto_*.json`), `status()` (для `/api/status → parsing`).

### `tools.py`
**`REGISTRY`** — единый реестр MCP-тулов + `openai_tools_schema()` (схемы для LLM) + `tools_info()`.
`call_tool(name, arguments)` — диспетчер. Саммари: `_summarize_articles`, `summarize_articles`,
`summarize_best_posts`, `save_summary`, `get_latest_summary`, `clear_summaries`,
`current_summary_dir()` (текущая папка для скриншотов). Встроенные тулы: `get_saved_articles`,
`summarize_best_posts`, `save_summary`, `start_parsing_pikabu`, `stop_parsing_pikabu`, `get_theme_*`.

### `mcp_server.py`
Встроенный MCP-сервер: `MCPServer` (SDK **v2**), `register_tools(themes)` (из `REGISTRY`),
`build_app()` (Streamable HTTP). Не импортировать `mcp.server.fastmcp`.

### `mcp_manager.py`
Внешние MCP-серверы (stdio). `manager.configure(servers)`, `startup`/`shutdown`, `status`,
`set_enabled`, `call_external`, `external_tools_schema`/`external_tools_info`, `clear_output_dirs`,
`screenshot_flow_hint`, `SEPARATOR = "__"`. Сессия в своей asyncio-задаче (anyio: вход/выход из
контекстных менеджеров — в одной задаче). **Не импортирует `tools`.**

### `llm.py`
Провайдеры LLM (OpenAI-совместимые): `deepseek` и локальный `ollama` (`{ollama_base_url}/v1`).
`normalize_provider`, `is_configured`, `chat_model`, `get_client(provider)`, `check_ollama_available`.
`complete(...)` — один вызов (без стрима), возвращает `{content, reasoning, tool_calls}` и логирует в
`llm_log`. `stream_complete(...)` — стрим (async-генератор дельт `reasoning`/`content` + финальный
`done`), тоже логирует. `complete_messages`/`complete_text` — обёртки над `complete` (phase `aux`/`rag`).
`LLMError`/`LLMNotConfigured`. Для DeepSeek без `DEEPSEEK_API_KEY` — ошибка `llm_not_configured`.

### `llm_log.py`
Кольцевой буфер LLM-вызовов **в памяти** (последние 200, не персистится) для вкладки LOG.
`log_call` (контекст запроса + ответ + `duration_ms`/`error`), `recent(limit)` (свежие сверху), `clear`.

### `chat.py`
`run_chat(session_id, message, rag_strategy, rag_options, llm_provider)` — главный вход чата (без стрима).
`run_chat_stream(...)` — async-генератор SSE-событий (`thinking`/`tool`/`reply`) для веб-клиента.
`_run_agent_chat_stream` (агентный цикл через `llm.stream_complete`), `_run_rag_chat_stream`
(стрим финальной генерации RAG). `_run_rag_chat`, `route_tool_call`, `_system_prompt`, `all_tools_schema`,
rate limit, `reset_session` (удаляет чат), `list_chats`, `load_session`. `llm_provider` (`deepseek`/`ollama`)
выбирает модель для генерации ответа; служебные LLM-вызовы остаются на DeepSeek. `elapsed_ms` — полное
время обработки. История — через `chat_store`. Возвращает `{reply, tool_calls, chunks?, debug?,
task_state?, chat_id, chat_title, reasoning?, elapsed_ms?, error?}`.

### `rag.py`
RAG: парсинг `pikabu-txt.md`, чанкинг (`fixed`/`paragraph`, `CHUNKERS`), эмбеддинги ollama
(`embed_texts`), индексы (`build_index`, `load_index`, `list_indexes`), `search`, `RAG_SYSTEM_PROMPT`,
`build_rag_reply(message, strategy, history, options, task_state_data, provider)` и
`build_rag_reply_stream(...)` (деривация `reasoning` + финальный `done`). CLI: `python -m app.rag build|list|search`.
Детали — [RAG.md](RAG.md).

### `rag_pipeline.py`
`RetrievalOptions`, `RETRIEVAL_STRATEGIES` (baseline / query-rewrite / similarity-filter /
query-rewrite-rerank), `rewrite_query`, `rerank_candidates`, `run_retrieval`. Не импортирует `rag.py`
(ретривер передаётся callable).

### `task_state.py`
Память задачи: `empty_state`, `update_state` (LLM-экстрактор JSON + rule-based fallback),
`normalize_state`, `format_for_prompt`. Структура `{goal, clarifications, constraints, updated_at}`.

## scripts/

- `scripts/run_chat_scenarios.py` — прогон 2 проверочных сценариев (сам поднимает/гасит сервер),
  транскрипты в `docs/scenarios/`. Запуск из корня: `.\.venv\Scripts\python.exe scripts\run_chat_scenarios.py`.

## Данные (server/data/, gitignored)

`pikabu.db` (статьи + чат) · `summaries/` (`summary_*/` из чата, `summary_auto_*.json`) ·
`rag/<strategy>/index.json` · `mcp_output/` (скриншоты Playwright) · `mcp_servers_state.json` · `scenario_server.log`.
