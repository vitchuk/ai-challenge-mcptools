import { ref } from 'vue'

/** Общий стор для связи вкладок: счётчик статей и версия данных (bump при очистке/парсинге). */
export const articlesCount = ref(0)
export const dataVersion = ref(0)

export function setArticlesCount(count: number) {
  articlesCount.value = count
}

export function bumpDataVersion(count = 0) {
  articlesCount.value = count
  dataVersion.value += 1
}
