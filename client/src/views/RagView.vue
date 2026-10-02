<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { ragStrategy, setRagStrategy } from '../store'
import type { RagStrategyInfo } from '../types'

const strategies = ref<RagStrategyInfo[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const selected = computed(
  () => strategies.value.find((item) => item.strategy === ragStrategy.value) ?? null,
)

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await api.getRagStrategies()
    strategies.value = data.strategies
    if (ragStrategy.value && !strategies.value.some((item) => item.strategy === ragStrategy.value)) {
      // индекс пропал (например, очистили server/data) — выключаем RAG
      setRagStrategy('')
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

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ru-RU')
}

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
          Выберите стратегию чанкинга — вкладка «Чат» будет искать релевантные чанки
          по базе знаний (pikabu-txt.md) и подмешивать их в вопрос к LLM:
          вопрос → поиск чанков → объединение с вопросом → ответ LLM. «Не использовать RAG» —
          чат работает как обычно (агент с тулами). Смена стратегии очищает историю диалога.
        </p>
      </section>

      <!-- Выбор стратегии -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Стратегия</h2>

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

      <!-- Детали выбранной стратегии -->
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
