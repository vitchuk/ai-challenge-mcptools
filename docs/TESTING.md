# Тестирование изменений

> **TL;DR**: Готовые процедуры — скиллы opencode `pikabu-e2e` (smoke REST/MCP) и
> `pikabu-chat-live-test` (живой чат). Контракт проверок — чеклист ниже. Для живого чата нужен
> `DEEPSEEK_API_KEY`; для RAG — собранный индекс и ollama. Python-линтера нет — код должен
> импортироваться (`.venv\Scripts\python.exe -c "import app.main"` из `server`).

## Быстрые команды

```powershell
# typecheck + сборка клиента
cd client; npm run build

# импорт-чек сервера
cd server; ..\.venv\Scripts\python.exe -c "import app.main; print('OK')"

# RAG-индекс (нужен ollama)
cd server; ..\.venv\Scripts\python.exe -m app.rag build

# проверочные сценарии RAG (сервер поднимается/гасится скриптом)
.\.venv\Scripts\python.exe scripts\run_chat_scenarios.py
```

## Скиллы (загружаются через skill-tool)

- **`pikabu-e2e`** — фоновый запуск/остановка сервера, smoke REST (`/api/status`, `/api/tools`,
  `/api/articles`), disable/enable playwright, clear-data, run-now, smoke `/mcp`. Запуск:
  `.\.venv\Scripts\python.exe .opencode\skills\pikabu-e2e\scripts\e2e_api.py`.
- **`pikabu-chat-live-test`** — живой сценарий «саммари N постов + скриншоты», проверка цепочки
  тулов и структуры папок `summaries/summary_*` (одна папка + PNG, плоский `summary_auto_*.json`).

## Фоновый запуск сервера вручную (Windows)

```powershell
# 1) освободить порт (частая причина «зависшего» старта / ConnectionReset)
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }

# 2) запустить из папки server
$proc = Start-Process -FilePath "..\.venv\Scripts\python.exe" -ArgumentList "-m","app.main" `
  -WorkingDirectory (Get-Location) -PassThru -RedirectStandardOutput "$env:TEMP\pikabu.out.log" `
  -RedirectStandardError "$env:TEMP\pikabu.err.log"

# 3) ждать /api/status, затем проверять; 4) остановить
Stop-Process -Id $proc.Id -Force
```

> Фоновые процессы, запущенные внутри одной команды оболочки, могут не пережить её завершение.
> Для долгих прогонов управляй сервером из того же процесса/скрипта (как `run_chat_scenarios.py`,
> который сам стартует сервер сабпроцессом и гасит его в `finally`).

## Чеклист (контракт проверок)

1. `GET /api/status`, `/api/tools`, `/api/articles` отвечают, `mcp.connected: true`, `tools_count: 28`.
2. `POST /api/parsing/run-now` — сохраняется 8 постов; `new` может быть 0, если лента не менялась (не ошибка).
3. При наличии `DEEPSEEK_API_KEY` после парсинга в `server/data/summaries/` появляется **плоский**
   `summary_auto_<ts>.json` (не папка!), в `/api/status` — `parsing.last_summary_file`; на вкладке
   «MCP» в блоке «Саммари» — его содержимое.
4. Кнопки/эндпоинты start/stop отражаются в `parsing.running`.
5. `POST /api/parsing/clear-data` обнуляет `articles_count`, `summary/latest` → `exists:false`,
   сбрасывает `last_summary_file`/`last_parsed_count`, чистит `mcp_output` (`cleared_mcp_outputs`);
   на вкладке «MCP» в левой колонке — заглушка с таймером, блок «Саммари» скрывается.
6. `playwright` в `/api/status → servers` → `connected:true` после старта (npx холодный старт ~1 мин);
   `disable` убирает `playwright__*` из `/api/tools` (30→28), `enable` возвращает; состояние переживает рестарт.
7. Сценарий «саммари + скриншоты» (живой чат): `summarize_best_posts` →
   `playwright__browser_navigate`/`browser_take_screenshot`; в `summaries/summary_*` — `summary.json` + PNG,
   папка за запрос ровно одна.
8. MCP: клиент к `/mcp` — `initialize`, `tools/list`, `call_tool`.
9. Клиент: `npm run build` без ошибок типизации; `/tools` в чате — 28 встроенных + тулы внешних серверов.
10. RAG-чат: после `python -m app.rag build` и при запущенном ollama — ответ с `chunks`, в тексте
    «Источники:»/цитаты; `GET /api/chat/history` возвращает сообщения и `task_state`; при отсутствии
    релевантных фрагментов — «Источники: не найдены». Тест-вопросы — в [RAG.md](RAG.md).
11. Чаты: новое сообщение создаёт чат (`chat_id`/`chat_title` в ответе, заголовок = первый вопрос),
    `GET /api/chats` показывает его с числом сообщений; переключение в списке восстанавливает историю
    (`GET /api/chat/history?session_id=`); удаление (`POST /api/chats/{id}/delete`) убирает чат из
    списка и очищает историю/память задачи; старые сессии из БД подхватываются бэкфиллом.

## Полезно

- Грабли и решения — [GOTCHAS.md](GOTCHAS.md).
- Проверка типов клиента = `npm run build` (включает `vue-tsc --noEmit`).
