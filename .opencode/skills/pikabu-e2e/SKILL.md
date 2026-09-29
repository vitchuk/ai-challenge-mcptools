---
name: pikabu-e2e
description: "Smoke/e2e проверка Pikabu MCP-сервера: фоновый запуск и остановка сервера на Windows, проверки REST API (/api/status, /api/tools, /api/articles), включение/выключение внешнего MCP-сервера playwright, clear-data и run-now, смоук MCP-эндпоинта /mcp. Use when verifying server changes (verify, e2e, smoke, проверка сервера, поднять/остановить сервер). Не использовать для правки кода приложения."
---

# Pikabu E2E-проверка

Поднимает сервер, прогоняет smoke-проверки REST API и MCP-эндпоинта, останавливает сервер.
Все ожидаемые значения — из `AGENTS.md → Тестирование изменений`.

## Быстрый путь

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe .opencode\skills\pikabu-e2e\scripts\e2e_api.py
```

Скрипт самодостаточен:
- освобождает порт :8000 (убивает висящий процесс, если есть);
- стартует `python -m app.main` из `server/` в фоне (логи — во временный файл);
- ждёт готовности `/api/status`, печатает `[OK]`/`[FAIL]` по каждому пункту;
- при провале печатает хвост лога сервера;
- в конце убивает сервер; код выхода `1`, если есть провалы.

Предусловия: Windows, venv, Node.js (npx для playwright). Chrome для скриншотов здесь **не нужен** — проверяется только подключение.

## Что проверяется

1. `/api/status`: `mcp.connected=true`, `mcp.tools_count=28`.
2. `playwright` подключён (`servers[].connected`; холодный `npx` — до ~1 мин).
3. `/api/tools`: 30 тулов = 28 встроенных + 2 `playwright__*`.
4. `disable`/`enable` playwright → 28 ↔ 30, `connected` возвращается.
5. `/api/articles` — есть `count` и `articles`.
6. `clear-data` — поля `cleared_articles`/`cleared_summaries`/`cleared_mcp_outputs`, затем `articles_count=0` и `summary/latest.exists=false`.
7. `run-now` — `ok=true` и статьи в БД (`new` может быть 0, если лента не менялась — это не ошибка).
8. MCP `/mcp` — `initialize`, `tools/list` (28), `call_tool get_saved_articles`.

## Ручной путь (частичный прогон)

```powershell
# 1) освободить порт (частая причина «зависшего» старта / ConnectionReset)
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }

# 2) запустить сервер в фоне (из папки server)
$proc = Start-Process -FilePath "..\.venv\Scripts\python.exe" -ArgumentList "-m","app.main" `
  -WorkingDirectory (Get-Location) -PassThru -RedirectStandardOutput "$env:TEMP\pikabu.out.log" `
  -RedirectStandardError "$env:TEMP\pikabu.err.log"

# 3) ждать /api/status (темы + playwright, ~5-15 с), затем проверять эндпоинты
Invoke-RestMethod http://127.0.0.1:8000/api/status
Invoke-RestMethod http://127.0.0.1:8000/api/tools

# 4) остановить
Stop-Process -Id $proc.Id -Force
```

## Грабли

- Висящий процесс на :8000 → «висит» старт или `ConnectionReset` по API (см. ручной шаг 1).
- `playwright` иногда не подключается с первого раза (застрявший холодный старт браузера/осиротевшие
  headless-Chrome). Скрипт сам делает `disable/enable` и ждёт ещё, а перед стартом гасит только
  осиротевшие Chrome нашего MCP-профиля (по `ms-playwright` в командной строке) — пользовательский Chrome не трогает.
- `config.json` кэшируется (`lru_cache`) — правки конфига действуют только после рестарта сервера.
- MCP SDK v2: поля моделей snake_case (`input_schema`, `is_error`, `server_info`); `streamable_http_client` отдаёт 2-tuple `(read, write)`.
- Подробнее — `AGENTS.md` (разделы «Грабли», «Тестирование изменений»).
