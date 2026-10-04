<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { parseRagCitations } from '../citations'
import {
  bumpSummaryVersion,
  chats,
  currentChatId,
  posts,
  ragRetrieval,
  ragStrategy,
  removeChat,
  setChats,
  setCurrentChatId,
  touchChat,
} from '../store'
import type { ChatMessage, Post, TaskState, ToolCallEvent, ToolInfo } from '../types'
import ToolCallList from '../components/ToolCallList.vue'
import AgentReply from '../components/AgentReply.vue'
import RagSources from '../components/RagSources.vue'
import RagPipelineInfo from '../components/RagPipelineInfo.vue'
import RagSettingsPanel from '../components/RagSettingsPanel.vue'
import TaskStatePanel from '../components/TaskStatePanel.vue'
import ChatTabs from '../components/ChatTabs.vue'

const RETRIEVAL_LABELS: Record<string, string> = {
  baseline: 'Baseline',
  'query-rewrite': 'Query Rewrite',
  'similarity-filter': 'Similarity Filter',
  'query-rewrite-rerank': 'Query Rewrite + Reranker',
}

const retrievalLabel = computed(
  () => RETRIEVAL_LABELS[ragRetrieval.value.strategy] ?? ragRetrieval.value.strategy,
)

const inputPlaceholder = computed(() =>
  currentChatId.value ? 'Спросите что-нибудь или введите /tools' : 'Сообщение начнёт новый чат…',
)

const messages = ref<ChatMessage[]>([])
const input = ref('')
const busy = ref(false)
const listEl = ref<HTMLElement | null>(null)
const postStore = ref<Record<string, Post>>({})
const taskState = ref<TaskState | null>(null)
let nextId = 1

const suggestions = [
  '/tools',
  'Покажи статьи из базы',
  'Сделай саммари последних 5 статей',
  'Сделай саммари 3 постов со скриншотами',
  'Сохрани саммари как json',
  'Что нового в теме IT?',
]

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function indexPosts(posts: Post[] | undefined) {
  if (!Array.isArray(posts)) return
  for (const post of posts) {
    if (post?.url) postStore.value[post.url] = post
  }
}

