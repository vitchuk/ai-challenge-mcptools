<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { bumpDataVersion, posts, setPosts, summaryVersion } from '../store'
import type {
  AppConfig,
  AppStatus,
  McpServerInfo,
  ParsingStatus,
  SummaryData,
  ThemeInfo,
  ToolInfo,
} from '../types'
import PostCard from '../components/PostCard.vue'

const status = ref<AppStatus | null>(null)
const config = ref<AppConfig | null>(null)
const tools = ref<ToolInfo[]>([])
const themes = ref<ThemeInfo[]>([])
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const busy = ref<'start' | 'stop' | 'run' | 'clear' | null>(null)
const busyServer = ref<string | null>(null)

const parsing = ref<ParsingStatus | null>(null)
const parseError = ref<string | null>(null)
const waitingForParse = ref(false)
const countdownText = ref('')
const lastRunSeen = ref<string | null>(null)
let timer: number | undefined
let tickCount = 0

const summary = ref<SummaryData | null>(null)
const summaryFile = ref<string | null>(null)
const summaryFolder = ref<string | null>(null)
const showSummary = computed(() => posts.value.length > 0)

const servers = computed<McpServerInfo[]>(() => status.value?.servers ?? [])
const coreTools = computed(() =>
  tools.value.filter((tool) => (!tool.server || tool.server === 'pikabu') && !tool.name.startsWith('get_theme_')),
)
const themeTools = computed(() => tools.value.filter((tool) => tool.name.startsWith('get_theme_')))
const externalTools = computed(() => tools.value.filter((tool) => tool.server && tool.server !== 'pikabu'))
const mcpUrl = computed(() => `${window.location.origin}/mcp`)
const autoSummaryFile = computed(() => {
  const file = status.value?.parsing.last_summary_file
  return file ? file.split(/[\\/]/).pop() : null
})

function serverDot(server: McpServerInfo): string {
  if (server.connected) return 'bg-emerald-400'
  return 'bg-red-500'
}

function serverStateLabel(server: McpServerInfo): string {
  if (server.connected) return 'подключён'
  if (server.enabled) return 'запускается'
  return 'выключен'
}

