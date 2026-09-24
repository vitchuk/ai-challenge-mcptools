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
- MCP-сервер — `mcp.server.mcpserver.MCPServer` (это MCP SDK **v2**; в v1 класс
  назывался `FastMCP`). Не импортируйте `mcp.server.fastmcp` — в v2 он выбрасывает
  ошибку. Роут `/mcp` добавляется в FastAPI в `main.create_app()`.
- Чат-агент выполняет тулы **в процессе** (`tools.call_tool`), а не по HTTP.
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
- Все внешние URL фиксированы на домены `pikabu.ru` (защита от SSRF).
- Файлы саммари создаются только в `summaries_dir` с генерируемым сервером именем.
- SQL — только параметризованный.
- CORS ограничен `CORS_ORIGINS`.

## Тестирование изменений

1. Запустить сервер и проверить `GET /api/status`, `/api/tools`, `/api/articles`.
2. `POST /api/parsing/run-now` — в БД должно появиться 8 новых постов.
3. Кнопки/эндпоинты start/stop отражаются в `parsing.running`.
4. MCP: подключиться клиентом к `/mcp`, вызвать `list_tools` и `call_tool`.
5. Клиент: `npm run build` без ошибок типизации; чат `/tools` показывает 28 тулов.
6. Для живого чата нужен `DEEPSEEK_API_KEY` в `.env` (без него возвращается
   понятная ошибка `llm_not_configured`).

## Git

- Коммитить по завершении логической единицы работы, осмысленным сообщением.
- Не коммитить `.env`, `node_modules`, `.venv`, `server/data`, `client/dist`.
