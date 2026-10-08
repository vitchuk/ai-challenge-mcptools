<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ChatView from './views/ChatView.vue'
import McpView from './views/McpView.vue'
import LogView from './views/LogView.vue'
import { api } from './api'
import { llmProvider, setLlmProvider } from './store'
import type { AppStatus, LlmProvider } from './types'

type Tab = 'chat' | 'mcp' | 'log'

const tab = ref<Tab>('chat')

const tabs: { id: Tab; label: string }[] = [
  { id: 'chat', label: 'Чат' },
  { id: 'mcp', label: 'MCP' },
  { id: 'log', label: 'LOG' },
]

const status = ref<AppStatus | null>(null)

onMounted(async () => {
  try {
    status.value = await api.getStatus()
  } catch {
    // статус недоступен — дропдаун работает с провайдером по умолчанию
  }
})

function providerAvailable(provider: LlmProvider): boolean {
  if (!status.value) return true
  return provider === 'deepseek'
    ? status.value.llm.deepseek.configured
    : status.value.llm.ollama.available
}

function providerLabel(provider: LlmProvider): string {
  if (provider === 'deepseek') {
    const model = status.value?.llm.deepseek.model ?? 'deepseek'
    const suffix = status.value && !status.value.llm.deepseek.configured ? ' — ключ не задан' : ''
    return `DeepSeek (${model})${suffix}`
  }
  const model = status.value?.llm.ollama.model ?? 'ollama'
  const suffix = status.value && !status.value.llm.ollama.available ? ' — не запущена' : ''
  return `Ollama (${model})${suffix}`
}

function onProviderChange(event: Event) {
  setLlmProvider((event.target as HTMLSelectElement).value as LlmProvider)
}
</script>

<template>
  <div class="flex h-full flex-col bg-slate-950 text-slate-100">
    <header class="flex items-center gap-6 border-b border-slate-800 px-4 py-3">
      <div>
        <h1 class="text-base font-semibold">Ai Playground</h1>
        <select
          class="mt-0.5 max-w-[280px] rounded-lg border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs text-slate-300"
          :value="llmProvider"
          @change="onProviderChange"
        >
          <option value="deepseek" :disabled="!providerAvailable('deepseek')">
            {{ providerLabel('deepseek') }}
          </option>
          <option value="ollama" :disabled="!providerAvailable('ollama')">
            {{ providerLabel('ollama') }}
          </option>
        </select>
      </div>
      <nav class="flex gap-1">
        <button
          v-for="item in tabs"
          :key="item.id"
          type="button"
          class="rounded-lg px-4 py-1.5 text-sm transition"
          :class="
            tab === item.id
              ? 'bg-indigo-600 text-white'
              : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
          "
          @click="tab = item.id"
        >
          {{ item.label }}
        </button>
      </nav>
    </header>

    <main class="min-h-0 flex-1">
      <ChatView v-show="tab === 'chat'" />
      <McpView v-show="tab === 'mcp'" />
      <LogView v-show="tab === 'log'" :active="tab === 'log'" />
    </main>
  </div>
</template>
