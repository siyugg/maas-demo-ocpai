import MetricsPanel from './MetricsPanel'
import McpMonitorPanel from './McpMonitorPanel'
import type { ModelKey } from '../types'

const MODEL_CONFIG: Record<string, { label: string; color: string }> = {
  granite: { label: 'Granite-8B', color: '#EE0000' },
  qwen: { label: 'Qwen3-8B', color: '#9333ea' },
}

interface Props {
  model: ModelKey
  setModel: (m: ModelKey) => void
  availableModels: ModelKey[]
}

export default function AdminTab({ model, setModel, availableModels }: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-rh-border bg-rh-dark shrink-0 flex items-center justify-between">
        <span className="text-sm font-medium text-rh-text">Admin Controls</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-rh-muted">User chat model:</span>
          <div className="flex items-center gap-2 bg-rh-surface rounded-full px-1 py-1">
            {availableModels.map(m => (
              <button
                type="button"
                key={m}
                onClick={() => setModel(m)}
                title={MODEL_CONFIG[m]?.label ?? m}
                className={`px-3 py-0.5 rounded-full text-xs font-medium transition-all ${
                  model === m
                    ? 'text-white shadow'
                    : 'text-rh-muted hover:text-rh-text'
                }`}
                style={model === m ? { backgroundColor: MODEL_CONFIG[m]?.color ?? '#888' } : {}}
              >
                {MODEL_CONFIG[m]?.label ?? m}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Left — vLLM Model Metrics */}
        <div className="w-1/2 border-r border-rh-border flex flex-col min-h-0 overflow-y-auto">
          <MetricsPanel />
        </div>
        {/* Right — MCP Monitor */}
        <div className="w-1/2 flex flex-col min-h-0">
          <McpMonitorPanel />
        </div>
      </div>
    </div>
  )
}
