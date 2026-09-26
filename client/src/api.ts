import type {
  AppConfig,
  AppStatus,
  ArticlesResponse,
  ChatResponse,
  ClearDataResponse,
  LatestSummaryResponse,
  ParsingStatus,
  ThemesResponse,
  ToolsResponse,
} from './types'

const SESSION_KEY = 'pikabu-mcp-session-id'

export function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Session-Id': getSessionId(),
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`)
  }
  return (await response.json()) as T
}

export const api = {
  getStatus: () => request<AppStatus>('/api/status'),
  getConfig: () => request<AppConfig>('/api/config'),
  getArticles: (limit = 100) => request<ArticlesResponse>(`/api/articles?limit=${limit}`),
  getTools: () => request<ToolsResponse>('/api/tools'),
  getThemes: () => request<ThemesResponse>('/api/themes'),
  startParsing: () => request<ParsingStatus>('/api/parsing/start', { method: 'POST' }),
  stopParsing: () => request<ParsingStatus>('/api/parsing/stop', { method: 'POST' }),
  runNow: () => request<Record<string, unknown>>('/api/parsing/run-now', { method: 'POST' }),
  clearData: () => request<ClearDataResponse>('/api/parsing/clear-data', { method: 'POST' }),
  getLatestSummary: () => request<LatestSummaryResponse>('/api/summary/latest'),
  sendChat: (message: string) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message, session_id: getSessionId() }),
    }),
}
