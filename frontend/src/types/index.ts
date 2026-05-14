export type ModelKey = 'granite' | 'qwen'

export interface DecisionCard {
  risk_level: string
  recommended_action: string
  confidence: number
  why: string[]
  redacted?: boolean
}

export interface EvidencePayload {
  weather_timestamp: string
  weather_valid_period?: { start?: string; end?: string; text?: string }
  transport_dataset: string
  tools_used: string[]
  model_split: {
    weather_specialist: string
    transport_specialist: string
    fusion: string
  }
  generated_at: string
}

export interface PhaseLatencyPayload {
  weather_specialist: number
  transport_specialist: number
  fusion: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model?: ModelKey
  toolCalls?: ToolCallEvent[]
  decisionCard?: DecisionCard
  evidence?: EvidencePayload
  phaseLatenciesMs?: PhaseLatencyPayload
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
  endpoint?: string
  status: 'ok' | 'error'
  tokens_total?: number
  prompt_tokens_total?: number
  total_tokens?: number
  avg_latency_s?: number
  avg_ttft_s?: number
  generation_tps?: number
  prompt_tps?: number
  requests_per_s?: number
  gpu_cache_perc?: number
  requests_running?: number
  requests_waiting?: number
  queue_ratio?: number
  timestamp: number
  error?: string
}

export interface FleetMetrics {
  models_total: number
  models_healthy: number
  requests_running_total: number
  requests_waiting_total: number
  generation_tps_total: number
  prompt_tps_total: number
  avg_latency_s: number
  avg_ttft_s: number
  mcp_recent_calls: number
  mcp_success_rate: number
  timestamp: number
}

export interface AdminMetrics {
  fleet: FleetMetrics
  models: Record<string, ModelMetrics>
}

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
