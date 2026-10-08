# Клиент (client/)

> **TL;DR**: Vue 3 + Vite + TS + Tailwind. Точка входа `src/main.ts` → `App.vue` с двумя вкладками
> (`chat`/`mcp`, обе остаются смонтированными через `v-show`). Нет vue-router. Проверка типов и сборка:
> `npm run build` (`vue-tsc --noEmit` + `vite build`). **TypeScript держать на `^5`** (7.x ломает vue-tsc).

## Структура `client/src/`

| Файл | Роль |
| --- | --- |
| `main.ts` | `createApp(App).mount('#app')` |
| `App.vue` | Шапка «Ai Playground» + дропдаун выбора LLM-провайдера (DeepSeek/Ollama; недоступный — задизейблен) + вкладки «Чат»/«MCP»/«LOG» (`v-show`, роутера нет) |
| `views/ChatView.vue` | Вкладка «Чат»: три колонки — список чатов, диалог (RAG-индикатор, память задачи, стрим «размышлений», время ответа, инпут), панель RAG |
| `views/McpView.vue` | Вкладка «MCP»: две колонки — слева посты/статус парсинга, справа настройки (статус, конфиг, парсинг, саммари, серверы, тулы) |
| `views/LogView.vue` | Вкладка «LOG»: лог LLM-вызовов (`GET /api/llm-log`, поллинг 3 с) — сворачиваемые блоки запроса (system/user/assistant/tool) и ответа (размышления/тулы/ответ) |
| `store.ts` | Общий стор вкладок (без Pinia): `posts`, `articlesCount`, `dataVersion`, `summaryVersion`, `chats`, `currentChatId`, `ragStrategy`, `ragRetrieval`, `llmProvider` |
| `api.ts` | REST-клиент; `getSessionId()` (UUID в localStorage), все запросы с `X-Session-Id`; `sendChatStream` (парсер SSE), `getLlmLog`/`clearLlmLog` |
| `types.ts` | Типы API и UI (`ChatResponse`, `TaskState`, `RagChunkHit`, `AppStatus`, …) |
| `citations.ts` | `parseRagCitations(reply)` (`> [id] quote`), `splitHighlighted(text, quotes)` |
| `style.css` | Единственный css-файл (Tailwind-директивы) |

### Компоненты (`src/components/`)

| Компонент | Вход | Рисует |
| --- | --- | --- |
| `PostCard.vue` | `post: Post` | Карточка статьи (заголовок-ссылка, картинка/видео, мета) |
| `ChatTabs.vue` | `chats`, `currentChatId`, `busy` | Вертикальный список чатов: заголовок, число сообщений, крестик удаления, «+ Новый чат» |
| `AgentReply.vue` | `text`, `posts` | Ответ ассистента: цитаты `> [id]`, markdown-ссылки → встроенные карточки постов |
| `ToolCallList.vue` | `calls: ToolCallEvent[]` | Свёрнутые чипы вызовов тулов |
| `RagSources.vue` | `chunks`, `citations` | Блок «Источники RAG (N)»; при 0 — «фрагменты не найдены» |
| `RagPipelineInfo.vue` | `debug` | Отладка retrieval: original/rewritten query, воронка фильтров |
| `RagSettingsPanel.vue` | — | Правая панель: стратегия чанкинга, стратегия поиска, параметры, детали индекса |
| `TaskStatePanel.vue` | `state: TaskState` | Память задачи: цель / уточнения / ограничения |

## Потоки

### Отправка сообщения (`ChatView.send`)
`api.sendChatStream(text, chatId, {onThinking, onTool}, ragStrategy || undefined, ragStrategy ? ragRetrieval : undefined, llmProvider)` →
`POST /api/chat/stream` (SSE) с `{message, session_id, rag_strategy, rag_options, llm_provider}`. В `rag_options`
`reranker_threshold` уходит только при `reranker_threshold_enabled`. События стрима: `thinking` (дельты
размышлений — выводятся в раскрывающийся блок «Размышления» под вейтером в рантайме), `tool` (вызов тула),
`reply` (финальный ответ: `reply`, `tool_calls`, `chunks`, `debug`, `task_state`, `reasoning`, `elapsed_ms`,
`chat_id`, `chat_title`). Сообщение помечается `rag: true`, если включён RAG и нет ошибки → под ответом
рендерятся `RagSources` (даже при пустых chunks) и `RagPipelineInfo`. Под assistant-сообщением показываются
`message.thinking` (блок «Размышления», схлопнут) и `message.elapsedMs` (`⏱ N с`; если ответа нет — ничего).
Если чат новый — после ответа `getChats()` обновляет список; иначе `touchChat` поднимает чат наверх.

### Чаты (список, переключение, удаление)
`ChatView` при старте (`onMounted`) грузит `getChats()` и выбирает `currentChatId` из localStorage
(иначе самый свежий, иначе пустое состояние). `loadChat(id)` → `getChatHistory(id)` восстанавливает
сообщения и `task_state`. `newChat()` только сбрасывает выбор — **чат создаётся лениво** при первом
сообщении (`crypto.randomUUID()` в `send`). Удаление — крестик в `ChatTabs` → `window.confirm` →
`deleteChat(id)` (`POST /api/chats/{id}/delete`) → `removeChat`; если удалён активный чат, выбирается
соседний (или пустое состояние). Смена RAG-стратегии чат **не сбрасывает**.

### Восстановление истории
`loadChat(id)` → `api.getChatHistory(id)` (`GET /api/chat/history?session_id=…`) → сообщения и
`task_state` восстанавливаются в UI.

### Посты, парсинг и саммари (вкладка «MCP»)
`McpView` — владелец загрузки постов: `loadPosts()` → `api.getArticles(500)` → `setPosts()` в стор.
Тик раз в секунду: при наличии постов `refresh()` каждые 5с; при пустой базе — живой отсчёт
(`updateCountdown`) и `refresh()` каждые 1–3с (детект завершения парсинга по `last_run_at`).
`loadSummary()` (`GET /api/summary/latest`) вызывается при появлении постов и по `summaryVersion`.
`ChatView` читает `posts` из стора и держит `postStore` (URL → пост) для встроенных карточек в ответах
(`AgentReply`); `indexToolResults` дополняет его постами из результатов тулов.

### Синхронизация вкладок
- `dataVersion` (bump в `McpView.clearData`) — сигнал «данные очищены»; посты сбрасываются через `setPosts([])`.
- `summaryVersion` (bump в `ChatView.send` после тулов `summarize_best_posts`/`save_summary`) →
  `McpView` перезагружает блок «Саммари».

## Сборка

```powershell
cd client
npm install
npm run dev        # :5173, проксирует /api и /mcp на :8000
npm run build      # typecheck + vite build -> client/dist (раздаётся FastAPI)
```

Dev-прокси настроен в `vite.config.ts`. После `npm run build` бэкенд раздаёт SPA сам на `:8000`.
