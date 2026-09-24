<script setup lang="ts">
import { ref } from 'vue'
import ChatView from './views/ChatView.vue'
import McpView from './views/McpView.vue'

type Tab = 'chat' | 'mcp'

const tab = ref<Tab>('chat')

const tabs: { id: Tab; label: string }[] = [
  { id: 'chat', label: 'Чат' },
  { id: 'mcp', label: 'MCP' },
]
</script>

<template>
  <div class="flex h-full flex-col bg-slate-950 text-slate-100">
    <header class="flex items-center gap-6 border-b border-slate-800 px-4 py-3">
      <div>
        <h1 class="text-base font-semibold">Pikabu MCP</h1>
        <p class="text-xs text-slate-500">Чат с LLM + MCP-сервер парсинга pikabu.ru</p>
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
    </main>
  </div>
</template>
