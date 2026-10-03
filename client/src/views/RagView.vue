<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import {
  hasStoredRagRetrieval,
  ragRetrieval,
  ragStrategy,
  setRagRetrieval,
  setRagStrategy,
} from '../store'
import type { RagRetrievalOptions, RagRetrievalStrategy, RagStrategyInfo } from '../types'

const strategies = ref<RagStrategyInfo[]>([])
const retrievalStrategies = ref<{ id: string; description: string }[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const retrieval = ref<RagRetrievalOptions>({ ...ragRetrieval.value })

const RETRIEVAL_LABELS: Record<RagRetrievalStrategy, string> = {
  baseline: 'Baseline',
  'query-rewrite': 'Query Rewrite',
  'similarity-filter': 'Similarity Filter',
  'query-rewrite-rerank': 'Query Rewrite + Reranker',
}

const retrievalOptions = computed(() =>
  (Object.keys(RETRIEVAL_LABELS) as RagRetrievalStrategy[]).map((id) => ({
    id,
    label: RETRIEVAL_LABELS[id],
    description: retrievalStrategies.value.find((item) => item.id === id)?.description ?? '',
  })),
)

const selected = computed(
  () => strategies.value.find((item) => item.strategy === ragStrategy.value) ?? null,
)

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

const retrievalErrors = computed<string[]>(() => {
  const r = retrieval.value
  const list: string[] = []
  const positive = (name: string, value: number) => {
    if (!finite(value) || value < 1) list.push(`${name} должен быть ≥ 1`)
  }
  const threshold = (name: string, value: number) => {
    if (!finite(value) || value < 0 || value > 1) list.push(`${name} должен быть в диапазоне 0..1`)
  }

  if (r.strategy === 'baseline') {
    positive('Top_K', r.top_k)
  } else if (r.strategy === 'query-rewrite') {
    positive('Top_K', r.top_k)
    threshold('Similarity threshold', r.similarity_threshold)
  } else if (r.strategy === 'similarity-filter') {
    positive('Top_K before filter', r.top_k_before)
    threshold('Similarity threshold', r.similarity_threshold)
    positive('Top_K after filter', r.top_k_after)
    if (finite(r.top_k_before) && finite(r.top_k_after) && r.top_k_before < r.top_k_after) {
      list.push('Top_K before filter не может быть меньше Top_K after filter')
    }
  } else {
    positive('Top_K before reranker', r.top_k_before)
    threshold('Similarity threshold', r.similarity_threshold)
    positive('Top_K final', r.top_k_final)
    if (finite(r.top_k_before) && finite(r.top_k_final) && r.top_k_before < r.top_k_final) {
      list.push('Top_K before reranker не может быть меньше Top_K final')
    }
    if (r.reranker_threshold_enabled) {
      threshold('Reranker threshold', r.reranker_threshold)
    }
  }
  return list
})

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await api.getRagStrategies()
    strategies.value = data.strategies
    retrievalStrategies.value = data.retrieval_strategies ?? []
    if (ragStrategy.value && !strategies.value.some((item) => item.strategy === ragStrategy.value)) {
      // индекс пропал (например, очистили server/data) — выключаем RAG
      setRagStrategy('')
    }
    if (!hasStoredRagRetrieval()) {
      // первый запуск: Top_K для Baseline берём из server/config.json
      try {
        const config = await api.getConfig()
        retrieval.value.top_k = config.rag.chat_top_k
      } catch {
        // конфиг недоступен — оставляем значения по умолчанию
      }
    }
  } catch (err) {
    error.value = message(err)
  } finally {
    loading.value = false
  }
}

function choose(strategy: string) {
  if (strategy === ragStrategy.value) return
  setRagStrategy(strategy)
}

function chooseRetrieval(strategy: RagRetrievalStrategy) {
  retrieval.value.strategy = strategy
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ru-RU')
}

watch(
  retrieval,
  () => {
    if (retrievalErrors.value.length === 0) setRagRetrieval({ ...retrieval.value })
  },
  { deep: true },
)

onMounted(load)
</script>

