import { ref } from 'vue'

/** Общий стор для связи вкладок: счётчик статей и версия данных (bump при очистке/парсинге). */
export const articlesCount = ref(0)
export const dataVersion = ref(0)

const RAG_STRATEGY_KEY = 'pikabu-mcp-rag-strategy'

/** Выбранная стратегия RAG для вкладки «Чат»: '' — RAG выключен. */
export const ragStrategy = ref(localStorage.getItem(RAG_STRATEGY_KEY) ?? '')
/** Версия смены стратегии RAG: вкладка «Чат» по ней очищает историю диалога. */
export const ragVersion = ref(0)

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
  ragVersion.value += 1
}
