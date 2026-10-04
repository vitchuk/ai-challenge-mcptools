# Архитектура

> **TL;DR**: Vue 3 SPA + FastAPI-бэкенд, который заодно является MCP-сервером (Streamable HTTP).
> Бэкенд парсит pikabu.ru в SQLite, отдаёт данные MCP-тулами, ведёт чат через DeepSeek
> (function calling) и RAG-чат по `pikabu-txt.md`. Внешние MCP-серверы (Playwright) — для скриншотов.

## Компоненты

```
[Vue 3 + Vite + TS + Tailwind]  --REST/JSON-->  [FastAPI :8000]
      вкладка «Чат»                               /api/*        — чат, статус, статьи, RAG, парсинг
      вкладка «MCP»                               /mcp          — MCP-сервер (Streamable HTTP, SDK v2)
                                                  LLM-агент     — DeepSeek + вызовы тулов
                                                  RAG           — rag.py + rag_pipeline.py + task_state.py
                                                  Scheduler     — APScheduler, парсинг каждые X мин
                                                  Parser        — httpx + BeautifulSoup → SQLite
                                                  MCPManager    — внешние MCP-серверы (stdio)
                                                  client/dist   — статика (один порт в prod)
```

## Четыре потока данных

### 1. Агентский чат (`POST /api/chat` без `rag_strategy`)
`chat.run_chat` → системный промпт + история из SQLite → цикл DeepSeek `tool_choice=auto`
(до `chat_max_iterations`) → `route_tool_call` (префикс `server__tool` → внешний MCP, иначе `tools.REGISTRY`)
→ ответ. Тулы выполняются **в процессе**, не по HTTP к `/mcp`. История и ответ сохраняются в SQLite.

> Каждая сессия (`session_id`) — **отдельный чат** с собственным заголовком (первый вопрос) и памятью
> задачи; список — `GET /api/chats`, удаление — `POST /api/chats/{id}/delete` (`chat_store.delete_chat`).

### 2. RAG-чат (`POST /api/chat` с `rag_strategy`)
`chat._run_rag_chat` → `task_state.update_state` (память задачи) → `rag.build_rag_reply`
(поиск чанков + промпт с контекстом/памятью) → ответ с `chunks`/`debug`/`task_state`.
Детали — [RAG.md](RAG.md).

### 3. Парсинг + автосаммари
APScheduler (`scheduler.py`) каждые `parse_interval_minutes` → `parser.fetch_best` (отбрасывает посты
старше `max_post_age_hours`) → `db.upsert_articles` + `db.trim_to_max` → `_auto_summary` пишет
**плоский** `summary_auto_<ts>.json`. Ошибки LLM не ломают парсинг (`parsing.last_summary_error`).

### 4. Внешние MCP-серверы + скриншоты
`mcp_manager` держит stdio-сессию каждого сервера из `config.json → external_mcp_servers` в своей
asyncio-задаче. Тулы видны агенту как `server__tool`, фильтруются `tools_filter`. Файлы
`screenshot_tools` переносятся в текущую папку саммари (`tools.current_summary_dir()`); base64 в
контекст LLM не попадают. Вкл/выкл из UI — состояние в `server/data/mcp_servers_state.json`.

## Инварианты (ломаются легко — соблюдай)

- **Единый реестр тулов** — `server/app/tools.py` (`REGISTRY`). Из него берутся и MCP-регистрация
  (`mcp_server.register_tools`), и схемы для LLM (`tools.openai_tools_schema`). Новый тул — только в
  `tools.py`; дублировать описания не нужно.
- **`mcp_manager` не импортирует `tools`** — иначе циклы импортов. Маршрутизация вызовов — в
  `chat.route_tool_call` (не в `mcp_manager`).
- **Папки саммари — только для чата**: `summarize_best_posts` создаёт
  `summaries/summary_<ГГГГММДД_ЧЧММСС>/` с `summary.json` и становится маршрутом скриншотов
  (`current_summary_dir()`). Автосаммари парсера пишет **плоский** `summary_auto_<ts>.json` и папку
  НЕ создаёт (иначе на «саммари+скриншоты» получаются дубли папок). `save_summary` — в текущую папку.
  `clear_summaries` удаляет `summary_*`; `/api/summary/latest` сравнивает папки и плоские файлы по ts.
- **Саммаризация переиспользуется**: `tools._summarize_articles(articles, folder=...)` вызывают и
  тулы (folder=True), и планировщик (folder=False).
- **MCP SDK v2**: класс `mcp.server.mcpserver.MCPServer` (в v1 — `FastMCP`). Не импортировать
  `mcp.server.fastmcp` — в v2 бросает ошибку. Поля моделей — snake_case (`input_schema`, `is_error`,
  `server_info`). Роут `/mcp` добавляется в `main.create_app()`.
- **`chat_max_iterations: 16`** — цепочке «саммари + navigate + screenshot на каждый пост» нужен запас
  (при 5 сценарий обрезается).
- **`/best` — уже «лучшее за сегодня»**; `parser.fetch_best` дополнительно отбрасывает старое.
- **Очистка данных** (`POST /api/parsing/clear-data`) = `db.clear_articles` + `tools.clear_summaries`
  + `mcp_manager.clear_output_dirs` + `scheduler.reset_parse_stats`. Клиент синхронизирует вкладки
  через стор (`dataVersion`, `posts`, `summaryVersion`).
- **Статус парсинга и посты — на вкладке «MCP»** (левая колонка): живой отсчёт до
  `parsing.next_run_at`, спиннер «выполняется парсинг», карточки при `articles_count > 0`. Вкладка не
  триггерит парсинг — только опрашивает `/api/status`. Посты грузит `McpView` в общий стор `posts`;
  вкладка «Чат» читает их для встроенных карточек в ответах.
- **Абсолютные пути** (`database_path`, `summaries_dir`) резолвятся от корня проекта в `config.py`.
- **Секреты** — только `.env`; конфиг сервера — `server/config.json`.

## Соглашения по коду

- Python: async/await, `from __future__ import annotations`, логирование через `logging`, ошибки
  парсинга — `parser.ParserError`, LLM — `deepseek.LLMError`.
- Тулы возвращают **строку с JSON** (`json.dumps(..., ensure_ascii=False)`), не бросают исключения наружу.
- Vue: Composition API `<script setup lang="ts">`, только утилитарные классы Tailwind (без css-файлов,
  кроме `src/style.css`).
- Комментарии — на русском, только по делу.

## Связанные доки

[BACKEND.md](BACKEND.md) · [CLIENT.md](CLIENT.md) · [API.md](API.md) · [RAG.md](RAG.md) ·
[TESTING.md](TESTING.md) · [GOTCHAS.md](GOTCHAS.md) · [RECIPES.md](RECIPES.md)
