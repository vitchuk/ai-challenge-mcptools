# Грабли (Windows / окружение / процессы)

> **TL;DR**: Читай перед отладкой «странного» поведения. Самые частые: заглушка `python` из
> Microsoft Store, закэшированный `config.json`, висящий процесс на `:8000`, тяжёлые юникод-принты
> в cp1251-консоли и «умирающие» фоновые процессы.

## Python / окружение

- **`python` в PATH — заглушка Microsoft Store** (ничего не делает). Всегда используй
  `.venv\Scripts\python.exe` (или `py -3`).
- **`config.json` кэшируется** (`lru_cache` на `get_settings()` в `config.py`) — правки конфига
  вступают в силу **только после рестарта сервера**.
- Нет отдельного Python-линтера. Контракт: код импортируется без ошибок
  (`.venv\Scripts\python.exe -c "import app.main"` из `server`).
- Node.js 18+ (проверено на 26) — нужен и для клиента, и для `npx @playwright/mcp`.
- Для скриншотов нужен системный Google Chrome (Playwright MCP использует канал `chrome`).

## Порт и процессы

- **Зависший старт / `ConnectionReset` по API** — обычно на `:8000` остался старый процесс:
  `Get-NetTCPConnection -LocalPort 8000 -State Listen` → `Stop-Process -Id <PID> -Force`.
- **Фоновые процессы не переживают завершение команды оболочки** (и гибнут при таймауте команды).
  Не рассчитывай, что сервер, запущенный `Start-Process` в одной команде, будет жив в следующей.
  Для долгих прогонов поднимай и гаси сервер **внутри одного процесса/скрипта** (образец —
  `scripts/run_chat_scenarios.py`: `subprocess.Popen` + `taskkill /F /T` в `finally`).
- `.venv\Scripts\python.exe` на Windows — это запускающий шим: PID от `Start-Process` может не
  совпадать с реальным PID процесса (`Started server process [N]` в логе). Убивай дерево
  (`taskkill /F /T`), а не только шим.
- `playwright` при первом запуске скачивается через `npx` (~1 мин); подключение может занять время
  после `Application startup complete`.

## Консоль / вывод

- **Консоль Windows обычно cp1251** — `print("✅")`/кириллица в неожиданной кодировке роняют скрипт
  `UnicodeEncodeError: 'charmap' codec can't encode character`. В скриптах: либо ASCII-маркеры
  (`OK`/`FAIL`), либо `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` в начале.
  Файлы всегда пиши с `encoding="utf-8"`.

## MCP / SDK

- **SDK v2**: класс `mcp.server.mcpserver.MCPServer` (в v1 — `FastMCP`). Не импортируй
  `mcp.server.fastmcp` — в v2 бросает ошибку. Поля моделей — **snake_case** (`input_schema`,
  `is_error`, `server_info`).
- Сессия внешнего MCP-сервера — в своей asyncio-задаче; вход/выход из контекстных менеджеров
  происходят в **одной и той же задаче** (требование anyio). Не переноси это в чужую задачу.
- `mcp_manager` **не должен импортировать `tools`** — циклы импортов. Роутинг вызовов — в
  `chat.route_tool_call`.

## Клиент

- **Не поднимать `typescript` до 7.x** — vue-tsc 3.x падает
  (`ERR_PACKAGE_PATH_NOT_EXPORTED './lib/tsc'`); в `package.json` зафиксирован `^5`.
- Typecheck клиента = `npm run build` (в `.opencode` skills/README упоминается `npm run build`).
- Dev-режим проксирует `/api` и `/mcp` на `:8000` (`client/vite.config.ts`); в prod FastAPI раздаёт
  `client/dist` (если папки нет — лог «client/dist не найден», фронт через Vite).

## Данные / безопасность

- `server/data/` — gitignored (SQLite, саммари, RAG-индексы, `mcp_output`, логи).
- `.env` не коммитить; секреты только там. Никогда не логировать/не отдавать `DEEPSEEK_API_KEY`.
- SQL — только параметризованный. Внешние URL — только `pikabu.ru` (SSRF).
- Без `DEEPSEEK_API_KEY` чат возвращает `llm_not_configured` (интерфейс и парсинг работают).
- RAG без собранного индекса → `rag_error`; без ollama → ошибка эмбеддингов при `build`/поиске.
