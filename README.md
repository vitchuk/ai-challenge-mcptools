# Pikabu MCP

Веб-клиент с чатом на Vue 3 и MCP-сервер на Python: периодически парсит [pikabu.ru/best](https://pikabu.ru/best) в SQLite, отдаёт статьи через MCP-тулы и общается с пользователем через LLM (DeepSeek).

## Возможности

- **Вкладка «Чат»**: диалог с LLM (DeepSeek) с function calling. Команда `/tools` показывает справку по всем тулам. Ответы агента со списками постов рендерятся карточками (заголовок-ссылка, картинка/иконка видео, мета). Сверху — сворачиваемый блок **«Саммари»** с содержимым последнего саммари-файла (JSON); показывается только при наличии карточек. Пока в базе нет статей — заглушка «Еще не спарсили» с обратным отсчётом до следующего парсинга и вейтером «выполняется парсинг»; после парсинга карточки появляются автоматически.
- **Вкладка «MCP»**: конфигурация сервера, статус подключения MCP, кнопки **Старт/Стоп** cron-парсинга, кнопка «Спарсить сейчас», кнопка **«Очистить данные»** (удаляет все статьи из БД, все саммари и содержимое `mcp_output`), статистика и список тулов.
- **Внешние MCP-серверы**: интеграция **Playwright MCP (Microsoft)** для скриншотов страниц; на вкладке MCP каждый сервер можно **включать/выключать** с зелёным/красным индикатором статуса.
- **Сценарий «саммари + скриншоты»**: агент делает саммари постов, открывает их страницы и сохраняет скриншоты в папку саммари (имя папки — дата и время саммаризации). Тулы разных MCP-серверов вызываются последовательно в одном диалоге.
- **Парсинг** `https://pikabu.ru/best` (это лента **«лучшее за сегодня»**) по расписанию (каждые X минут), хранение не более Y последних статей, удаление старых. Посты старше `max_post_age_hours` отбрасываются — страховка, что парсим именно свежее.
- **Автосаммари**: после каждого парсинга новые статьи саммаризируются через LLM и результат автоматически сохраняется в `server/data/summaries/summary_*.json`.
- **Тулы**: `get_saved_articles`, `get_theme_<тема>` (23 темы с https://pikabu.ru/themes), `summarize_best_posts`, `save_summary` (txt/json), `start_parsing_pikabu`, `stop_parsing_pikabu`.

## Архитектура

```
[Vue 3 + Vite + TS + Tailwind]  --REST/JSON-->  [FastAPI :8000]
        вкладка Чат                                 /api/*      — чат, статус, конфиг, статьи, старт/стоп
        вкладка MCP                                 /mcp        — MCP-сервер (Streamable HTTP)
                                                    LLM-агент   — DeepSeek + вызовы тулов
                                                    Scheduler   — APScheduler (интервал X мин)
                                                    Parser      — httpx + BeautifulSoup → SQLite
                                                    MCPManager  — внешние MCP-серверы (stdio)
                                                    client/dist — статика (один порт в prod)
```

Сколько отдаёт сайт за один запрос: страница `/best` содержит 8 полноценных постов (плюс 2 рекламные вставки, которые парсер пропускает). Поэтому **N = 8** — значение `posts_per_fetch` в конфиге.

> `https://pikabu.ru/best` уже отдаёт **лучшее за сегодня** (title страницы «Лучшие посты за сегодня», в конфиге страницы `"date":"today"`). Выбор «неделя/месяц/дата» делается на сайте JS-виджетом и серверу через URL не передаётся, поэтому парсится дефолт «сегодня». Дополнительно парсер отбрасывает посты старше `max_post_age_hours`.


## Требования

- Python 3.11+ (проверено на 3.14)
- Node.js 18+ (нужен и для клиента, и для Playwright MCP через `npx`)
- Google Chrome/Chromium — Playwright MCP по умолчанию использует системный Chrome
  (при первом запуске `npx` также скачает пакет `@playwright/mcp`)

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

`server/config.json` (значения — как в поставляемом файле):

| Поле | Значение | Назначение |
| --- | --- | --- |
| `parse_interval_minutes` | `30` | X — период cron-парсинга в минутах |
| `max_articles` | `10` | Y — максимум статей в базе (старые удаляются) |
| `posts_per_fetch` | `8` | N — сколько постов брать за один запрос |
| `max_post_age_hours` | `48` | отбрасывать посты старше N часов (страховка «за сегодня») |
| `auto_summary_after_parse` | `true` | автосаммари новых статей в JSON после каждого парсинга |
| `pikabu_best_url` | `https://pikabu.ru/best` | URL ленты «Лучшее» |
| `pikabu_themes_url` | `https://pikabu.ru/themes` | страница тем для обнаружения тулов `get_theme_*` |
| `pikabu_base_url` | `https://pikabu.ru` | базовый URL (резолв относительных ссылок, SSRF-проверка) |
| `theme_cache_ttl_sec` | `300` | кэш страниц тем при вызове тулов |
| `excluded_themes` | `[]` | темы (slug), для которых не создаются тулы |
| `autostart_parsing` | `true` | запускать cron сразу при старте сервера |
| `database_path` | `server/data/pikabu.db` | путь к SQLite (абсолютный или от корня проекта) |
| `summaries_dir` | `server/data/summaries` | папка для сохранённых саммари (txt/json) |
| `parse_timeout_sec` | `20` | таймаут HTTP-запросов парсера |
| `request_delay_sec` | `1.0` | пауза между повторными попытками запроса |
| `chat_max_iterations` | `16` | максимум циклов «LLM → тулы» на одно сообщение (сценарий саммари+скриншоты требует запаса) |
| `chat_history_limit` | `20` | сколько сообщений истории хранится на сессию чата |
| `chat_rate_limit_per_minute` | `20` | лимит сообщений чата в минуту на сессию |
| `chat_max_message_chars` | `4000` | максимум символов в сообщении пользователя |
| `allowed_screenshot_hosts` | `["pikabu.ru"]` | хосты, для которых внешним серверам разрешено открывать страницы и делать скриншоты |
| `external_mcp_servers` | см. ниже | список внешних MCP-серверов (stdio), включаемых/выключаемых из UI |

Поля `external_mcp_servers[]`:

| Поле | Назначение |
| --- | --- |
| `name` | идентификатор сервера; тулы получают имя `name__tool` |
| `description` | описание для UI и подсказок агента |
| `command`, `args` | команда запуска stdio-процесса (на Windows `npx` оборачивается в `cmd /c` автоматически) |
| `enabled_by_default` | включён ли сервер при первом запуске (дальше состояние сохраняется) |
| `output_dir`, `output_dir_flag` | папка файлов сервера; менеджер добавляет флаг в args и сам переносит скриншоты в папку саммари; содержимое очищается кнопкой «Очистить данные» |
| `tools_filter` | какие тулы сервера показать агенту (пустой список = все) |
| `screenshot_tools` | тулы, чьи файлы-результаты переносятся в папку саммари |

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
| GET | `/api/status` | статус MCP, список серверов (`servers`), парсинга, LLM, число статей |
| GET | `/api/config` | публичная конфигурация (без секретов) |
| GET | `/api/articles?limit=` | статьи из базы |
| GET | `/api/tools` | список тулов (встроенные + внешние, поле `server`) |
| GET | `/api/themes` | список тем |
| GET | `/api/summary/latest` | последний саммари-файл (JSON) |
| POST | `/api/parsing/start` \| `/stop` \| `/run-now` | управление парсингом |
| POST | `/api/parsing/clear-data` | удалить все статьи из БД, все саммари и содержимое `mcp_output` |
| GET | `/api/mcp-servers` | статус внешних MCP-серверов |
| POST | `/api/mcp-servers/{name}/enable` \| `/disable` | включить/выключить внешний MCP-сервер |
| POST | `/api/chat` | сообщение в чат (`{message, session_id}`) |

## MCP-тулы

- `get_saved_articles(limit)` — статьи из SQLite;
- `get_theme_<slug>(limit)` — свежие посты темы (23 темы: `get_theme_humor`, `get_theme_it`, …);
- `summarize_best_posts(count)` — саммари последних N статей: `{title, summary, images[], videos[]}`, результат пишется в папку `server/data/summaries/summary_<ГГГГММДД_ЧЧММСС>/summary.json`;
- `save_summary(format)` — сохранить саммари в `summary.txt|json` в ту же папку;
- `start_parsing_pikabu` / `stop_parsing_pikabu` — запуск/остановка cron.

## Внешние MCP-серверы (скриншоты)

Приложение выступает **MCP-клиентом** по отношению к внешним серверам из
`config.json → external_mcp_servers`. По умолчанию подключён
**[Playwright MCP](https://github.com/microsoft/playwright-mcp) (Microsoft)** —
headless Chrome делает скриншоты страниц.

- Сервер запускается как stdio-процесс (`npx -y @playwright/mcp@latest`), поэтому на машине
  нужны Node.js и Chrome/Chromium; при первой загрузке `npx` скачивает пакет (после первого
  раза — из кэша).
- Из ~25 тулов Playwright MCP агенту показываются **только 2** (`tools_filter`):
  `playwright__browser_navigate` и `playwright__browser_take_screenshot` — экономия токенов.
  Префикс `playwright__` — имя сервера, поэтому агент видит, к какому серверу относится тул,
  и может последовательно вызывать тулы pikabu и playwright в одном диалоге.
- `--image-responses omit`: base64-картинки не попадают в контекст LLM.
- **Папки саммари**: `summarize_best_posts` создаёт `summary_<ГГГГММДД_ЧЧММСС>/` (дата+время
  саммаризации) и пишет туда `summary.json`. Скриншоты, сделанные после него, автоматически
  переносятся из `server/data/mcp_output` в ту же папку — саммари и скриншоты лежат вместе.
  Кнопка «Очистить данные» на вкладке MCP удаляет и папки саммари, и содержимое `mcp_output`.
- **Вкл/выкл на вкладке «MCP»**: у каждого внешнего сервера — зелёный/красный индикатор
  (connected) и кнопка Включить/Выключить; состояние сохраняется в
  `server/data/mcp_servers_state.json`. Встроенный `pikabu` всегда включён, у него индикатор
  здоровья `/mcp`.
- **SSRF-политика**: скриншоты разрешены только для хостов из `allowed_screenshot_hosts`
  (по умолчанию `pikabu.ru`); произвольные пути для сохранения файлов моделью игнорируются.

Пример запроса в чате: «Сделай саммари 3 постов со скриншотами» → агент вызывает
`summarize_best_posts`, затем для каждого поста `playwright__browser_navigate` +
`playwright__browser_take_screenshot`, и отвечает с путём к папке.

## Безопасность

- API-ключ хранится только в `.env` на сервере и никогда не отдаётся клиенту.
- CORS ограничен allowlist-ом из `CORS_ORIGINS`.
- Тулы работают только с доменами `pikabu.ru` (защита от SSRF), произвольные URL не принимаются.
- Скрины внешних MCP-серверов — только хосты из `allowed_screenshot_hosts`; пути файлов из
  вызовов модели вырезаются, скриншоты сохраняются сервером в подконтрольные папки.
- Команды внешних MCP-серверов задаются только администратором в `config.json` (из UI — только
  вкл/выкл по имени сервера).
- Имя файла саммари генерируется сервером в фиксированной папке (нет path traversal).
- Только параметризованные SQL-запросы.
- Rate limit чата и лимит длины сообщения.
- `.env`, `node_modules`, `.venv`, `server/data`, `client/dist` исключены из git.

### Деплой на VPS

1. `npm run build` и перенесите `client/dist`.
2. Запустите сервер через systemd, слушайте `127.0.0.1` (`HOST=127.0.0.1`).
3. Поставьте reverse proxy (nginx/Caddy) с TLS на домен, проксируя на `:8000`.
4. Добавьте домен в `CORS_ORIGINS`, установите права на `.env` (например `chmod 600`).
5. Для скриншотов на Linux установите браузер: `npx -y playwright install --with-deps chromium`
   (Playwright MCP использует системный Chrome, если он есть).

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
    scheduler.py   # cron-парсинг (APScheduler) + автосаммари
    tools.py       # реестр MCP-тулов, папки саммари
    mcp_server.py  # встроенный MCP-сервер (Streamable HTTP)
    mcp_manager.py # внешние MCP-серверы (stdio): статус, вкл/выкл, скриншоты
    deepseek.py    # вызовы DeepSeek
    chat.py        # чат + function calling (тулы всех серверов)
  config.json
  requirements.txt
  data/            # SQLite, саммари-папки, вывод внешних MCP (gitignored)
client/
  src/
    App.vue, views/ChatView.vue, views/McpView.vue
    components/, api.ts, types.ts, store.ts
```
