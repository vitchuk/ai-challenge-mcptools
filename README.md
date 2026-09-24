# Pikabu MCP

Веб-клиент с чатом на Vue 3 и MCP-сервер на Python: периодически парсит [pikabu.ru/best](https://pikabu.ru/best) в SQLite, отдаёт статьи через MCP-тулы и общается с пользователем через LLM (DeepSeek).

## Возможности

- **Вкладка «Чат»**: диалог с LLM (DeepSeek) с function calling. При загрузке выводятся все статьи из базы или заглушка «Еще не спарсили». Команда `/tools` показывает справку по всем тулам.
- **Вкладка «MCP»**: конфигурация сервера, статус подключения MCP, кнопки **Старт/Стоп** cron-парсинга, кнопка «Спарсить сейчас», статистика и список тулов.
- **Парсинг** `https://pikabu.ru/best` по расписанию (каждые X минут), хранение не более Y последних статей, удаление старых.
- **Тулы**: `get_saved_articles`, `get_theme_<тема>` (23 темы с https://pikabu.ru/themes), `summarize_best_posts`, `save_summary` (txt/json), `start_parsing_pikabu`, `stop_parsing_pikabu`.

## Архитектура

```
[Vue 3 + Vite + TS + Tailwind]  --REST/JSON-->  [FastAPI :8000]
        вкладка Чат                                 /api/*      — чат, статус, конфиг, статьи, старт/стоп
        вкладка MCP                                 /mcp        — MCP-сервер (Streamable HTTP)
                                                    LLM-агент   — DeepSeek + вызовы тулов
                                                    Scheduler   — APScheduler (интервал X мин)
                                                    Parser      — httpx + BeautifulSoup → SQLite
                                                    client/dist — статика (один порт в prod)
```

Сколько отдаёт сайт за один запрос: страница `/best` содержит 8 полноценных постов (плюс 2 рекламные вставки, которые парсер пропускает). Поэтому **N = 8**, значение задаётся в конфиге (`posts_per_fetch`).

## Требования

- Python 3.11+ (проверено на 3.14)
- Node.js 18+ (проверено на Node 26)

## Быстрый старт (локально)

### 1. Бэкенд

```powershell
# из корня проекта
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt

# настройки и API-ключ
Copy-Item .env.example .env
# откройте .env и вставьте DEEPSEEK_API_KEY

# запуск сервера
.\.venv\Scripts\python.exe -m app.main   # выполняется из папки server
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
cp .env.example .env
cd server && ../.venv/bin/python -m app.main
```

Сервер поднимется на `http://127.0.0.1:8000`, MCP-эндпоинт — `http://127.0.0.1:8000/mcp`.

### 2. Фронтенд (режим разработки)

```powershell
cd client
npm install
npm run dev          # http://localhost:5173, проксирует /api и /mcp на :8000
```

### 3. Production (один процесс)

```powershell
cd client
npm run build        # создаст client/dist
cd ..\server
..\.venv\Scripts\python.exe -m app.main
```

После сборки `client/dist` FastAPI раздаёт фронтенд сам — открывайте `http://127.0.0.1:8000/`.

## Конфигурация

`server/config.json`:

| Поле | Назначение |
| --- | --- |
| `parse_interval_minutes` | X — период парсинга в минутах |
| `max_articles` | Y — максимум статей в базе |
| `posts_per_fetch` | N — сколько постов брать за один запрос (8) |
| `theme_cache_ttl_sec` | кэш страниц тем при вызове тулов |
| `excluded_themes` | темы, для которых не создаются тулы |
| `autostart_parsing` | запускать ли cron при старте сервера |

`.env` (не коммитится):

| Переменная | Назначение |
| --- | --- |
| `DEEPSEEK_API_KEY` | API-ключ DeepSeek (только на сервере) |
| `DEEPSEEK_MODEL` | ID модели, по умолчанию `deepseek-chat` |
| `DEEPSEEK_BASE_URL` | базовый URL API |
| `HOST`, `PORT` | адрес и порт сервера |
| `CORS_ORIGINS` | разрешённые origin через запятую |

## REST API

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/api/status` | статус MCP, парсинга, LLM, число статей |
| GET | `/api/config` | публичная конфигурация (без секретов) |
| GET | `/api/articles?limit=` | статьи из базы |
| GET | `/api/tools` | список тулов |
| GET | `/api/themes` | список тем |
| POST | `/api/parsing/start` \| `/stop` \| `/run-now` | управление парсингом |
| POST | `/api/chat` | сообщение в чат (`{message, session_id}`) |

## MCP-тулы

- `get_saved_articles(limit)` — статьи из SQLite;
- `get_theme_<slug>(limit)` — свежие посты темы (23 темы: `get_theme_humor`, `get_theme_it`, …);
- `summarize_best_posts(count)` — саммари последних N статей: `{title, summary, images[], videos[]}`;
- `save_summary(format)` — сохраняет последнее саммари в `server/data/summaries/summary_*.txt|json`;
- `start_parsing_pikabu` / `stop_parsing_pikabu` — запуск/остановка cron.

## Безопасность

- API-ключ хранится только в `.env` на сервере и никогда не отдаётся клиенту.
- CORS ограничен allowlist-ом из `CORS_ORIGINS`.
- Тулы работают только с доменами `pikabu.ru` (защита от SSRF), произвольные URL не принимаются.
- Имя файла саммари генерируется сервером в фиксированной папке (нет path traversal).
- Только параметризованные SQL-запросы.
- Rate limit чата и лимит длины сообщения.
- `.env`, `node_modules`, `.venv`, `server/data`, `client/dist` исключены из git.

### Деплой на VPS

1. `npm run build` и перенесите `client/dist`.
2. Запустите сервер через systemd, слушайте `127.0.0.1` (`HOST=127.0.0.1`).
3. Поставьте reverse proxy (nginx/Caddy) с TLS на домен, проксируя на `:8000`.
4. Добавьте домен в `CORS_ORIGINS`, установите права на `.env` (например `chmod 600`).

## Структура проекта

```
server/
  app/
    main.py        # FastAPI + монтирование MCP + статика
    api.py         # REST-эндпоинты
    config.py      # .env + config.json
    db.py          # SQLite: схема, upsert, обрезка до Y
    parser.py      # парсинг /best и /themes/<slug>
    themes.py      # список тем + имена тулов
    scheduler.py   # cron-парсинг (APScheduler)
    tools.py       # реестр MCP-тулов
    mcp_server.py  # MCP-сервер (Streamable HTTP)
    deepseek.py    # вызовы DeepSeek
    chat.py        # чат + function calling
  config.json
  requirements.txt
  data/            # SQLite и сохранённые саммари (gitignored)
client/
  src/
    App.vue, views/ChatView.vue, views/McpView.vue
    components/, api.ts, types.ts
```
