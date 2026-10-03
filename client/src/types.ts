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
  short_description?: string | null
  parameters: Record<string, unknown>
  server?: string | null
}

export interface McpServerInfo {
  name: string
  description?: string | null
  builtin: boolean
  enabled: boolean
  connected: boolean
  tools_count: number
  tools: string[]
  last_error: string | null
  output_dir: string | null
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
  new_articles_last_run: number | null
  last_summary_file: string | null
  last_summary_error: string | null
  total_runs: number
}

export interface AppStatus {
  mcp: {
    connected: boolean
    endpoint: string
    transport: string
    tools_count: number
  }
  servers: McpServerInfo[]
  parsing: ParsingStatus
  articles_count: number
  last_parsed_at: string | null
  llm: {
    model: string
    configured: boolean
  }
}

export interface ExternalMcpServerConfig {
  name: string
  description?: string | null
  enabled_by_default: boolean
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
  max_post_age_hours: number
  auto_summary_after_parse: boolean
  model: string
  llm_configured: boolean
  chat_max_iterations: number
  chat_rate_limit_per_minute: number
  chat_max_message_chars: number
  allowed_screenshot_hosts: string[]
  external_mcp_servers: ExternalMcpServerConfig[]
  rag: {
    source_file: string
    ollama_base_url: string
    embedding_model: string
    min_tokens: number
    max_tokens: number
    chat_top_k: number
  }
}

export interface ToolCallEvent {
  name: string
  arguments: Record<string, unknown>
  result_preview: string
  result?: string
}

export interface ChatResponse {
  reply: string
  tool_calls: ToolCallEvent[]
  chunks?: RagChunkHit[]
  debug?: RagPipelineDebug | null
  error?: string
}

export interface ArticlesResponse {
  count: number
  articles: Post[]
}

export interface SummaryData {
  title: string
  summary: string
  images: string[]
  videos: string[]
  posts?: { title: string; url: string }[]
  source_count: number
  created_at: string
}

export interface LatestSummaryResponse {
  exists: boolean
  file: string | null
  folder: string | null
  summary: SummaryData | null
}

export interface ClearDataResponse {
  cleared_articles: number
  cleared_summaries: number
  cleared_mcp_outputs: number
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
export type MessageKind = 'text' | 'tools'

export interface ChatMessage {
  id: number
  role: MessageRole
  kind: MessageKind
  text: string
  tools?: ToolInfo[]
  toolCalls?: ToolCallEvent[]
  chunks?: RagChunkHit[]
  ragDebug?: RagPipelineDebug | null
  error?: boolean
}

export interface RagStrategyInfo {
  strategy: string
  description: string | null
  chunks: number
  tokens_min: number
  tokens_max: number
  tokens_avg: number
  articles: number | null
  has_embeddings: boolean
  embedding_model: string | null
  embedding_dim: number | null
  built_at: string | null
  params: Record<string, number> | null
}

export interface RagStrategiesResponse {
  strategies: RagStrategyInfo[]
  retrieval_strategies?: { id: string; description: string }[]
}

/** Стратегии поиска (retrieval pipeline). Не путать со стратегиями чанкинга. */
export type RagRetrievalStrategy =
  | 'baseline'
  | 'query-rewrite'
  | 'similarity-filter'
  | 'query-rewrite-rerank'

export interface RagRetrievalOptions {
  strategy: RagRetrievalStrategy
  top_k: number
  top_k_before: number
  top_k_after: number
  top_k_final: number
  similarity_threshold: number
  reranker_threshold_enabled: boolean
  reranker_threshold: number
}

export interface RagPipelineDebug {
  retrieval_strategy: string
  original_query: string
  rewritten_query: string | null
  rewrite_fallback: boolean
  reranker_fallback: boolean | null
  params: Record<string, number | null>
  counts: {
    retrieved: number
    after_similarity_filter: number
    after_reranker_filter: number
    final: number
  }
}

export interface RagChunkMetadata {
  chunk_id: string
  url: string | null
  author: string | null
  rating: number | null
  date: string | null
  title: string | null
  story_id: number | null
  strategy: string
  chunk_index: number
  article_chunks: number
}

export interface RagChunkHit {
  id: string
  score: number
  reranker_score?: number | null
  tokens: number | null
  text: string
  metadata: RagChunkMetadata
}
