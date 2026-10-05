# REST API и MCP

> **TL;DR**: REST под `/api/*`, MCP-сервер под `/mcp` (Streamable HTTP). Все REST-запросы клиента
> несут заголовок `X-Session-Id`; тело — JSON. Поля ответов чата: `reply`, `tool_calls`,
> `chunks?`, `debug?`, `task_state?`, `error?`.

Базовый URL локально: `http://127.0.0.1:8000`. Секреты в API не отдаются.

## REST-эндпоинты

| Метод | Путь | Параметры / тело | Возвращает |
| --- | --- | --- | --- |
| GET | `/api/status` | — | `mcp` (connected/transport/tools_count), `servers[]`, `parsing`, `articles_count`, `last_parsed_at`, `llm` |
| GET | `/api/config` | — | публичный конфиг (`public_config()`, без секретов) |
| GET | `/api/articles` | `limit` (1..500, по умолч. 100) | `{count, articles[]}` |
| GET | `/api/tools` | — | `{count, tools[]}` (встроенные + внешние, поле `server`) |
| GET | `/api/themes` | — | `{count, themes[]}` |
| GET | `/api/mcp-servers` | — | `{servers[]}` |
| POST | `/api/mcp-servers/{name}/enable` | — | статус сервера |
| POST | `/api/mcp-servers/{name}/disable` | — | статус сервера |
| POST | `/api/parsing/start` | — | `parsing` |
| POST | `/api/parsing/stop` | — | `parsing` |
| POST | `/api/parsing/run-now` | — | результат парсинга (`ok`, `new`, …) |
| POST | `/api/parsing/clear-data` | — | `{cleared_articles, cleared_summaries, cleared_mcp_outputs}` |
| GET | `/api/summary/latest` | — | `{exists, file, folder, summary}` |
| POST | `/api/chat` | `{message, session_id?, rag_strategy?, rag_options?}` | `ChatResponse` (включая `chat_id`, `chat_title`) |
| GET | `/api/chat/history` | заголовок `X-Session-Id` или `session_id` | `{session_id, messages[], task_state}` |
| POST | `/api/chat/reset` | `{session_id?}` | `{ok, session_id}` (удаляет чат целиком) |
| GET | `/api/chats` | — | `{count, chats[]}` (заголовок = первый вопрос, свежие сверху) |
| POST | `/api/chats/{session_id}/delete` | — | `{ok, session_id}` (идемпотентно) |
| GET | `/api/rag/strategies` | — | `{strategies[], retrieval_strategies[]}` |
| GET | `/api/rag/strategies/{strategy}` | `limit` (1..500, по умолч. 50) | чанки индекса без векторов |

`session_id` в `/api/chat` и `/api/chat/reset`; если не передан — берётся заголовок `X-Session-Id`
(иначе `"default"`). Каждый `session_id` — отдельный сохраняемый чат.

## `POST /api/chat`

Тело:

```json
{
  "message": "Что известно о наклоне земной оси?",
  "session_id": "uuid",
  "rag_strategy": "fixed",
  "rag_options": {
    "strategy": "query-rewrite-rerank",
    "top_k": 5,
    "top_k_before": 12,
    "top_k_after": 5,
    "top_k_final": 5,
    "similarity_threshold": 0.75,
    "reranker_threshold": 0.5
  }
}
```

- `rag_strategy` — id **стратегии чанкинга** (`fixed`/`paragraph`) или `null` → агентский режим (без RAG).
- `rag_options` — **стратегия поиска** (`baseline` / `query-rewrite` / `similarity-filter` /
  `query-rewrite-rerank`) и её параметры; `null` — baseline-поведение.
- Без `DEEPSEEK_API_KEY` вернётся `error: "llm_not_configured"` с понятным текстом (интерфейс работает).

Ответ (`ChatResponse`):

```json
{
  "reply": "…текст ответа…",
  "tool_calls": [{"name": "…", "arguments": {}, "result_preview": "…", "result": "…"}],
  "chunks": [{"id": "fixed_003", "score": 0.69, "reranker_score": 0.9, "tokens": 300,
              "metadata": {"title": "…", "url": "…", "author": "…", "rating": 7,
                           "date": "…", "story_id": 14379038, "chunk_index": 2},
              "text": "…"}],
  "debug": {"retrieval_strategy": "query-rewrite-rerank", "original_query": "…",
            "rewritten_query": "…", "rewrite_fallback": false, "reranker_fallback": false,
            "params": {}, "counts": {"retrieved": 12, "after_similarity_filter": 12,
                                     "after_reranker_filter": 12, "final": 5}},
  "task_state": {"goal": "…", "clarifications": ["…"], "constraints": ["…"], "updated_at": "…"},
  "chat_id": "uuid",
  "chat_title": "Первый вопрос пользователя…",
  "error": null
}
```

В агентском режиме `chunks` = `[]`, `debug`/`task_state` отсутствуют. `chat_id` = `session_id`,
`chat_title` = заголовок чата (обрезка первого вопроса).

## Примеры (curl)

```bash
# Статус
curl -s http://127.0.0.1:8000/api/status

# RAG-чат (baseline)
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" -H "X-Session-Id: demo" \
  -d '{"message":"Почему Земля не падает на Солнце?","rag_strategy":"fixed","rag_options":{"strategy":"baseline","top_k":4}}'

# История и память задачи сессии
curl -s "http://127.0.0.1:8000/api/chat/history?session_id=demo"

# Очистить/удалить чат целиком
curl -s -X POST http://127.0.0.1:8000/api/chat/reset \
  -H "Content-Type: application/json" -d '{"session_id":"demo"}'

# Список чатов
curl -s http://127.0.0.1:8000/api/chats

# Удалить чат по id
curl -s -X POST http://127.0.0.1:8000/api/chats/demo/delete

# Очистить все данные (статьи/саммари/output MCP)
curl -s -X POST http://127.0.0.1:8000/api/parsing/clear-data

# Выключить/включить внешний MCP-сервер
curl -s -X POST http://127.0.0.1:8000/api/mcp-servers/playwright/disable
```

## MCP (`/mcp`)

Streamable HTTP (SDK v2). Используйте MCP-клиент: `initialize`, `tools/list`, `tools/call`.
Клиентские модели — **snake_case** (`input_schema`, `is_error`, `server_info`).
Тулы: встроенные pikabu (`tools.REGISTRY`) + подключённые внешние (`server__tool`).
Проверка в `/api/status`: `mcp.connected: true`, `mcp.tools_count` (28 встроенных; +2 `playwright__*`
при включённом сервере).
