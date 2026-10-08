import { ref } from 'vue'
import type { ChatInfo, LlmProvider, Post, RagRetrievalOptions } from './types'

/** Общий стор для связи вкладок: счётчик статей и версия данных (bump при очистке/парсинге). */
export const articlesCount = ref(0)
export const dataVersion = ref(0)

/** Спаршенные посты: грузит вкладка «MCP», читают и «MCP» (карточки), и «Чат» (карточки в ответах). */
export const posts = ref<Post[]>([])
export function setPosts(list: Post[]) {
  posts.value = list
  articlesCount.value = list.length
}

/** Версия обновления саммари: чат бампает после тулов саммаризации, «MCP» перезагружает блок. */
export const summaryVersion = ref(0)
export function bumpSummaryVersion() {
  summaryVersion.value += 1
}

// --- Чаты ---

const CURRENT_CHAT_KEY = 'pikabu-mcp-current-chat'

/** Список сохранённых чатов (свежие сверху); грузит вкладка «Чат». */
export const chats = ref<ChatInfo[]>([])
/** Активный чат; null — нового диалога ещё нет (создаётся при первом сообщении). */
export const currentChatId = ref<string | null>(localStorage.getItem(CURRENT_CHAT_KEY))

export function setChats(list: ChatInfo[]) {
  chats.value = list
}

export function setCurrentChatId(id: string | null) {
  currentChatId.value = id
  if (id) localStorage.setItem(CURRENT_CHAT_KEY, id)
  else localStorage.removeItem(CURRENT_CHAT_KEY)
}

/** Убирает чат из списка (после удаления на сервере). */
export function removeChat(id: string) {
  chats.value = chats.value.filter((chat) => chat.session_id !== id)
}

/** Поднимает чат наверх списка после новой реплики. */
export function touchChat(id: string) {
  const index = chats.value.findIndex((chat) => chat.session_id === id)
  if (index <= 0) return
  const list = [...chats.value]
  const [chat] = list.splice(index, 1)
  chats.value = [{ ...chat, updated_at: new Date().toISOString() }, ...list]
}

// --- RAG-настройки ---

const RAG_STRATEGY_KEY = 'pikabu-mcp-rag-strategy'
const RAG_RETRIEVAL_KEY = 'pikabu-mcp-rag-retrieval'

/** Выбранная стратегия RAG для вкладки «Чат»: '' — RAG выключен. */
export const ragStrategy = ref(localStorage.getItem(RAG_STRATEGY_KEY) ?? '')

/** Значения по умолчанию для стратегии поиска (top_k уточняется из config.rag.chat_top_k). */
export const DEFAULT_RAG_RETRIEVAL: RagRetrievalOptions = {
  strategy: 'baseline',
  top_k: 5,
  top_k_before: 20,
  top_k_after: 5,
  top_k_final: 5,
  similarity_threshold: 0.75,
  reranker_threshold_enabled: false,
  reranker_threshold: 0.5,
}

function loadRagRetrieval(): RagRetrievalOptions {
  const raw = localStorage.getItem(RAG_RETRIEVAL_KEY)
  if (raw) {
    try {
      return { ...DEFAULT_RAG_RETRIEVAL, ...(JSON.parse(raw) as Partial<RagRetrievalOptions>) }
    } catch {
      // повреждённое значение — значения по умолчанию
    }
  }
  return { ...DEFAULT_RAG_RETRIEVAL }
}

/** Есть ли сохранённые пользователем настройки стратегии поиска. */
export function hasStoredRagRetrieval(): boolean {
  return localStorage.getItem(RAG_RETRIEVAL_KEY) !== null
}

/** Настройки стратегии поиска RAG (Top_K, пороги, reranker). */
export const ragRetrieval = ref<RagRetrievalOptions>(loadRagRetrieval())

export function setArticlesCount(count: number) {
  articlesCount.value = count
}

export function bumpDataVersion(count = 0) {
  articlesCount.value = count
  dataVersion.value += 1
}

export function setRagStrategy(strategy: string) {
  ragStrategy.value = strategy
  localStorage.setItem(RAG_STRATEGY_KEY, strategy)
}

export function setRagRetrieval(options: RagRetrievalOptions) {
  ragRetrieval.value = { ...options }
  localStorage.setItem(RAG_RETRIEVAL_KEY, JSON.stringify(options))
}

// --- LLM-провайдер ---

const LLM_PROVIDER_KEY = 'pikabu-mcp-llm-provider'

/** Выбранный провайдер LLM для чата: 'deepseek' (облако) или 'ollama' (локальная модель). */
export const llmProvider = ref<LlmProvider>(
  (localStorage.getItem(LLM_PROVIDER_KEY) as LlmProvider | null) ?? 'deepseek',
)

export function setLlmProvider(provider: LlmProvider) {
  llmProvider.value = provider
  localStorage.setItem(LLM_PROVIDER_KEY, provider)
}
