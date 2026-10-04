# AGENTS.md — навигатор по репозиторию Pikabu MCP

> Тонкий роутер: минимум всегда нужного + ссылки на детальные доки в `docs/`.
> Не распухать — детали пиши в `docs/*.md`, здесь только одна строка-указатель.

**Что это**: Vue 3 SPA + FastAPI-бэкенд, который заодно является MCP-сервером (Streamable HTTP).
Парсит `pikabu.ru/best` в SQLite, отдаёт данные MCP-тулами, ведёт чат (DeepSeek, function calling)
и RAG-чат по `pikabu-txt.md` с памятью задачи и выводом источников.

## Окружение и команды (Windows)

- Python — только `.venv\Scripts\python.exe` (или `py -3`). **`python` в PATH — заглушка MS Store.**
- Node.js 18+. Для скриншотов нужен системный Chrome.

```powershell
# бэкенд (из server/)
..\.venv\Scripts\python.exe -m app.main
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -c "import app.main"        # импорт-чек (линтера нет)

# клиент (из client/)
npm run dev        # :5173, проксирует /api и /mcp на :8000
npm run build      # vue-tsc (typecheck) + vite build -> client/dist
```

Проверка MCP: `GET /api/status` → `mcp.connected: true`.

## Критично (ломается чаще всего)

- **`config.json` кэшируется** (`lru_cache` на `get_settings()`) — правки конфига только после рестарта.
- **Зависший старт / `ConnectionReset`** — старый процесс на `:8000`:
  `Get-NetTCPConnection -LocalPort 8000 -State Listen` → `Stop-Process -Id <PID> -Force`.
- **TS держать на `^5`** — `typescript` 7.x ломает `vue-tsc` (`ERR_PACKAGE_PATH_NOT_EXPORTED`).
- Прочее (фоновые процессы, cp1251-консоль, MCP SDK v2, anyio) — [docs/GOTCHAS.md](docs/GOTCHAS.md).

## Безопасность (обязательно)

- Никогда не логировать и не отдавать в API `DEEPSEEK_API_KEY`; `.env` не коммитить.
- Внешние URL — только домены `pikabu.ru` (SSRF); для скриншотов — `allowed_screenshot_hosts`,
  аргументы с путями файлов из вызовов модели вырезаются.
- Команды внешних MCP-серверов — только из `config.json` (из UI — вкл/выкл по имени).
- Файлы саммари — только в `summaries_dir` с генерируемым сервером именем.
- SQL — только параметризованный. CORS ограничен `CORS_ORIGINS`.

## Карта документации (что читать под задачу)

| Задача | Читать |
| --- | --- |
| Понять проект целиком, инварианты, потоки данных | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Изменить логику сервера, найти модуль/функцию | [docs/BACKEND.md](docs/BACKEND.md) |
| Изменить Vue-клиент, компоненты, стор | [docs/CLIENT.md](docs/CLIENT.md) |
| Добавить/изменить REST-эндпоинт или MCP | [docs/API.md](docs/API.md) |
| RAG, источники, память задачи | [docs/RAG.md](docs/RAG.md) |
| Проверить изменения, поднять сервер, сценарии | [docs/TESTING.md](docs/TESTING.md) |
| «Странное» поведение, ошибки окружения | [docs/GOTCHAS.md](docs/GOTCHAS.md) |
| Рецепты: добавить тул/эндпоинт/поле/промпт/стратегию | [docs/RECIPES.md](docs/RECIPES.md) |
| Человекочитаемое описание и быстрый старт | [README.md](README.md) |

Готовые процедуры — скиллы opencode `pikabu-e2e` и `pikabu-chat-live-test` в `.opencode/skills/`
(подключаются через skill-tool). Контракт проверок — [docs/TESTING.md](docs/TESTING.md).

## Git

- Коммить по завершении логической единицы работы, осмысленным сообщением.
- Не коммитить `.env`, `node_modules`, `.venv`, `server/data`, `client/dist`.
- **Push — только по явной просьбе пользователя и в указанную им ветку.** В репозитории `main` +
  ветки-«дни» вида `dayNN`; локальный `main` может опережать `origin/main` — это норма.
