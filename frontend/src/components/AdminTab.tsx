import MetricsPanel from './MetricsPanel'
import McpMonitorPanel from './McpMonitorPanel'

export default function AdminTab() {
  return (
    <div className="flex h-full">
      {/* Left — vLLM Model Metrics */}
      <div className="w-1/2 border-r border-rh-border flex flex-col min-h-0 overflow-y-auto">
        <MetricsPanel />
      </div>
      {/* Right — MCP Monitor */}
      <div className="w-1/2 flex flex-col min-h-0">
        <McpMonitorPanel />
      </div>
    </div>
  )
}
