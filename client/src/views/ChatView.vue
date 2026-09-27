<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { dataVersion } from '../store'
import type { ChatMessage, ParsingStatus, Post, SummaryData, ToolCallEvent, ToolInfo } from '../types'
import PostCard from '../components/PostCard.vue'
import ToolCallList from '../components/ToolCallList.vue'
import AgentReply from '../components/AgentReply.vue'

const messages = ref<ChatMessage[]>([])
const input = ref('')
const busy = ref(false)
const listEl = ref<HTMLElement | null>(null)
const postStore = ref<Record<string, Post>>({})
let nextId = 1

const articles = ref<Post[]>([])
const hasArticles = ref(false)
const parsing = ref<ParsingStatus | null>(null)
const parseError = ref<string | null>(null)
const waitingForParse = ref(false)
const countdownText = ref('')
const lastRunSeen = ref<string | null>(null)

const summary = ref<SummaryData | null>(null)
const summaryFile = ref<string | null>(null)
const summaryFolder = ref<string | null>(null)
const showSummary = computed(() => hasArticles.value)

let tickTimer: number | undefined
let tickCount = 0

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

function formatDuration(total: number): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`
}

async function loadSummary() {
  try {
    const data = await api.getLatestSummary()
    summary.value = data.summary
    summaryFile.value = data.file
    summaryFolder.value = data.folder
  } catch {
    summary.value = null
    summaryFile.value = null
    summaryFolder.value = null
  }
}

async function loadArticles() {
  const data = await api.getArticles(500)
  articles.value = data.articles
  if (data.count > 0) {
    hasArticles.value = true
    waitingForParse.value = false
    indexPosts(data.articles)
    await loadSummary()
  } else {
    hasArticles.value = false
    articles.value = []
  }
}

async function refreshStatus() {
  try {
    const data = await api.getStatus()
    parsing.value = data.parsing
    parseError.value = data.parsing.last_error
    if (data.articles_count > 0) {
      waitingForParse.value = false
      if (!hasArticles.value || data.articles_count !== articles.value.length) {
        await loadArticles()
      }
    } else if (waitingForParse.value) {
      const run = data.parsing.last_run_at
      if (run && run !== lastRunSeen.value) {
        lastRunSeen.value = run
        waitingForParse.value = false
      }
    }
  } catch (error) {
    parseError.value = errorText(error)
  }
}

function updateCountdown() {
  const current = parsing.value
  if (!current?.running || !current.next_run_at) {
    countdownText.value = ''
    return
  }
  const diff = Math.floor((new Date(current.next_run_at).getTime() - Date.now()) / 1000)
  if (diff <= 0) {
    countdownText.value = '00:00'
    if (!waitingForParse.value) {
      waitingForParse.value = true
      lastRunSeen.value = current.last_run_at ?? null
    }
  } else {
    countdownText.value = formatDuration(diff)
  }
}

async function tick() {
  tickCount += 1
  if (hasArticles.value) {
    if (tickCount % 5 === 0) await refreshStatus()
    return
  }
  updateCountdown()
  const every = waitingForParse.value ? 1 : 3
  if (tickCount % every === 0) await refreshStatus()
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
    indexToolResults(response.tool_calls)
    addMessage({
      role: 'assistant',
      kind: 'text',
      text: response.reply,
      toolCalls: response.tool_calls,
      error: Boolean(response.error),
    })
    if (response.tool_calls.some((call) => call.name === 'summarize_best_posts' || call.name === 'save_summary')) {
      await loadSummary()
    }
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

watch(dataVersion, async () => {
  articles.value = []
  hasArticles.value = false
  postStore.value = {}
  summary.value = null
  summaryFile.value = null
  summaryFolder.value = null
  waitingForParse.value = false
  await refreshStatus()
})

onMounted(async () => {
  await refreshStatus()
  tickTimer = window.setInterval(tick, 1000)
})

onUnmounted(() => {
  if (tickTimer) window.clearInterval(tickTimer)
})
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Саммари по текущим карточкам -->
    <div v-if="showSummary" class="border-b border-slate-800 bg-slate-950/60 px-4 py-2">
      <div class="mx-auto w-full max-w-3xl">
        <details class="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
          <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-400">
            Саммари
            <span v-if="summaryFolder || summaryFile" class="ml-2 normal-case text-slate-500">{{ summaryFolder || summaryFile }}</span>
          </summary>
          <pre
            v-if="summary"
            class="mt-2 max-h-80 overflow-auto rounded bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-300"
          >{{ JSON.stringify(summary, null, 2) }}</pre>
          <p v-else class="mt-2 text-xs text-slate-500">Саммари ещё нет.</p>
        </details>
      </div>
    </div>

    <div ref="listEl" class="flex-1 overflow-y-auto p-4">
      <div class="mx-auto w-full max-w-3xl space-y-3">
        <!-- Заглушка: нет статей -->
        <div v-if="!hasArticles" class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center">
          <p class="text-sm text-slate-300">Еще не спарсили</p>
          <div v-if="waitingForParse" class="mt-3 flex items-center justify-center gap-2 text-sm text-indigo-300">
            <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
            выполняется парсинг
          </div>
          <p v-else-if="parsing?.running" class="mt-3 text-sm text-slate-400">
            До следующего парсинга: <span class="font-mono text-slate-200">{{ countdownText }}</span>
          </p>
          <p v-else class="mt-3 text-sm text-amber-300">
            Парсинг остановлен — запустите его на вкладке MCP.
          </p>
          <p v-if="parseError" class="mt-2 text-xs text-red-300">Ошибка парсинга: {{ parseError }}</p>
        </div>

        <!-- Карточки статей -->
        <div v-else>
          <p class="mb-2 text-center text-xs text-slate-400">В базе {{ articles.length }} статей из ленты /best:</p>
          <div class="grid gap-2 md:grid-cols-2">
            <PostCard v-for="post in articles" :key="post.story_id" :post="post" />
          </div>
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
            <span class="animate-pulse">Агент думает и вызывает тулы…</span>
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
  </div>
</template>
