/** Разбор ссылок в ответах LLM: короткие подписи и распознавание голых URL. */

const URL_RE = /(?:https?:\/\/|www\.)[^\s<>"«»()]+/gi
const TRAILING_PUNCT_RE = /[.,;:!?…»)"']+$/
const MAX_LABEL_LENGTH = 40

export interface LinkifiedPart {
  text: string
  href?: string
}

export function looksLikeUrl(value: string): boolean {
  return /^(https?:\/\/|www\.)/i.test(value.trim())
}

/** Короткая подпись для ссылки: «статья» для постов pikabu, иначе домен. */
export function shortLinkLabel(href: string, label?: string): string {
  const cleanLabel = (label ?? '').trim()
  if (cleanLabel && !looksLikeUrl(cleanLabel) && cleanLabel.length <= MAX_LABEL_LENGTH) {
    return cleanLabel
  }
  try {
    const url = new URL(/^www\./i.test(href) ? `https://${href}` : href)
    const host = url.hostname.replace(/^www\./i, '')
    if (host === 'pikabu.ru' || host.endsWith('.pikabu.ru')) {
      return /\/story\//.test(url.pathname) ? 'статья' : 'pikabu.ru'
    }
    return host || 'ссылка'
  } catch {
    return 'ссылка'
  }
}

/** Разбивает текст на фрагменты и ссылки: голые URL → кликабельная короткая метка. */
export function linkifyText(text: string): LinkifiedPart[] {
  const parts: LinkifiedPart[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  URL_RE.lastIndex = 0
  while ((match = URL_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ text: text.slice(lastIndex, match.index) })
    }
    let href = match[0]
    const trailing = href.match(TRAILING_PUNCT_RE)?.[0] ?? ''
    if (trailing) href = href.slice(0, -trailing.length)
    if (href) {
      parts.push({ text: shortLinkLabel(href), href })
    }
    if (trailing) {
      parts.push({ text: trailing })
    }
    lastIndex = URL_RE.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push({ text: text.slice(lastIndex) })
  }
  return parts.filter((part) => part.text.length > 0)
}
