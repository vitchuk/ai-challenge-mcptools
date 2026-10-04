/** Разбор цитат из ответа LLM и подсветка процитированных фрагментов в тексте чанка. */

export interface RagCitation {
  chunkId: string
  quote: string
}

/** Строка вида `> [fixed_006] дословная цитата` — требование к LLM в RAG_SYSTEM_PROMPT. */
const CITATION_RE = /^>+\s*\[([A-Za-z0-9_]+)\]\s*(.+)$/

export function parseRagCitations(reply: string): RagCitation[] {
  const result: RagCitation[] = []
  for (const raw of (reply || '').split('\n')) {
    const match = CITATION_RE.exec(raw.trim())
    if (!match) continue
    const quote = match[2].trim()
    if (quote) result.push({ chunkId: match[1], quote })
  }
  return result
}

export interface HighlightSegment {
  text: string
  highlight: boolean
}

const norm = (value: string) => value.replace(/\s+/g, ' ').trim()

/**
 * Ищет quotes в text и разбивает его на сегменты (без v-html).
 * Сначала точное совпадение, затем — с нормализацией пробелов (LLM мог их поправить).
 */
export function splitHighlighted(text: string, quotes: string[]): HighlightSegment[] {
  const ranges: Array<[number, number]> = []
  const normalizedQuotes = quotes
    .filter((quote) => norm(quote).length >= 4)
    .sort((a, b) => b.length - a.length)

  for (const quote of normalizedQuotes) {
    const range = findQuoteRange(text, quote, ranges)
    if (range) ranges.push(range)
  }

  if (!ranges.length) return [{ text, highlight: false }]
  ranges.sort((a, b) => a[0] - b[0])

  const segments: HighlightSegment[] = []
  let cursor = 0
  for (const [start, end] of ranges) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), highlight: false })
    segments.push({ text: text.slice(start, end), highlight: true })
    cursor = end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), highlight: false })
  return segments
}

function findQuoteRange(
  text: string,
  quote: string,
  taken: Array<[number, number]>,
): [number, number] | null {
  const overlaps = (start: number, end: number) =>
    taken.some(([from, to]) => start < to && end > from)

  const exact = text.indexOf(quote)
  if (exact >= 0 && !overlaps(exact, exact + quote.length)) {
    return [exact, exact + quote.length]
  }

  // Fallback: ищем по тексту с нормализованными пробелами, сопоставляя индексы обратно.
  const map: number[] = []
  let normalized = ''
  let pendingSpace = false
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (/\s/.test(char)) {
      pendingSpace = normalized.length > 0
      continue
    }
    if (pendingSpace) {
      normalized += ' '
      map.push(i)
      pendingSpace = false
    }
    normalized += char
    map.push(i)
  }
  normalized = normalized.trimEnd()

  const start = normalized.indexOf(quote)
  if (start < 0) return null
  const endIndex = start + quote.length - 1
  if (endIndex >= map.length) return null
  const startChar = map[start]
  const endChar = map[endIndex] + 1
  if (overlaps(startChar, endChar)) return null
  return [startChar, endChar]
}
