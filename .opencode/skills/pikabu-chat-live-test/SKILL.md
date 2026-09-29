---
name: pikabu-chat-live-test
description: "Живой тест чат-агента Pikabu MCP (DeepSeek + Playwright): сценарий «сделай саммари N постов и их скриншоты», проверка цепочки тулов и структуры папок саммари (ровно одна summary_*/ с summary.json и PNG, плоский summary_auto_*.json). Требует DEEPSEEK_API_KEY в .env и Chrome. Use when testing the chat agent / live LLM scenario (живой чат, саммари со скриншотами, chat test)."
---

# Живой тест чат-агента: саммари + скриншоты

Проверяет end-to-end: парсинг → чат «саммари N постов со скриншотами» → папка саммари со скриншотами.

## Быстрый путь

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe .opencode\skills\pikabu-chat-live-test\scripts\chat_scenario.py
```

Скрипт самодостаточен: освобождает :8000, стартует сервер в фоне, ждёт готовности и подключения `playwright`,
делает `clear-data` + `run-now` (детерминированные данные), шлёт сообщение в чат и проверяет результат.
Без `DEEPSEEK_API_KEY` печатает `SKIP` (код 0) — ключ при этом не читается в вывод.

## Предусловия

- `DEEPSEEK_API_KEY` в `.env` (иначе — SKIP).
- Системный Google Chrome (Playwright MCP использует канал `chrome`).
- `npx` (Node.js); первый холодный запуск playwright MCP — до ~1 минуты.

## Что проверяется

1. Сервер стартует, `playwright` подключается.
2. `clear-data` → пустая БД; `run-now` → статьи в БД + плоский `summary_auto_*.json`.
3. `POST /api/chat` с текстом «Сделай саммари 2 последних постов и их скриншоты».
4. Цепочка `tool_calls` содержит `summarize_best_posts` и `playwright__browser_take_screenshot`.
5. В `server/data/summaries/` — **ровно одна** папка `summary_*/` (парсинг/автосаммари в неё не мешаются),
   внутри `summary.json` и PNG-скриншоты (ожидается 2, допускается отклонение LLM — проверяется `>=1`).
6. Плоские файлы в `summaries/` — только `summary_auto_*.json`.
7. `/api/summary/latest` указывает на папку из п.5, `parsing.last_summary_error` пуст.

## Внимание

Скрипт **удаляет данные** (`clear-data`) и парсит заново — это часть проверки.
Сервер поднимается и гасится скриптом; если на :8000 висит другой процесс, он будет остановлен.
