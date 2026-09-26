<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { AppConfig, AppStatus, ThemeInfo, ToolInfo } from '../types'

const status = ref<AppStatus | null>(null)
const config = ref<AppConfig | null>(null)
const tools = ref<ToolInfo[]>([])
const themes = ref<ThemeInfo[]>([])
const error = ref<string | null>(null)
const busy = ref<'start' | 'stop' | 'run' | null>(null)
let timer: number | undefined

const coreTools = computed(() => tools.value.filter((tool) => !tool.name.startsWith('get_theme_')))
const themeTools = computed(() => tools.value.filter((tool) => tool.name.startsWith('get_theme_')))
const mcpUrl = computed(() => `${window.location.origin}/mcp`)
const summaryFile = computed(() => {
  const file = status.value?.parsing.last_summary_file
  return file ? file.split(/[\\/]/).pop() : null
})

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function refresh() {
  try {
    const [statusData, configData] = await Promise.all([api.getStatus(), api.getConfig()])
    status.value = statusData
    config.value = configData
    error.value = null
  } catch (err) {
    error.value = message(err)
  }
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

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ru-RU')
}

onMounted(() => {
  void refresh()
  void loadStatic()
  timer = window.setInterval(refresh, 5000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="h-full space-y-4 overflow-y-auto p-4">
    <div v-if="error" class="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
      {{ error }}
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
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
            <dt>LLM модель</dt>
            <dd class="font-mono text-slate-300">{{ config?.model ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>API-ключ LLM</dt>
            <dd :class="config?.llm_configured ? 'text-emerald-300' : 'text-amber-300'">
              {{ config?.llm_configured ? 'задан' : 'не задан (.env)' }}
            </dd>
          </div>
          <div class="flex justify-between gap-2">
            <dt>Исключённые темы</dt>
            <dd class="truncate text-slate-300">{{ config?.excluded_themes?.length ? config.excluded_themes.join(', ') : 'нет' }}</dd>
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
        </div>

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
            <dd class="truncate text-slate-300">{{ summaryFile ?? '—' }}</dd>
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
    </div>

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
              <td class="w-52 py-1.5 pr-3 align-top font-mono text-emerald-300">{{ tool.name }}</td>
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
              <td class="w-52 py-1.5 pr-3 align-top font-mono text-emerald-300">{{ tool.name }}</td>
              <td class="py-1.5 text-slate-400">{{ tool.short_description || tool.description }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>
  </div>
</template>