<template>
  <div class="h-full space-y-4 overflow-y-auto p-4">
    <div
      v-if="error"
      class="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200"
    >
      {{ error }}
    </div>

    <div class="mx-auto w-full max-w-4xl space-y-4">
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="text-sm font-semibold text-slate-200">RAG для вкладки «Чат»</h2>
        <p class="mt-1 text-xs text-slate-400">
          Выберите стратегию чанкинга и стратегию поиска — вкладка «Чат» будет искать релевантные
          чанки по базе знаний (pikabu-txt.md) и подмешивать их в вопрос к LLM. «Не использовать RAG» —
          чат работает как обычно (агент с тулами). Смена стратегии очищает историю диалога.
        </p>
      </section>

      <!-- Выбор стратегии чанкинга -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Стратегия чанкинга (индекс)</h2>

        <div class="grid gap-3 md:grid-cols-2">
          <button
            type="button"
            class="rounded-lg border p-3 text-left transition"
            :class="
              ragStrategy === ''
                ? 'border-indigo-500 bg-indigo-950/40'
                : 'border-slate-700 hover:border-slate-500'
            "
            @click="choose('')"
          >
            <p class="text-sm font-medium text-slate-100">
              Не использовать RAG
              <span v-if="ragStrategy === ''" class="ml-2 text-xs text-indigo-300">выбрано</span>
            </p>
            <p class="mt-1 text-xs text-slate-400">
              Обычный чат-агент с MCP-тулами, без поиска по чанкам.
            </p>
          </button>

          <button
            v-for="item in strategies"
            :key="item.strategy"
            type="button"
            class="rounded-lg border p-3 text-left transition"
            :class="
              ragStrategy === item.strategy
                ? 'border-indigo-500 bg-indigo-950/40'
                : 'border-slate-700 hover:border-slate-500'
            "
            @click="choose(item.strategy)"
          >
            <p class="text-sm font-medium text-slate-100">
              <span class="font-mono">{{ item.strategy }}</span>
              <span v-if="ragStrategy === item.strategy" class="ml-2 text-xs text-indigo-300">выбрано</span>
            </p>
            <p class="mt-1 text-xs text-slate-400">{{ item.description }}</p>
            <p class="mt-1 text-xs text-slate-500">
              чанков: {{ item.chunks }} · ~{{ item.tokens_avg }} токенов/чанк
            </p>
            <p v-if="!item.has_embeddings" class="mt-1 text-xs text-amber-300">
              нет эмбеддингов — поиск не заработает
            </p>
          </button>
        </div>

        <p v-if="loading" class="mt-3 text-xs text-slate-500">Загрузка стратегий…</p>
        <p v-else-if="!strategies.length" class="mt-3 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-200">
          RAG-индексы не собраны. Соберите из папки server:
          <span class="font-mono">..\.venv\Scripts\python.exe -m app.rag build</span>
        </p>
      </section>

      <!-- Выбор стратегии поиска -->
      <section v-if="ragStrategy" class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-1 text-sm font-semibold text-slate-200">Стратегия поиска</h2>
        <p class="mb-3 text-xs text-slate-400">
          Пайплайн обработки результатов: переписывание запроса, фильтр по similarity, reranker.
          Параметры применяются к каждому вопросу во вкладке «Чат».
        </p>

        <div class="grid gap-2 md:grid-cols-2">
          <button
            v-for="item in retrievalOptions"
            :key="item.id"
            type="button"
            class="rounded-lg border p-3 text-left transition"
            :class="
              retrieval.strategy === item.id
                ? 'border-indigo-500 bg-indigo-950/40'
                : 'border-slate-700 hover:border-slate-500'
            "
            @click="chooseRetrieval(item.id)"
          >
            <p class="text-sm font-medium text-slate-100">
              {{ item.label }}
              <span v-if="retrieval.strategy === item.id" class="ml-2 text-xs text-indigo-300">выбрано</span>
            </p>
            <p v-if="item.description" class="mt-1 text-xs text-slate-400">{{ item.description }}</p>
          </button>
        </div>

        <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label
            v-if="retrieval.strategy === 'baseline' || retrieval.strategy === 'query-rewrite'"
            class="block"
          >
            <span class="text-xs text-slate-400">Top_K</span>
            <input
              v-model.number="retrieval.top_k"
              type="number"
              min="1"
              step="1"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </label>

          <label
            v-if="retrieval.strategy === 'similarity-filter' || retrieval.strategy === 'query-rewrite-rerank'"
            class="block"
          >
            <span class="text-xs text-slate-400">
              Top_K before {{ retrieval.strategy === 'query-rewrite-rerank' ? 'reranker' : 'filter' }}
            </span>
            <input
              v-model.number="retrieval.top_k_before"
              type="number"
              min="1"
              step="1"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </label>

          <label v-if="retrieval.strategy !== 'baseline'" class="block">
            <span class="text-xs text-slate-400">Similarity threshold</span>
            <input
              v-model.number="retrieval.similarity_threshold"
              type="number"
              min="0"
              max="1"
              step="0.05"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
            <span class="mt-0.5 block text-[11px] text-slate-500">
              оставляем чанки со similarity ≥ порога (косинусная близость)
            </span>
          </label>

          <label v-if="retrieval.strategy === 'similarity-filter'" class="block">
            <span class="text-xs text-slate-400">Top_K after filter</span>
            <input
              v-model.number="retrieval.top_k_after"
              type="number"
              min="1"
              step="1"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </label>

          <label v-if="retrieval.strategy === 'query-rewrite-rerank'" class="block">
            <span class="text-xs text-slate-400">Top_K final</span>
            <input
              v-model.number="retrieval.top_k_final"
              type="number"
              min="1"
              step="1"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </label>

          <label v-if="retrieval.strategy === 'query-rewrite-rerank'" class="block">
            <span class="flex items-center gap-2 text-xs text-slate-400">
              <input
                v-model="retrieval.reranker_threshold_enabled"
                type="checkbox"
                class="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 accent-indigo-500"
              />
              Reranker threshold
            </span>
            <input
              v-model.number="retrieval.reranker_threshold"
              type="number"
              min="0"
              max="1"
              step="0.05"
              :disabled="!retrieval.reranker_threshold_enabled"
              class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 outline-none focus:border-indigo-500 disabled:opacity-40"
            />
            <span class="mt-0.5 block text-[11px] text-slate-500">
              оценка reranker (LLM, 0..1), по умолчанию выключено
            </span>
          </label>
        </div>

        <div
          v-if="retrievalErrors.length"
          class="mt-3 rounded border border-red-900/60 bg-red-950/30 px-2 py-1 text-xs text-red-200"
        >
          <p v-for="err in retrievalErrors" :key="err">{{ err }}</p>
        </div>
        <p v-else class="mt-3 text-xs text-emerald-300">
          Настройки сохранены и применятся в чате.
        </p>
      </section>

      <!-- Детали выбранной стратегии чанкинга -->
      <section v-if="selected" class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">
          Индекс <span class="font-mono text-indigo-300">{{ selected.strategy }}</span>
        </h2>
        <dl class="grid gap-1 text-xs text-slate-400 sm:grid-cols-2">
          <div class="flex justify-between gap-2">
            <dt>Чанков</dt>
            <dd class="text-slate-300">{{ selected.chunks }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Статей в источнике</dt>
            <dd class="text-slate-300">{{ selected.articles ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Токенов на чанк</dt>
            <dd class="text-slate-300">
              {{ selected.tokens_min }} / {{ selected.tokens_avg }} / {{ selected.tokens_max }}
              (min / avg / max)
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Модель эмбеддингов</dt>
            <dd class="font-mono text-slate-300">
              {{ selected.embedding_model || '—' }}
              <span v-if="selected.embedding_dim">({{ selected.embedding_dim }}d)</span>
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Собран</dt>
            <dd class="text-slate-300">{{ formatDate(selected.built_at) }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Перекрытие / границы</dt>
            <dd class="text-slate-300">
              {{ selected.params?.overlap_tokens ?? '—' }} токенов, {{ selected.params?.min_tokens }}–{{
                selected.params?.max_tokens
              }}
            </dd>
          </div>
        </dl>
        <p
          v-if="!selected.has_embeddings"
          class="mt-3 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-200"
        >
          У индекса нет эмбеддингов — RAG-ответы работать не будут. Пересоберите:
          <span class="font-mono">..\.venv\Scripts\python.exe -m app.rag build</span>
        </p>
        <p v-else class="mt-3 text-xs text-emerald-300">
          Стратегия активна: вкладка «Чат» отвечает с опорой на найденные чанки.
        </p>
      </section>
    </div>
  </div>
</template>
