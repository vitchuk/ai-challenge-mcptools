# Рецепты типовых изменений

> **TL;DR**: Пошаговые инструкции под частые задачи. Всегда сверяйся с [ARCHITECTURE.md](ARCHITECTURE.md)
> (инварианты) и в конце прогоняй проверки из [TESTING.md](TESTING.md).

## Добавить MCP-тул

1. В `server/app/tools.py` добавь запись в **`REGISTRY`** (имя → функция-обработчик; описание/схема
   берутся из реестра). Функция возвращает **строку с JSON** (`json.dumps(..., ensure_ascii=False)`),
   не бросает исключения наружу.
2. Ничего дублировать не нужно: `mcp_server.register_tools` и `tools.openai_tools_schema`
   подхватят тул автоматически — он появится и в MCP, и у LLM-агента.
3. Проверь `GET /api/tools` (тул в списке) и `GET /api/status` (`mcp.tools_count` увеличился).

## Добавить REST-эндпоинт

1. Добавь обработчик в `server/app/api.py` (router уже под `/api`), логику — в модуле-владельце
   (не пиши бизнес-логику прямо в эндпоинте).
2. Если нужен новый тип запроса — Pydantic-модель рядом (`ChatRequest`-стиль).
3. Клиент: метод в `client/src/api.ts` + тип в `client/src/types.ts`; вызови из `views/*`.
4. Проверь `curl`-ом и `npm run build`.

## Добавить/изменить поле в ответе чата

1. Бэкенд: дополни словарь в `chat.run_chat` / `_run_rag_chat` (`server/app/chat.py`).
2. Тип: добавь поле в `ChatResponse` в `client/src/types.ts`.
3. UI: используй поле в `ChatView.vue` (например, добавь компонент под ответом).
4. Проверь `npm run build` и живой запрос к `/api/chat`.

## Изменить системный промпт LLM

- RAG-ответ — `RAG_SYSTEM_PROMPT` в `server/app/rag.py`.
- Переформулировка поискового запроса — `REWRITE_SYSTEM_PROMPT` в `server/app/rag_pipeline.py`.
- Реранкер — `RERANK_SYSTEM_PROMPT` в `server/app/rag_pipeline.py`.
- Память задачи — `EXTRACT_SYSTEM_PROMPT` в `server/app/task_state.py`.
- Агентский чат (тулы) — `_system_prompt()` в `server/app/chat.py`.
- Требования к источникам (`> [id]`, «Источники:») живут в `RAG_SYSTEM_PROMPT`; согласованно
  отражай их в `docs/RAG.md`.

## Добавить стратегию чанкинга или поиска

- **Чанкинг**: функция вида `chunk_article_*(article, params)` + запись в `CHUNKERS` в `rag.py`,
  описание в `STRATEGIES`. Пересобери индекс (`python -m app.rag build`). UI подтянет её из
  `GET /api/rag/strategies` (`RagSettingsPanel.vue`).
- **Поиск**: добавь id в `RETRIEVAL_STRATEGIES` и ветку в `run_retrieval` (`rag_pipeline.py`);
  параметры — в `RetrievalOptions.validate`; UI-кнопки/поля — в `RagSettingsPanel.vue` и
  `DEFAULT_RAG_RETRIEVAL` (`store.ts`).

## Правки саммари/парсинга

- Логика саммари — `tools._summarize_articles` (общая для чата и планировщика). Папку создают только
  чатовые вызовы (`folder=True`); автосаммари парсера — плоский файл (см. инварианты в
  [ARCHITECTURE.md](ARCHITECTURE.md)).
- Парсинг — `parser.fetch_best` / `fetch_theme`; расписание — `scheduler.py`.

## Прогнать проверку

1. `cd client; npm run build` (типы + сборка).
2. `cd server; ..\.venv\Scripts\python.exe -c "import app.main"` (импорт-чек).
3. Скилл `pikabu-e2e` (smoke REST/MCP) или ручной чеклист — [TESTING.md](TESTING.md).
4. Для чата/скриншотов — скилл `pikabu-chat-live-test`.
5. Для RAG — `..\.venv\Scripts\python.exe -m app.rag build` и
   `.\.venv\Scripts\python.exe scripts\run_chat_scenarios.py`.

## Коммит

- Коммить по завершении логической единицы, осмысленным сообщением; не коммить `.env`,
  `node_modules`, `.venv`, `server/data`, `client/dist`.
- **Push — только по явной просьбе пользователя и в указанную им ветку.**
