<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import type { ChatMessage, ToolInfo } from '../types'
import PostCard from '../components/PostCard.vue'
import ToolCallList from '../components/ToolCallList.vue'

const messages = ref<ChatMessage[]>([])
const input = ref('')
const busy = ref(false)
const listEl = ref<HTMLElement | null>(null)
let nextId = 1

const suggestions = [
  '/tools',
  'Покажи статьи из базы',
  'Сделай саммари последних 5 статей',
  'Сохрани саммари как json',
  'Что нового в теме IT?',
]

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function scrollDown() {
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function addMessage(message: Omit<ChatMessage, 'id'>) {
  messages.value.push({ id: nextId++, ...message })
  void scrollDown()
}

async function loadArticles() {
  try {
    const data = await api.getArticles(500)
    if (data.count === 0) {
      addMessage({ role: 'system', kind: 'text', text: 'Еще не спарсили' })
    } else {
      addMessage({
        role: 'system',
        kind: 'articles',
        text: `В базе уже ${data.count} статей из ленты /best:`,
        articles: data.articles,
      })
    }
  } catch (error) {
    addMessage({ role: 'system', kind: 'text', text: `Не удалось загрузить статьи: ${errorText(error)}`, error: true })
  }
}

async function showToolsHelp() {
  try {
    const data = await api.getTools()
    addMessage({
      role: 'assistant',
      kind: 'tools',
      text: `Доступные тулы (${data.count}):`,
      tools: data.tools as ToolInfo[],
    })
  } catch (error) {
    addMessage({ role: 'assistant', kind: 'text', text: `Не удалось получить список тулов: ${errorText(error)}`, error: true })
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  input.value = ''
  addMessage({ role: 'user', kind: 'text', text })

  if (text === '/tools') {
    await showToolsHelp()
    return
  }

  busy.value = true
  try {
    const response = await api.sendChat(text)
    addMessage({
      role: 'assistant',
      kind: 'text',
      text: response.reply,
      toolCalls: response.tool_calls,
      error: Boolean(response.error),
    })
  } catch (error) {
    addMessage({ role: 'assistant', kind: 'text', text: `Ошибка: ${errorText(error)}`, error: true })
  } finally {
    busy.value = false
  }
}

function useSuggestion(text: string) {
  input.value = text
  void send()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

onMounted(loadArticles)
</script>

<template>
  <div class="flex h-full flex-col">
    <div ref="listEl" class="flex-1 space-y-3 overflow-y-auto p-4">
      <div
        v-for="message in messages"
        :key="message.id"
        class="flex"
        :class="{
          'justify-end': message.role === 'user',
          'justify-start': message.role === 'assistant',
          'justify-center': message.role === 'system',
        }"
      >
        <!-- Пользователь / ассистент -->
        <div
          v-if="message.kind !== 'articles' && message.kind !== 'tools'"
          class="max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap"
          :class="{
            'bg-indigo-600 text-white': message.role === 'user',
            'border border-slate-800 bg-slate-800/80 text-slate-100': message.role === 'assistant' && !message.error,
            'border border-red-900/60 bg-red-950/40 text-red-200': message.error,
            'border border-slate-800 bg-slate-900/70 text-slate-400': message.role === 'system' && !message.error,
          }"
        >
          <ToolCallList v-if="message.toolCalls?.length" :calls="message.toolCalls" />
          {{ message.text }}
        </div>

        <!-- Статьи -->
        <div v-else-if="message.kind === 'articles'" class="w-full max-w-3xl">
          <p class="mb-2 text-center text-xs text-slate-400">{{ message.text }}</p>
          <div class="grid gap-2 md:grid-cols-2">
            <PostCard v-for="post in message.articles" :key="post.story_id" :post="post" />
          </div>
        </div>

        <!-- Справка по тулам -->
        <div v-else class="w-full max-w-3xl rounded-xl border border-slate-800 bg-slate-900/70 p-4">
          <p class="mb-3 text-sm font-medium text-slate-200">{{ message.text }}</p>
          <ul class="space-y-2">
            <li v-for="tool in message.tools" :key="tool.name" class="text-xs">
              <span class="font-mono text-emerald-300">{{ tool.name }}</span>
              <span class="text-slate-400"> — {{ tool.description }}</span>
            </li>
          </ul>
          <p class="mt-3 text-xs text-slate-500">
            Введите запрос обычным текстом — агент сам вызовет нужные тулы. Например: «Покажи юмор», «Саммари 5 статей», «Сохрани как txt».
          </p>
        </div>
      </div>

      <div v-if="busy" class="flex justify-start">
        <div class="rounded-2xl border border-slate-800 bg-slate-800/60 px-4 py-2 text-sm text-slate-400">
          <span class="animate-pulse">Агент думает и вызывает тулы…</span>
        </div>
      </div>
    </div>

    <div class="border-t border-slate-800 bg-slate-950/80 p-3">
      <div class="mb-2 flex flex-wrap gap-2">
        <button
          v-for="suggestion in suggestions"
          :key="suggestion"
          type="button"
          :disabled="busy"
          class="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 transition hover:border-indigo-500 hover:text-indigo-300 disabled:opacity-40"
          @click="useSuggestion(suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
      <div class="flex items-end gap-2">
        <textarea
          v-model="input"
          rows="2"
          :disabled="busy"
          placeholder="Спросите что-нибудь или введите /tools"
          class="flex-1 resize-none rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-indigo-500 disabled:opacity-50"
          @keydown="onKeydown"
        />
        <button
          type="button"
          :disabled="busy || !input.trim()"
          class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-40"
          @click="send"
        >
          Отправить
        </button>
      </div>
    </div>
  </div>
</template>