async function toggleServer(server: McpServerInfo) {
  busyServer.value = server.name
  error.value = null
  try {
    if (server.enabled) await api.disableMcpServer(server.name)
    else await api.enableMcpServer(server.name)
    await refresh()
    await loadStatic()
  } catch (err) {
    error.value = message(err)
  } finally {
    busyServer.value = null
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function formatDuration(total: number): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`
}

async function loadPosts() {
  try {
    const data = await api.getArticles(500)
    setPosts(data.articles)
    if (data.count > 0) {
      waitingForParse.value = false
      await loadSummary()
    }
  } catch (err) {
    error.value = message(err)
  }
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

async function refresh() {
  try {
    const [statusData, configData] = await Promise.all([api.getStatus(), api.getConfig()])
    status.value = statusData
    config.value = configData
    parsing.value = statusData.parsing
    parseError.value = statusData.parsing.last_error
    if (statusData.articles_count > 0) {
      waitingForParse.value = false
      if (posts.value.length !== statusData.articles_count) {
        await loadPosts()
      }
    } else {
      if (posts.value.length) setPosts([])
      if (waitingForParse.value) {
        const run = statusData.parsing.last_run_at
        if (run && run !== lastRunSeen.value) {
          lastRunSeen.value = run
          waitingForParse.value = false
        }
      }
    }
    error.value = null
  } catch (err) {
    error.value = message(err)
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
  if (posts.value.length) {
    if (tickCount % 5 === 0) await refresh()
    return
  }
  updateCountdown()
  const every = waitingForParse.value ? 1 : 3
  if (tickCount % every === 0) await refresh()
}

async function loadStatic() {
  try {
    const [toolsData, themesData] = await Promise.all([api.getTools(), api.getThemes()])
    tools.value = toolsData.tools
    themes.value = themesData.themes
  } catch (err) {
    error.value = message(err)
  }
}

async function action(kind: 'start' | 'stop' | 'run') {
  busy.value = kind
  notice.value = null
  try {
    if (kind === 'start') await api.startParsing()
    if (kind === 'stop') await api.stopParsing()
    if (kind === 'run') await api.runNow()
    await refresh()
  } catch (err) {
    error.value = message(err)
  } finally {
    busy.value = null
  }
}

async function clearData() {
  if (!window.confirm('Удалить все статьи из БД, все саммари и файлы вывода MCP-серверов? Действие необратимо.')) return
  busy.value = 'clear'
  error.value = null
  notice.value = null
  try {
    const result = await api.clearData()
    bumpDataVersion(0)
    setPosts([])
    summary.value = null
    summaryFile.value = null
    summaryFolder.value = null
    waitingForParse.value = false
    countdownText.value = ''
    notice.value =
      `Данные очищены: статей ${result.cleared_articles}, саммари ${result.cleared_summaries}, файлов вывода MCP ${result.cleared_mcp_outputs}`
    await refresh()
  } catch (err) {
    error.value = message(err)
  } finally {
    busy.value = null
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ru-RU')
}

watch(summaryVersion, () => {
  void loadSummary()
})

onMounted(async () => {
  await Promise.all([refresh(), loadStatic()])
  timer = window.setInterval(tick, 1000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="flex h-full">
    <!-- Левая колонка: спаршенные посты -->
    <div class="h-full w-3/5 min-w-0 overflow-y-auto border-r border-slate-800 p-4">
      <div class="mx-auto w-full max-w-3xl">
        <div v-if="!posts.length" class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center">
          <p class="text-sm text-slate-300">Еще не спарсили</p>
          <div v-if="waitingForParse" class="mt-3 flex items-center justify-center gap-2 text-sm text-indigo-300">
            <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
            выполняется парсинг
          </div>
          <p v-else-if="parsing?.running" class="mt-3 text-sm text-slate-400">
            До следующего парсинга: <span class="font-mono text-slate-200">{{ countdownText }}</span>
          </p>
          <p v-else class="mt-3 text-sm text-amber-300">
            Парсинг остановлен — запустите его в панели справа.
          </p>
          <p v-if="parseError" class="mt-2 text-xs text-red-300">Ошибка парсинга: {{ parseError }}</p>
        </div>

        <template v-else>
          <p class="mb-2 text-center text-xs text-slate-400">В базе {{ posts.length }} статей из ленты /best:</p>
          <div class="grid gap-2 md:grid-cols-2">
            <PostCard v-for="post in posts" :key="post.story_id" :post="post" />
          </div>
        </template>
      </div>
    </div>

    <!-- Правая колонка: настройки MCP -->
    <div class="h-full w-2/5 shrink-0 space-y-4 overflow-y-auto bg-slate-950/40 p-4">
      <div v-if="error" class="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
        {{ error }}
      </div>

      <!-- Статус MCP -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Статус MCP-сервера</h2>
        <div class="flex items-center gap-2">
          <span
            class="inline-block h-2.5 w-2.5 rounded-full"
            :class="status?.mcp.connected ? 'bg-emerald-400' : 'bg-red-500'"
          />
          <span class="text-sm" :class="status?.mcp.connected ? 'text-emerald-300' : 'text-red-300'">
            {{ status?.mcp.connected ? 'Подключено' : 'Нет связи' }}
          </span>
        </div>
        <dl class="mt-3 space-y-1 text-xs text-slate-400">
          <div class="flex justify-between gap-2">
            <dt>URL</dt>
            <dd class="truncate font-mono text-slate-300">{{ mcpUrl }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Транспорт</dt>
            <dd class="text-slate-300">{{ status?.mcp.transport ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Тулов</dt>
            <dd class="text-slate-300">{{ status?.mcp.tools_count ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Тем</dt>
            <dd class="text-slate-300">{{ themes.length || '—' }}</dd>
          </div>
        </dl>
      </section>

      <!-- Конфигурация -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Конфигурация сервера</h2>
        <dl class="space-y-1 text-xs text-slate-400">
          <div class="flex justify-between gap-2">
            <dt>Интервал парсинга</dt>
            <dd class="text-slate-300">{{ config?.parse_interval_minutes ?? '—' }} мин</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Макс. статей в БД</dt>
            <dd class="text-slate-300">{{ config?.max_articles ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Статей за запрос</dt>
            <dd class="text-slate-300">{{ config?.posts_per_fetch ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Макс. возраст постов</dt>
            <dd class="text-slate-300">{{ config?.max_post_age_hours ?? '—' }} ч</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Автосаммари после парсинга</dt>
            <dd :class="config?.auto_summary_after_parse ? 'text-emerald-300' : 'text-slate-300'">
              {{ config?.auto_summary_after_parse ? 'вкл' : 'выкл' }}
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Кэш тем</dt>
            <dd class="text-slate-300">{{ config?.theme_cache_ttl_sec ?? '—' }} сек</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>LLM DeepSeek</dt>
            <dd class="font-mono text-slate-300">{{ config?.llm?.deepseek?.model ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Ключ DeepSeek</dt>
            <dd :class="config?.llm?.deepseek?.configured ? 'text-emerald-300' : 'text-amber-300'">
              {{ config?.llm?.deepseek?.configured ? 'задан' : 'не задан (.env)' }}
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>LLM Ollama</dt>
            <dd class="font-mono text-slate-300">{{ config?.llm?.ollama?.model ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Исключённые темы</dt>
            <dd class="truncate text-slate-300">{{ config?.excluded_themes?.length ? config.excluded_themes.join(', ') : 'нет' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Хосты для скриншотов</dt>
            <dd class="truncate text-slate-300">{{ config?.allowed_screenshot_hosts?.length ? config.allowed_screenshot_hosts.join(', ') : 'все' }}</dd>
          </div>
        </dl>
      </section>

      <!-- Управление парсингом -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Управление парсингом</h2>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            :disabled="busy !== null || status?.parsing.running"
            class="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:opacity-40"
            @click="action('start')"
          >
            {{ busy === 'start' ? 'Запуск…' : 'Старт' }}
          </button>
          <button
            type="button"
            :disabled="busy !== null || !status?.parsing.running"
            class="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-red-500 disabled:opacity-40"
            @click="action('stop')"
          >
            {{ busy === 'stop' ? 'Остановка…' : 'Стоп' }}
          </button>
          <button
            type="button"
            :disabled="busy !== null"
            class="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition hover:border-indigo-500 hover:text-indigo-300 disabled:opacity-40"
            @click="action('run')"
          >
            {{ busy === 'run' ? 'Парсим…' : 'Спарсить сейчас' }}
          </button>
          <button
            type="button"
            :disabled="busy !== null"
            class="rounded-lg border border-amber-800 px-3 py-2 text-sm text-amber-300 transition hover:border-amber-500 hover:text-amber-200 disabled:opacity-40"
            @click="clearData"
          >
            {{ busy === 'clear' ? 'Очистка…' : 'Очистить данные' }}
          </button>
        </div>

        <p v-if="notice" class="mt-3 rounded border border-emerald-900/60 bg-emerald-950/30 px-2 py-1 text-xs text-emerald-200">
          {{ notice }}
        </p>

        <dl class="mt-4 flex flex-col gap-1 text-xs text-slate-400">
          <div class="flex justify-between gap-2">
            <dt>Cron активен</dt>
            <dd :class="status?.parsing.running ? 'text-emerald-300' : 'text-slate-300'">
              {{ status?.parsing.running ? 'да' : 'нет' }}
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Статей в базе</dt>
            <dd class="text-slate-300">{{ status?.articles_count ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Последний парсинг</dt>
            <dd class="text-slate-300">{{ formatDate(status?.parsing.last_run_at ?? null) }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Следующий парсинг</dt>
            <dd class="text-slate-300">{{ formatDate(status?.parsing.next_run_at ?? null) }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Сохранено в последний раз</dt>
            <dd class="text-slate-300">{{ status?.parsing.last_parsed_count ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Новых в последний раз</dt>
            <dd class="text-slate-300">{{ status?.parsing.new_articles_last_run ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Последнее автосаммари</dt>
            <dd class="truncate text-slate-300">{{ autoSummaryFile ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Всего прогонов</dt>
            <dd class="text-slate-300">{{ status?.parsing.total_runs ?? '—' }}</dd>
          </div>
        </dl>

        <p v-if="status?.parsing.last_error" class="mt-3 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-200">
          Последняя ошибка парсинга: {{ status.parsing.last_error }}
        </p>
        <p v-if="status?.parsing.last_summary_error" class="mt-2 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-200">
          Ошибка автосаммари: {{ status.parsing.last_summary_error }}
        </p>
      </section>

      <!-- Саммари -->
      <section v-if="showSummary">
        <details class="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
          <summary class="cursor-pointer text-sm font-semibold text-slate-200">
            Саммари
            <span v-if="summaryFolder || summaryFile" class="ml-2 text-xs font-normal normal-case text-slate-500">{{ summaryFolder || summaryFile }}</span>
          </summary>
          <pre
            v-if="summary"
            class="mt-2 max-h-80 overflow-auto rounded bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-300"
          >{{ JSON.stringify(summary, null, 2) }}</pre>
          <p v-else class="mt-2 text-xs text-slate-500">Саммари ещё нет.</p>
        </details>
      </section>

      <!-- Внешние и встроенные MCP-серверы -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">MCP-серверы ({{ servers.length }})</h2>
        <ul class="space-y-2">
          <li
            v-for="server in servers"
            :key="server.name"
            class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2"
          >
            <div class="flex min-w-0 items-center gap-2">
              <span class="inline-block h-2.5 w-2.5 shrink-0 rounded-full" :class="serverDot(server)" />
              <div class="min-w-0">
                <p class="truncate text-sm text-slate-200">
                  <span class="font-medium">{{ server.name }}</span>
                  <span
                    v-if="server.builtin"
                    class="ml-2 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400"
                  >
                    встроенный
                  </span>
                </p>
                <p class="truncate text-xs" :class="server.last_error ? 'text-red-300' : 'text-slate-500'">
                  {{ server.last_error || server.description }}
                </p>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-3 text-xs">
              <span class="text-slate-400">тулов: {{ server.tools_count }}</span>
              <span :class="server.connected ? 'text-emerald-300' : 'text-red-300'">{{ serverStateLabel(server) }}</span>
              <button
                v-if="!server.builtin"
                type="button"
                :disabled="busyServer !== null"
                class="rounded-lg border px-3 py-1.5 text-xs transition disabled:opacity-40"
                :class="server.enabled
                  ? 'border-red-800 text-red-300 hover:border-red-500 hover:text-red-200'
                  : 'border-emerald-800 text-emerald-300 hover:border-emerald-500 hover:text-emerald-200'"
                @click="toggleServer(server)"
              >
                {{ busyServer === server.name ? 'Ждите…' : server.enabled ? 'Выключить' : 'Включить' }}
              </button>
            </div>
          </li>
        </ul>
      </section>

      <!-- Тулы -->
      <section class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 class="mb-3 text-sm font-semibold text-slate-200">Тулы MCP ({{ tools.length }})</h2>

        <details class="mt-2">
          <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-500">
            Базовые ({{ coreTools.length }})
          </summary>
          <table class="mt-2 w-full text-left text-xs">
            <tbody>
              <tr v-for="tool in coreTools" :key="tool.name" class="border-t border-slate-800/60">
                <td class="w-44 py-1.5 pr-3 align-top font-mono text-emerald-300">{{ tool.name }}</td>
                <td class="py-1.5 text-slate-400">{{ tool.description }}</td>
              </tr>
            </tbody>
          </table>
        </details>

        <details class="mt-4">
          <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-500">
            Темы ({{ themeTools.length }}) — get_theme_*
          </summary>
          <table class="mt-2 w-full text-left text-xs">
            <tbody>
              <tr v-for="tool in themeTools" :key="tool.name" class="border-t border-slate-800/60">
                <td class="w-44 py-1.5 pr-3 align-top font-mono text-emerald-300">{{ tool.name }}</td>
                <td class="py-1.5 text-slate-400">{{ tool.short_description || tool.description }}</td>
              </tr>
            </tbody>
          </table>
        </details>

        <details v-if="externalTools.length" class="mt-4">
          <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-500">
            Внешние MCP-серверы ({{ externalTools.length }})
          </summary>
          <table class="mt-2 w-full text-left text-xs">
            <tbody>
              <tr v-for="tool in externalTools" :key="tool.name" class="border-t border-slate-800/60">
                <td class="w-44 py-1.5 pr-3 align-top font-mono text-emerald-300">
                  {{ tool.name }}
                  <span class="mt-0.5 block font-sans text-[10px] uppercase tracking-wide text-slate-500">
                    сервер: {{ tool.server }}
                  </span>
                </td>
                <td class="py-1.5 text-slate-400">{{ tool.description }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </section>
    </div>
  </div>
</template>