function indexToolResults(calls: ToolCallEvent[]) {
  for (const call of calls) {
    if (!call.result) continue
    try {
      const data = JSON.parse(call.result) as { articles?: Post[]; posts?: Post[] }
      indexPosts(data.articles)
      indexPosts(data.posts)
    } catch {
      // результат не JSON — пропускаем
    }
  }
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

async function refreshChats() {
  try {
    const data = await api.getChats()
    setChats(data.chats)
  } catch {
    // список чатов недоступен — не критично
  }
}

async function loadChat(id: string) {
  setCurrentChatId(id)
  messages.value = []
  taskState.value = null
  try {
    const data = await api.getChatHistory(id)
    taskState.value = data.task_state
    messages.value = data.messages.map((message) => ({
      id: nextId++,
      role: message.role,
      kind: 'text' as const,
      text: message.content,
      citations: message.role === 'assistant' ? parseRagCitations(message.content) : [],
    }))
    await scrollDown()
  } catch {
    // история недоступна — начинаем с пустого диалога
  }
}

function newChat() {
  setCurrentChatId(null)
  messages.value = []
  taskState.value = null
}

async function selectChat(id: string) {
  if (busy.value || id === currentChatId.value) return
  await loadChat(id)
}

async function deleteChat(id: string) {
  const chat = chats.value.find((item) => item.session_id === id)
  const title = chat?.title ?? 'без названия'
  if (!window.confirm(`Удалить чат «${title}»? История и память задачи будут удалены безвозвратно.`)) return
  try {
    await api.deleteChat(id)
  } catch (error) {
    addMessage({ role: 'assistant', kind: 'text', text: `Не удалось удалить чат: ${errorText(error)}`, error: true })
    return
  }
  removeChat(id)
  if (id === currentChatId.value) {
    const next = chats.value[0]
    if (next) await loadChat(next.session_id)
    else newChat()
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  input.value = ''

  if (text === '/tools') {
    addMessage({ role: 'user', kind: 'text', text })
    await showToolsHelp()
    return
  }

  // чат создаётся лениво: id генерируется при первом сообщении
  const isNewChat = !currentChatId.value
  const chatId = currentChatId.value ?? crypto.randomUUID()
  if (isNewChat) setCurrentChatId(chatId)
  addMessage({ role: 'user', kind: 'text', text })

  const isRag = Boolean(ragStrategy.value)
  busy.value = true
  try {
    const response = await api.sendChat(
      text,
      chatId,
      ragStrategy.value || undefined,
      ragStrategy.value ? ragRetrieval.value : undefined,
    )
    indexToolResults(response.tool_calls)
    if (response.task_state) taskState.value = response.task_state
    addMessage({
      role: 'assistant',
      kind: 'text',
      text: response.reply,
      toolCalls: response.tool_calls,
      chunks: response.chunks,
      citations: response.chunks?.length ? parseRagCitations(response.reply) : [],
      ragDebug: response.debug,
      rag: isRag && !response.error,
      taskState: response.task_state ?? null,
      error: Boolean(response.error),
    })
    if (response.tool_calls.some((call) => call.name === 'summarize_best_posts' || call.name === 'save_summary')) {
      bumpSummaryVersion()
    }
    if (isNewChat) await refreshChats()
    else touchChat(chatId)
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

watch(
  posts,
  (list) => {
    // общие посты (грузит вкладка «MCP») — индекс для встроенных карточек в ответах
    postStore.value = {}
    indexPosts(list)
  },
  { immediate: true },
)

onMounted(async () => {
  await refreshChats()
  const saved = currentChatId.value
  const target =
    saved && chats.value.some((chat) => chat.session_id === saved)
      ? saved
      : chats.value[0]?.session_id ?? null
  if (target) await loadChat(target)
  else newChat()
})
</script>

<template>
  <div class="flex h-full">
    <!-- Левая колонка: список чатов -->
    <aside class="h-full w-60 shrink-0 border-r border-slate-800">
      <ChatTabs
        :chats="chats"
        :current-chat-id="currentChatId"
        :busy="busy"
        @select="selectChat"
        @delete="deleteChat"
        @new="newChat"
      />
    </aside>

    <!-- Колонка чата -->
    <div class="flex h-full min-w-0 flex-1 flex-col">
      <div ref="listEl" class="flex-1 overflow-y-auto p-4">
        <div class="mx-auto w-full max-w-3xl space-y-3">
          <!-- Индикатор RAG-режима -->
          <div
            v-if="ragStrategy"
            class="rounded-lg border border-indigo-900/60 bg-indigo-950/30 px-3 py-1.5 text-xs text-indigo-200"
          >
            RAG включён: индекс <span class="font-mono text-indigo-100">{{ ragStrategy }}</span>, поиск
            <span class="text-indigo-100">{{ retrievalLabel }}</span> — ответы строятся по найденным чанкам.
            Сменить стратегию можно на панели справа.
          </div>

          <!-- Память задачи (цель / уточнения / ограничения) -->
          <TaskStatePanel v-if="ragStrategy && taskState" :state="taskState" />

          <!-- Пустое состояние: чат не выбран -->
          <div
            v-if="!currentChatId && !messages.length"
            class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center"
          >
            <p class="text-sm text-slate-300">Выберите чат слева или начните новый</p>
            <p class="mt-2 text-xs text-slate-500">Первое отправленное сообщение создаст новый чат.</p>
          </div>

          <!-- Сообщения чата -->
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
            <div
              v-if="message.kind === 'text'"
              class="max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed"
              :class="{
                'bg-indigo-600 whitespace-pre-wrap text-white': message.role === 'user',
                'border border-slate-800 bg-slate-800/80 text-slate-100': message.role === 'assistant' && !message.error,
                'border border-red-900/60 bg-red-950/40 text-red-200': message.error,
                'border border-slate-800 bg-slate-900/70 whitespace-pre-wrap text-slate-400': message.role === 'system' && !message.error,
              }"
            >
              <ToolCallList v-if="message.toolCalls?.length" :calls="message.toolCalls" />
              <AgentReply v-if="message.role === 'assistant' && !message.error" :text="message.text" :posts="postStore" />
              <template v-else>{{ message.text }}</template>
              <RagPipelineInfo v-if="message.ragDebug" :debug="message.ragDebug" />
              <RagSources
                v-if="message.rag"
                :chunks="message.chunks ?? []"
                :citations="message.citations"
              />
            </div>

            <div v-else class="w-full rounded-xl border border-slate-800 bg-slate-900/70 p-4">
              <p class="mb-3 text-sm font-medium text-slate-200">{{ message.text }}</p>
              <ul class="space-y-2">
                <li v-for="tool in message.tools" :key="tool.name" class="text-xs">
                  <span class="font-mono text-emerald-300">{{ tool.name }}</span>
                  <span class="text-slate-400"> — {{ tool.short_description || tool.description }}</span>
                </li>
              </ul>
              <p class="mt-3 text-xs text-slate-500">
                Введите запрос обычным текстом — агент сам вызовет нужные тулы. Например: «Покажи юмор», «Саммари 5 статей», «Сохрани как txt».
              </p>
            </div>
          </div>

          <div v-if="busy" class="flex justify-start">
            <div class="rounded-2xl border border-slate-800 bg-slate-800/60 px-4 py-2 text-sm text-slate-400">
              <span class="animate-pulse">
                {{ ragStrategy ? 'Ищу релевантные чанки и формирую ответ…' : 'Агент думает и вызывает тулы…' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="border-t border-slate-800 bg-slate-950/80 p-3">
        <div class="mx-auto w-full max-w-3xl">
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
              :placeholder="inputPlaceholder"
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
    </div>

    <!-- Сайтбар с настройками RAG (1/3 ширины окна) -->
    <aside class="h-full w-1/3 shrink-0 overflow-y-auto bg-slate-950/40 p-4">
      <RagSettingsPanel />
    </aside>
  </div>
</template>
