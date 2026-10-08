<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import type { LlmLogEntry } from '../types'

const props = defineProps<{ active: boolean }>()

const entries = ref<LlmLogEntry[]>([])
const error = ref<string | null>(null)
let timer: number | undefined

async function load() {
  try {
    const data = await api.getLlmLog(100)
    entries.value = data.entries
    error.value = null
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

async function clear() {
  try {
    await api.clearLlmLog()
    entries.value = []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

function startPolling() {
  stopPolling()
  void load()
  timer = window.setInterval(load, 3000)
}

function stopPolling() {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => props.active,
  (active) => (active ? startPolling() : stopPolling()),
)

onMounted(() => {
  if (props.active) startPolling()
})

onUnmounted(stopPolling)

function formatTime(ts: string): string {
  const date = new Date(ts)
  return Number.isNaN(date.getTime()) ? ts : date.toLocaleTimeString('ru-RU')
}

function formatDuration(ms: number | null): string {
  return ms == null ? '—' : `${(ms / 1000).toFixed(2)} с`
}

function messageRole(message: Record<string, unknown>): string {
  return String(message.role ?? '?')
}

function messageBadge(message: Record<string, unknown>): string {
  const role = messageRole(message)
  if (role === 'assistant' && Array.isArray(message.tool_calls)) {
    const names = (message.tool_calls as Array<{ function?: { name?: string } }>)
      .map((call) => call.function?.name)
      .filter((name): name is string => Boolean(name))
    if (names.length) return `assistant · тулы: ${names.join(', ')}`
  }
  if (role === 'tool') return `tool · ${String(message.name ?? message.tool_call_id ?? '')}`
  return role
}

function messageText(message: Record<string, unknown>): string {
  const content = message.content
  if (typeof content === 'string') return content
  if (content == null) return ''
  return JSON.stringify(content, null, 2)
}

function preview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > 90 ? `${flat.slice(0, 90)}…` : flat || '—'
}

function phaseClass(phase: string): string {
  if (phase === 'chat') return 'bg-indigo-900/60 text-indigo-200'
  if (phase === 'rag') return 'bg-emerald-900/50 text-emerald-200'
  return 'bg-slate-700/60 text-slate-300'
}
</script>

<template>
  <div class="h-full overflow-y-auto p-4">
    <div class="mx-auto w-full max-w-4xl space-y-3">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-slate-200">Лог LLM-вызовов</h2>
          <p class="text-xs text-slate-500">
            Контекст запросов и ответы. Хранится в памяти (последние 200), обновляется каждые 3 с.
          </p>
        </div>
        <div class="flex shrink-0 gap-2">
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-300 transition hover:border-indigo-500 hover:text-indigo-300"
            @click="load"
          >
            Обновить
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-300 transition hover:border-red-500 hover:text-red-300"
            @click="clear"
          >
            Очистить
          </button>
        </div>
      </div>

      <p
        v-if="error"
        class="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200"
      >
        {{ error }}
      </p>

      <p v-if="!entries.length && !error" class="text-sm text-slate-500">
        Записей пока нет. Отправьте сообщение в чат.
      </p>

      <details
        v-for="entry in entries"
        :key="entry.id"
        class="rounded-xl border border-slate-800 bg-slate-900/60"
      >
        <summary class="flex cursor-pointer flex-wrap items-center gap-3 px-3 py-2 text-xs">
          <span class="font-mono text-slate-400">#{{ entry.id }}</span>
          <span class="text-slate-400">{{ formatTime(entry.ts) }}</span>
          <span class="rounded px-1.5 py-0.5" :class="phaseClass(entry.phase)">{{ entry.phase }}</span>
          <span class="font-mono text-slate-300">{{ entry.provider }} / {{ entry.model }}</span>
          <span v-if="entry.tools_count" class="text-slate-500">тулов: {{ entry.tools_count }}</span>
          <span class="text-slate-400">⏱ {{ formatDuration(entry.duration_ms) }}</span>
          <span v-if="entry.error" class="text-red-400">ошибка</span>
        </summary>

        <div class="space-y-2 border-t border-slate-800 p-3">
          <details
            v-for="(message, index) in entry.messages"
            :key="index"
            class="rounded-lg border border-slate-800 bg-slate-950/50"
          >
            <summary class="cursor-pointer px-3 py-1.5 text-xs text-slate-300">
              <span class="font-mono text-slate-400">{{ index + 1 }}.</span>
              <span class="ml-1 font-medium">{{ messageBadge(message) }}</span>
              <span class="ml-2 text-slate-500">{{ preview(messageText(message)) }}</span>
            </summary>
            <pre
              class="max-h-80 overflow-auto whitespace-pre-wrap px-3 pb-2 text-xs text-slate-300"
            >{{ messageText(message) || '—' }}</pre>
          </details>

          <details
            v-if="entry.response?.reasoning"
            class="rounded-lg border border-amber-900/50 bg-amber-950/20"
          >
            <summary class="cursor-pointer px-3 py-1.5 text-xs text-amber-200">Размышления</summary>
            <pre
              class="max-h-80 overflow-auto whitespace-pre-wrap px-3 pb-2 text-xs text-amber-100/80"
            >{{ entry.response.reasoning }}</pre>
          </details>

          <details
            v-if="entry.response?.tool_calls?.length"
            class="rounded-lg border border-slate-800 bg-slate-950/50"
          >
            <summary class="cursor-pointer px-3 py-1.5 text-xs text-emerald-200">
              Вызовы тулов ({{ entry.response.tool_calls.length }})
            </summary>
            <pre
              class="max-h-80 overflow-auto whitespace-pre-wrap px-3 pb-2 text-xs text-slate-300"
            >{{ JSON.stringify(entry.response.tool_calls, null, 2) }}</pre>
          </details>

          <details class="rounded-lg border border-slate-800 bg-slate-950/50">
            <summary class="cursor-pointer px-3 py-1.5 text-xs text-slate-300">Ответ</summary>
            <pre
              class="max-h-96 overflow-auto whitespace-pre-wrap px-3 pb-2 text-xs text-slate-200"
            >{{ entry.response?.content || '—' }}</pre>
          </details>

          <pre
            v-if="entry.error"
            class="whitespace-pre-wrap rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-xs text-red-200"
          >{{ entry.error }}</pre>
        </div>
      </details>
    </div>
  </div>
</template>
