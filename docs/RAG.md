# RAG-чат, источники и память задачи

> **TL;DR**: `rag.py` — чанкинг `pikabu-txt.md` + эмбеддинги ollama + косинусный поиск;
> `rag_pipeline.py` — стратегии поиска (rewrite/filter/rerank); `task_state.py` — память задачи
> (цель/уточнения/ограничения); `chat_store.py` — персистентность. Ответ **всегда** содержит
> источники (или явное «не найдены»). Нужны собранный индекс (`python -m app.rag build`) и ollama.

## Индекс (эмбеддинги + векторный поиск)

`rag.py` разбирает `pikabu-txt.md` (статьи формата `## Заголовок` + мета-строка) на чанки:

- `fixed` — скользящее окно ~750 токенов с перекрытием 150, границы по предложениям;
- `paragraph` — целые абзацы до 1000 токенов без перекрытия.

Каждый чанк получает эмбеддинг через локальную **ollama** (`qwen3-embedding:0.6b`,
`/api/embed`, векторы нормализуются L2) и складывается в `server/data/rag/<strategy>/index.json`
(чанки + векторы). Поиск — косинусный (dot product нормализованных векторов).

```powershell
cd server
..\.venv\Scripts\python.exe -m app.rag build          # обе стратегии
..\.venv\Scripts\python.exe -m app.rag list
..\.venv\Scripts\python.exe -m app.rag search "запрос" --strategy fixed
```

Нужен запущенный ollama с моделью (`ollama pull qwen3-embedding:0.6b`). Параметры — `config.json → rag`.

## Стратегии поиска (`rag_pipeline.py`)

| id | Что делает |
| --- | --- |
| `baseline` | поиск → Top_K → LLM |
| `query-rewrite` | LLM переписывает вопрос в самодостаточный запрос (учёт истории и памяти задачи) → поиск → LLM |
| `similarity-filter` | поиск Top_K до → отсечение по `similarity_threshold` → Top_K после → LLM |
| `query-rewrite-rerank` | rewrite → поиск → similarity-фильтр → LLM-reranker (оценка 0..1) → LLM |

`RetrievalOptions` валидирует параметры; при сбое rewrite/reranker — fallback на исходный запрос/порядок
similarity (флаги в `debug`). Реранкер не импортирует `rag.py` — ретривер передаётся callable.

## Память задачи (`task_state.py`)

Структура: `{"goal": str|null, "clarifications": [str], "constraints": [str], "updated_at": str|null}`.

- `goal` — цель диалога; `clarifications` — уточнения (факты, предпочтения, названия, числа);
  `constraints` — правила, определения, форматы, запреты, термины.
- **На каждом ходу** LLM-экстрактор сливает предыдущее состояние + последние сообщения + новое
  сообщение (строгий JSON). При сбое LLM — rule-based fallback (состояние сохраняется, цель при
  необходимости заполняется из сообщения). Списки нормализуются (дедуп, лимит 12×220 симв.).
- Подаётся в **генерацию** (`rag.build_rag_reply`) и в **rewrite** (`rag_pipeline.rewrite_query`) —
  поэтому ответ не противоречит цели/ограничениям, а поиск раскрывает местоимения и термины.
- Хранится отдельно от окна истории (`chat_history_limit`) → **не теряется в длинных диалогах**.

## Источники в каждом ответе

- `RAG_SYSTEM_PROMPT` требует: дословные цитаты строкой `> [id_фрагмента] цитата` и **всегда**
  завершающий раздел «Источники:» (`[id] название — url`).
- Если релевантного нет — ответ «Ответить на вопрос, опираясь на базу знаний, невозможно…» и строка
  `Источники: не найдены (нет релевантных фрагментов в базе знаний)` (см. `_empty_hits_reply`).
- UI: `RagSources` (чанки, similarity/reranker, метаданные, текст с подсветкой цитат; при 0 —
  «фрагменты не найдены»), `RagPipelineInfo` (original/rewritten query, воронка фильтров),
  цитаты в тексте рендерит `AgentReply`.

## Персистентность и API

`chat_store.py` в SQLite (`server/data/pikabu.db`): `chat_messages(id, session_id, role, content,
created_at)`, `chat_task_states(session_id, state_json, updated_at)`. RAG-чат пишет/читает их;
`GET /api/chat/history` (по `X-Session-Id`) восстанавливает сессию в UI; `/api/chat/reset` очищает.
Смена стратегии чанкинга/поиска в UI шлёт reset (стор `ragVersion`).

## Прогон проверочных сценариев

```powershell
# из корня; скрипт сам поднимает/гасит сервер (нужны ollama и DEEPSEEK_API_KEY)
.\.venv\Scripts\python.exe scripts\run_chat_scenarios.py
```

Скрипт прогоняет 2 диалога по 13 сообщений (уточнения, смена условий, новые термины/запреты,
возвраты к ранее сказанному), пишет транскрипты в `docs/scenarios/scenario-1.md`,
`scenario-2.md`, `probe-no-sources.md` и печатает сводку (источники в каждом ответе, сохранение
цели, накопление уточнений/ограничений, probe без источников).

## Тест-вопросы для ручной проверки поиска

Из `вопросы.txt` (по базе `pikabu-txt.md`): расстояние от Солнца до Земли; потерявшаяся собака;
фактор третьего человека; чёрный курильщик; факты о Пифагоре; гормон, удерживающий семена в покое;
за сколько секунд флаттер разрушает крыло; длина оптоволоконного кабеля в эксперименте НГУ; почему
теннисная ракетка переворачивается в воздухе. Офф-топик (должен дать «Источники: не найдены»):
«Как приготовить борщ?».

## Связанное

[ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md) · [TESTING.md](TESTING.md) · [GOTCHAS.md](GOTCHAS.md)
