# Клиент (client/)

> **TL;DR**: Vue 3 + Vite + TS + Tailwind. Точка входа `src/main.ts` → `App.vue` с двумя вкладками
> (`chat`/`mcp`, обе остаются смонтированными через `v-show`). Нет vue-router. Проверка типов и сборка:
> `npm run build` (`vue-tsc --noEmit` + `vite build`). **TypeScript держать на `^5`** (7.x ломает vue-tsc).

## Структура `client/src/`

| Файл | Роль |
| --- | --- |
| `main.ts` | `createApp(App).mount('#app')` |
| `App.vue` | Шапка + переключение вкладок «Чат»/«MCP» (`v-show`, роутера нет) |
| `views/ChatView.vue` | Вкладка «Чат»: карточки статей, блок «Саммари», диалог, панель RAG |
| `views/McpView.vue` | Вкладка «MCP»: статус, конфиг, старт/стоп/парсинг, очистка, серверы и тулы |
| `store.ts` | Общий стор вкладок (без Pinia): `articlesCount`, `dataVersion`, `ragStrategy`, `ragVersion`, `ragRetrieval` |
| `api.ts` | REST-клиент; `getSessionId()` (UUID в localStorage), все запросы с `X-Session-Id` |
| `types.ts` | Типы API и UI (`ChatResponse`, `TaskState`, `RagChunkHit`, `AppStatus`, …) |
| `citations.ts` | `parseRagCitations(reply)` (`> [id] quote`), `splitHighlighted(text, quotes)` |
| `style.css` | Единственный css-файл (Tailwind-директивы) |

### Компоненты (`src/components/`)

| Компонент | Вход | Рисует |
| --- | --- | --- |
| `PostCard.vue` | `post: Post` | Карточка статьи (заголовок-ссылка, картинка/видео, мета) |
| `AgentReply.vue` | `text`, `posts` | Ответ ассистента: цитаты `> [id]`, markdown-ссылки → встроенные карточки постов |
| `ToolCallList.vue` | `calls: ToolCallEvent[]` | Свёрнутые чипы вызовов тулов |
| `RagSources.vue` | `chunks`, `citations` | Блок «Источники RAG (N)»; при 0 — «фрагменты не найдены» |
| `RagPipelineInfo.vue` | `debug` | Отладка retrieval: original/rewritten query, воронка фильтров |
| `RagSettingsPanel.vue` | — | Правая панель: стратегия чанкинга, стратегия поиска, параметры, детали индекса |
| `TaskStatePanel.vue` | `state: TaskState` | Память задачи: цель / уточнения / ограничения |

## Потоки

### Отправка сообщения (`ChatView.send`)
`api.sendChat(text, ragStrategy || undefined, ragStrategy ? ragRetrieval : undefined)` →
`POST /api/chat` с `{message, session_id, rag_strategy, rag_options}`. В `rag_options`
`reranker_threshold` уходит только при `reranker_threshold_enabled`. Из ответа: `reply`,
`tool_calls`, `chunks`, `debug`, `task_state`. Сообщение помечается `rag: true`, если включён RAG
и нет ошибки → под ответом рендерятся `RagSources` (даже при пустых chunks) и `RagPipelineInfo`.

### Восстановление истории
`onMounted` → `Promise.all([refreshStatus(), loadChatHistory()])`. `api.getChatHistory()`
(`GET /api/chat/history`, сессия по заголовку) → сообщения и `task_state` восстанавливаются в UI.
Смена стратегии RAG (bump `ragVersion`) очищает локальные сообщения/`task_state` и зовёт
`POST /api/chat/reset`. Кнопка «Новый диалог» делает то же вручную.

### Синхронизация вкладок
`dataVersion` (bump в `McpView.clearData`) → `watch` в `ChatView` сбрасывает карточки/саммари и
перезапрашивает статус.

## Сборка

```powershell
cd client
npm install
npm run dev        # :5173, проксирует /api и /mcp на :8000
npm run build      # typecheck + vite build -> client/dist (раздаётся FastAPI)
```

Dev-прокси настроен в `vite.config.ts`. После `npm run build` бэкенд раздаёт SPA сам на `:8000`.
