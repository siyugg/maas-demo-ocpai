export type ModelKey = 'granite' | 'qwen'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model?: ModelKey
  toolCalls?: ToolCallEvent[]
  streaming?: boolean
}

export interface ToolCallEvent {
  tool: string
  args: Record<string, unknown>
  preview?: string
}

export interface MapArea {
  name: string
  lat: number
  lng: number
  forecast: string
}

export interface MapData {
  timestamp: string
  valid_period: { start: string; end: string; text?: string }
  areas: MapArea[]
  cached_at: number
}

export interface ModelMetrics {
  model: ModelKey
  label: string
  namespace: string
  status: 'ok' | 'error'
  tokens_total?: number
  prompt_tokens_total?: number
  avg_latency_s?: number
  gpu_cache_perc?: number
  requests_running?: number
  requests_waiting?: number
  timestamp: number
  error?: string
}

export type AdminMetrics = Record<string, ModelMetrics>

export interface McpTool {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export interface AdminInfo {
  models: Record<string, { label: string; endpoint: string; namespace: string; model_name: string }>
  mcp: {
    health: { healthy: boolean; error?: string }
    tools: McpTool[]
  }
}

export interface McpLogEntry {
  id: string
  timestamp: string
  tool: string
  args: Record<string, unknown>
  latency_ms: number
  success: boolean
  error?: string
  preview: string
}
