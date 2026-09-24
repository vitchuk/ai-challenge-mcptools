export interface Post {
  story_id: number
  title: string
  url: string
  author: string | null
  theme: string | null
  tags: string[]
  rating: number | null
  comments_count: number | null
  body_text: string
  images: string[]
  videos: string[]
  published_at: string | null
  parsed_at: string
}

export interface ToolInfo {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface ThemeInfo {
  slug: string
  title: string
}

export interface ParsingStatus {
  running: boolean
  interval_minutes: number
  next_run_at: string | null
  last_run_at: string | null
  last_error: string | null
  last_parsed_count: number | null
  total_runs: number
}

export interface AppStatus {
  mcp: {
    connected: boolean
    endpoint: string
    transport: string
    tools_count: number
  }
  parsing: ParsingStatus
  articles_count: number
  last_parsed_at: string | null
  llm: {
    model: string
    configured: boolean
  }
}

export interface AppConfig {
  parse_interval_minutes: number
  max_articles: number
  posts_per_fetch: number
  pikabu_best_url: string
  pikabu_themes_url: string
  theme_cache_ttl_sec: number
  excluded_themes: string[]
  autostart_parsing: boolean
  model: string
  llm_configured: boolean
  chat_max_iterations: number
  chat_rate_limit_per_minute: number
  chat_max_message_chars: number
}

export interface ToolCallEvent {
  name: string
  arguments: Record<string, unknown>
  result_preview: string
}

export interface ChatResponse {
  reply: string
  tool_calls: ToolCallEvent[]
  error?: string
}

export interface ArticlesResponse {
  count: number
  articles: Post[]
}

export interface ToolsResponse {
  count: number
  tools: ToolInfo[]
}

export interface ThemesResponse {
  count: number
  themes: ThemeInfo[]
}

export type MessageRole = 'user' | 'assistant' | 'system'
export type MessageKind = 'text' | 'articles' | 'tools'

export interface ChatMessage {
  id: number
  role: MessageRole
  kind: MessageKind
  text: string
  articles?: Post[]
  tools?: ToolInfo[]
  toolCalls?: ToolCallEvent[]
  error?: boolean
}
