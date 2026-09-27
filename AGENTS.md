# AGENTS.md

Руководство для AI-агентов и разработчиков по репозиторию **Pikabu MCP**.

## Что это

Веб-клиент (Vue 3 + Vite + TypeScript + Tailwind CSS) и бэкенд (Python/FastAPI),
который одновременно является **MCP-сервером** (Streamable HTTP, официальный SDK).
Сервер периодически парсит `https://pikabu.ru/best` в SQLite, отдаёт данные через
MCP-тулы и ведёт чат пользователя с LLM (DeepSeek) через function calling.

## Окружение (Windows)

- В проекте используется venv: `.venv\Scripts\python.exe`.
- **Важно:** команда `python` в PATH — заглушка Microsoft Store (не работает).
  Всегда используйте `.venv\Scripts\python.exe` или `py -3`.
- Node.js 18+ (проверено на 26).

## Команды

Бэкенд (из папки `server`):

```powershell
..\.venv\Scripts\python.exe -m app.main          # запуск сервера на HOST:PORT из .env
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Клиент (из папки `client`):

```powershell
npm install
npm run dev        # dev-сервер :5173 с проксированием /api и /mcp на :8000
npm run build      # vue-tsc (typecheck) + vite build -> client/dist
```

Typecheck клиента: `npm run build` (включает `vue-tsc --noEmit`).
Отдельного линтера Python в проекте нет; код должен импортироваться без ошибок
(`.venv\Scripts\python.exe -c "import app.main"` из `server`).

Проверка MCP: после старта сервера — `GET /api/status` (должно быть
`mcp.connected: true`, `tools_count: 28`) или подключение MCP-клиента к `/mcp`.

## Архитектурные правила

- **Единый реестр тулов** — `server/app/tools.py` (`REGISTRY`). Из него берутся
  и регистрация в MCP (`mcp_server.register_tools`), и схемы для LLM
  (`tools.openai_tools_schema`). Новый тул добавляется в `tools.py` и попадает
  сразу в оба места; дублировать описания не нужно.
- **Внешние MCP-серверы** — `server/app/mcp_manager.py` (stdio, описаны в
  `config.json → external_mcp_servers`). Сессия каждого сервера живёт в своей
  asyncio-задаче (стоп — через `asyncio.Event`; выход из контекстных менеджеров
  происходит в той же задаче, что их открыла — требование anyio). Тулы наружу:
  имя `server__tool`, показываются только из `tools_filter`; диспетчер чата —
  `chat.route_tool_call` (префикс → `mcp_manager.call_external`, иначе реестр),
  поэтому в одном диалоге агент последовательно вызывает тулы разных серверов.
  Файлы `screenshot_tools` после вызова переносятся из output-папки в текущую
  папку саммари (`tools.current_summary_dir()`); base64-картинки в ответы LLM не
  попадают. Состояние вкл/выкл — `server/data/mcp_servers_state.json` (gitignored).
  `mcp_manager` не должен импортировать `tools` (циклов не допускать).
- **Папки саммари**: `summarize_best_posts` и автосаммари парсера создают
  `summaries/summary_<ГГГГММДД_ЧЧММСС>/` с `summary.json`; `save_summary` и
  скриншоты Playwright кладутся туда же. `clear_summaries` удаляет папки и файлы;
  `/api/summary/latest` читает последний `summary_*/summary.json`.
- **Саммаризация переиспользуется**: `tools._summarize_articles`/`save_last_summary`
  вызываются и тулами (`summarize_best_posts`, `save_summary`), и планировщиком
  (`scheduler._auto_summary`) после каждого парсинга. Автосаммари пишет JSON в
  `summaries_dir` для новых story_id; ошибки LLM не ломают парсинг (пишутся в
  `parsing.last_summary_error`).
- Лента `/best` — это уже «лучшее за сегодня»; `parser.fetch_best` дополнительно
  отбрасывает посты старше `max_post_age_hours`.
- Очистка данных: `POST /api/parsing/clear-data` = `db.clear_articles` +
  `tools.clear_summaries` (папки/файлы `summary_*` + сброс `_last_summary`) +
  `mcp_manager.manager.clear_output_dirs()` (содержимое output-папок внешних
  серверов, сами папки остаются) + `scheduler.reset_parse_stats`. Клиент
  синхронизирует вкладки через общий стор `client/src/store.ts` (`dataVersion`):
  после очистки во вкладке «Чат» исчезают карточки и блок «Саммари», появляется
  заглушка с таймером.
- Вкладка «Чат» сама не триггерит парсинг: она показывает обратный отсчёт до
  `parsing.next_run_at` и вейтер «выполняется парсинг», опрашивая `/api/status`;
  карточки подгружаются, когда `articles_count > 0`.
- MCP-сервер — `mcp.server.mcpserver.MCPServer` (это MCP SDK **v2**; в v1 класс
  назывался `FastMCP`). Не импортируйте `mcp.server.fastmcp` — в v2 он выбрасывает
  ошибку. Роут `/mcp` добавляется в FastAPI в `main.create_app()`.
- Чат-агент выполняет тулы **в процессе**: встроенные — `tools.call_tool`, внешние —
  `mcp_manager.call_external` (роутинг по префиксу `server__tool` в `chat.route_tool_call`),
  а не по HTTP к `/mcp`.
- Конфиг сервера — `server/config.json`; секреты — только `.env`.
- Абсолютные пути (`database_path`, `summaries_dir`) резолвятся от корня проекта
  в `config.py`.
- Схема БД и обрезка до Y (`max_articles`) — `server/app/db.py`.

## Соглашения по коду

- Python: async/await, `from __future__ import annotations`, логирование через
  `logging`, ошибки парсинга — `parser.ParserError`, LLM — `deepseek.LLMError`.
- Тулы возвращают **строку с JSON** (`json.dumps(..., ensure_ascii=False)`), а не
  бросают исключения наружу.
- Vue: Composition API `<script setup lang="ts">`, стили — только утилитарные
  классы Tailwind (без отдельных css-файлов, кроме `src/style.css`).
- Комментарии — на русском; добавлять только по делу.

## Безопасность (обязательно)

- Никогда не логировать и не отдавать в API `DEEPSEEK_API_KEY`.
- `.env` не коммитить (он в `.gitignore`); коммитить только `.env.example`.
- Все внешние URL фиксированы на домены `pikabu.ru` (защита от SSRF). Для скриншотов
  внешних MCP-серверов действует `allowed_screenshot_hosts`; аргументы с путями файлов
  (`filename`/`path`) из вызовов модели вырезаются.
- Команды внешних MCP-серверов берутся только из `config.json`, из UI доступны лишь
  переключатели вкл/выкл по имени сервера (произвольные команды не принимаются).
- Файлы саммари создаются только в `summaries_dir` с генерируемым сервером именем.
- SQL — только параметризованный.
- CORS ограничен `CORS_ORIGINS`.

## Тестирование изменений

1. Запустить сервер и проверить `GET /api/status`, `/api/tools`, `/api/articles`.
2. `POST /api/parsing/run-now` — в БД должно появиться 8 новых постов.
3. При наличии `DEEPSEEK_API_KEY` после парсинга в `server/data/summaries/` должен
   появиться `summary_*.json`, а в `/api/status` — `parsing.last_summary_file`.
4. Кнопки/эндпоинты start/stop отражаются в `parsing.running`.
5. `POST /api/parsing/clear-data` обнуляет `articles_count`, `summary/latest`
   отдаёт `exists:false`, а `last_summary_file`/`last_parsed_count` сбрасываются;
   содержимое `mcp_output` тоже удаляется (`cleared_mcp_outputs` в ответе);
   во вкладке «Чат» появляется заглушка с таймером.
6. MCP-серверы: в `/api/status → servers` у `playwright` `connected:true` после
   старта (npx при первом запуске скачивается ~1 мин);
   `POST /api/mcp-servers/playwright/disable` убирает `playwright__*` из
   `/api/tools` (было 30 → 28), `enable` — возвращает; состояние переживает рестарт.
7. Сценарий «саммари + скриншоты» (живой чат): сообщение вида «Сделай саммари 2
   постов со скриншотами» → в `tool_calls` идут `summarize_best_posts` →
   `playwright__browser_navigate`/`playwright__browser_take_screenshot`, в папке
   `summaries/summary_*` появляются `summary.json` + PNG.
8. MCP: подключиться клиентом к `/mcp`, вызвать `list_tools` и `call_tool`.
9. Клиент: `npm run build` без ошибок типизации; чат `/tools` показывает 28
   встроенных тулов + тулы подключённых внешних серверов.
10. Для живого чата нужен `DEEPSEEK_API_KEY` в `.env` (без него возвращается
   понятная ошибка `llm_not_configured`).

## Git

- Коммитить по завершении логической единицы работы, осмысленным сообщением.
- Не коммитить `.env`, `node_modules`, `.venv`, `server/data`, `client/dist`.
