import type {
  AppConfig,
  AppStatus,
  ArticlesResponse,
  ChatsResponse,
  ChatHistoryResponse,
  ChatResponse,
  ChatStreamEvent,
  ClearDataResponse,
  LatestSummaryResponse,
  LlmLogResponse,
  LlmProvider,
  McpServerInfo,
  ParsingStatus,
  RagRetrievalOptions,
  RagStrategiesResponse,
  ThemesResponse,
  ToolCallEvent,
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

/** Колбэки рантайм-событий стрима чата. */
export interface ChatStreamHandlers {
  onThinking?: (delta: string) => void
  onTool?: (event: ToolCallEvent) => void
}

function chatBody(
  message: string,
  sessionId: string,
  ragStrategy?: string,
  ragOptions?: RagRetrievalOptions,
  llmProvider?: LlmProvider,
): string {
  return JSON.stringify({
    message,
    session_id: sessionId,
    rag_strategy: ragStrategy || null,
    llm_provider: llmProvider ?? null,
    rag_options: ragOptions
      ? {
          strategy: ragOptions.strategy,
          top_k: ragOptions.top_k,
          top_k_before: ragOptions.top_k_before,
          top_k_after: ragOptions.top_k_after,
          top_k_final: ragOptions.top_k_final,
          similarity_threshold: ragOptions.similarity_threshold,
          reranker_threshold: ragOptions.reranker_threshold_enabled
            ? ragOptions.reranker_threshold
            : null,
        }
      : null,
  })
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
  enableMcpServer: (name: string) =>
    request<McpServerInfo>(`/api/mcp-servers/${encodeURIComponent(name)}/enable`, { method: 'POST' }),
  disableMcpServer: (name: string) =>
    request<McpServerInfo>(`/api/mcp-servers/${encodeURIComponent(name)}/disable`, { method: 'POST' }),
  sendChat: (
    message: string,
    sessionId: string,
    ragStrategy?: string,
    ragOptions?: RagRetrievalOptions,
    llmProvider?: LlmProvider,
  ) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: chatBody(message, sessionId, ragStrategy, ragOptions, llmProvider),
    }),
  sendChatStream: async (
    message: string,
    sessionId: string,
    handlers: ChatStreamHandlers,
    ragStrategy?: string,
    ragOptions?: RagRetrievalOptions,
    llmProvider?: LlmProvider,
  ): Promise<ChatResponse> => {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Session-Id': getSessionId(),
      },
      body: chatBody(message, sessionId, ragStrategy, ragOptions, llmProvider),
    })
    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => '')
      throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let final: ChatResponse | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const line = frame.split('\n').find((item) => item.startsWith('data:'))
        if (!line) continue
        const event = JSON.parse(line.slice(5).trim()) as ChatStreamEvent
        if (event.type === 'thinking') handlers.onThinking?.(event.delta)
        else if (event.type === 'tool') handlers.onTool?.(event.event)
        else if (event.type === 'reply') final = event
      }
    }
    if (!final) throw new Error('Пустой ответ стрима')
    return final
  },
  getLlmLog: (limit = 50) => request<LlmLogResponse>(`/api/llm-log?limit=${limit}`),
  clearLlmLog: () => request<{ cleared: number }>('/api/llm-log/clear', { method: 'POST' }),
  getChatHistory: (sessionId: string) =>
    request<ChatHistoryResponse>(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}`),
  getChats: () => request<ChatsResponse>('/api/chats'),
  deleteChat: (sessionId: string) =>
    request<{ ok: boolean; session_id: string }>(
      `/api/chats/${encodeURIComponent(sessionId)}/delete`,
      { method: 'POST' },
    ),
  getRagStrategies: () => request<RagStrategiesResponse>('/api/rag/strategies'),
}
