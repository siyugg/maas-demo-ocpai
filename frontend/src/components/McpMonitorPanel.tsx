import { useState, useEffect, useRef } from 'react'
import type { AdminInfo, McpLogEntry, McpTool } from '../types'
import { fetchAdminInfo, callMcpTool, subscribeMcpLog } from '../api/admin'

function HealthBadge({ healthy }: { healthy: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
      healthy
        ? 'bg-green-900/30 text-green-400 border border-green-800/50'
        : 'bg-red-900/30 text-red-400 border border-red-800/50'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${healthy ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
      {healthy ? 'Healthy' : 'Unreachable'}
    </div>
  )
}

function ToolCard({ tool, onTest }: { tool: McpTool; onTest: (tool: McpTool) => void }) {
  const [expanded, setExpanded] = useState(false)
  const params = (tool.inputSchema as any)?.properties ?? {}
  const paramNames = Object.keys(params)

  return (
    <div className="bg-rh-darker border border-rh-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-rh-surface/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-amber-400 text-xs font-mono">fn</span>
          <span className="text-sm font-medium text-blue-400 font-mono">{tool.name}</span>
          {paramNames.length > 0 && (
            <span className="text-xs text-rh-muted">({paramNames.join(', ')})</span>
          )}
        </div>
        <span className="text-rh-border text-xs">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 border-t border-rh-border/50">
          <p className="text-xs text-rh-muted mt-2 mb-2">{tool.description}</p>
          <button
            onClick={() => onTest(tool)}
            className="text-xs px-2.5 py-1 bg-rh-red/10 hover:bg-rh-red/20 border border-rh-red/30 text-rh-red rounded transition-colors"
          >
            Test this tool
          </button>
        </div>
      )}
    </div>
  )
}

function LogEntry({ entry }: { entry: McpLogEntry }) {
  return (
    <div className={`flex items-start gap-2 py-1.5 border-b border-rh-border/30 text-xs font-mono ${
      entry.success ? '' : 'text-red-400'
    }`}>
      <span className="text-rh-muted shrink-0">{entry.timestamp}</span>
      <span className={`shrink-0 ${entry.success ? 'text-green-400' : 'text-red-400'}`}>
        {entry.success ? '✓' : '✗'}
      </span>
      <span className="text-blue-400 shrink-0">{entry.tool}</span>
      <span className="text-rh-muted truncate flex-1">
        {entry.success ? entry.preview : entry.error}
      </span>
      <span className="text-rh-muted shrink-0">{entry.latency_ms}ms</span>
    </div>
  )
}

function TestCallForm({
  tools,
  onClose,
}: {
  tools: McpTool[]
  onClose: () => void
}) {
  const [selectedTool, setSelectedTool] = useState(tools[0]?.name ?? '')
  const [argsJson, setArgsJson] = useState('{}')
  const [result, setResult] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [argsError, setArgsError] = useState(false)

  const handleRun = async () => {
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(argsJson)
      setArgsError(false)
    } catch {
      setArgsError(true)
      return
    }
    setLoading(true)
    setResult(null)
    const res = await callMcpTool(selectedTool, args)
    setResult(res.success ? (res.result ?? 'No result') : `Error: ${res.error}`)
    setLoading(false)
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-6">
      <div className="bg-rh-surface border border-rh-border rounded-2xl w-full max-w-lg shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-rh-border">
          <span className="font-semibold text-sm text-rh-text">Test MCP Tool</span>
          <button onClick={onClose} className="text-rh-muted hover:text-rh-text text-lg leading-none">×</button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-rh-muted mb-1.5">Tool</label>
            <select
              value={selectedTool}
              onChange={e => setSelectedTool(e.target.value)}
              className="w-full bg-rh-darker border border-rh-border rounded-lg px-3 py-2 text-sm text-rh-text focus:outline-none focus:border-rh-red/50"
            >
              {tools.map(t => (
                <option key={t.name} value={t.name}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-rh-muted mb-1.5">Arguments (JSON)</label>
            <textarea
              value={argsJson}
              onChange={e => setArgsJson(e.target.value)}
              rows={3}
              className={`w-full bg-rh-darker border rounded-lg px-3 py-2 text-sm font-mono text-rh-text focus:outline-none ${
                argsError ? 'border-red-500' : 'border-rh-border focus:border-rh-red/50'
              }`}
            />
            {argsError && <p className="text-xs text-red-400 mt-1">Invalid JSON</p>}
          </div>
          <button
            onClick={handleRun}
            disabled={loading}
            className="w-full bg-rh-red hover:bg-rh-darkred text-white rounded-lg py-2 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {loading ? 'Calling…' : 'Run Tool'}
          </button>
          {result && (
            <div className="bg-rh-darker border border-rh-border rounded-lg px-3 py-2 text-xs font-mono text-rh-text whitespace-pre-wrap max-h-48 overflow-y-auto">
              {result}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function McpMonitorPanel() {
  const [info, setInfo] = useState<AdminInfo | null>(null)
  const [logEntries, setLogEntries] = useState<McpLogEntry[]>([])
  const [testOpen, setTestOpen] = useState(false)
  const [testTool, setTestTool] = useState<McpTool | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController>(new AbortController())

  useEffect(() => {
    fetchAdminInfo().then(setInfo).catch(console.error)
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const unsub = subscribeMcpLog(
      entry => setLogEntries(prev => [entry, ...prev].slice(0, 100)),
      ctrl.signal,
    )
    return () => { ctrl.abort(); unsub() }
  }, [])

  const tools = info?.mcp.tools ?? []
  const healthy = info?.mcp.health.healthy ?? null

  const handleTest = (tool: McpTool) => {
    setTestTool(tool)
    setTestOpen(true)
  }

  const toolCallCounts = logEntries.reduce<Record<string, number>>((acc, e) => {
    acc[e.tool] = (acc[e.tool] ?? 0) + 1
    return acc
  }, {})

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-rh-border bg-rh-dark shrink-0">
        <span className="text-sm font-medium text-rh-text">MCP Monitor</span>
        {healthy !== null && <HealthBadge healthy={healthy} />}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {/* Tool registry */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-rh-muted uppercase tracking-wide">
              Tool Registry ({tools.length})
            </span>
            <button
              onClick={() => setTestOpen(true)}
              className="text-xs px-2.5 py-1 bg-rh-surface border border-rh-border hover:border-rh-red/40 text-rh-muted hover:text-rh-text rounded transition-colors"
            >
              + Test Tool
            </button>
          </div>
          <div className="space-y-1.5">
            {tools.map(t => (
              <ToolCard key={t.name} tool={t} onTest={handleTest} />
            ))}
            {tools.length === 0 && (
              <div className="text-xs text-rh-muted text-center py-4">
                Loading tools…
              </div>
            )}
          </div>
        </section>

        {/* Call counts */}
        {Object.keys(toolCallCounts).length > 0 && (
          <section>
            <div className="text-xs font-semibold text-rh-muted uppercase tracking-wide mb-2">
              Tool Call Counts (this session)
            </div>
            <div className="space-y-1.5">
              {Object.entries(toolCallCounts)
                .sort(([, a], [, b]) => b - a)
                .map(([tool, count]) => {
                  const max = Math.max(...Object.values(toolCallCounts))
                  return (
                    <div key={tool} className="flex items-center gap-2 text-xs">
                      <span className="text-blue-400 font-mono w-40 truncate">{tool}</span>
                      <div className="flex-1 bg-rh-darker rounded-full h-1.5 overflow-hidden">
                        <div
                          className="h-full bg-amber-500 rounded-full transition-all"
                          style={{ width: `${(count / max) * 100}%` }}
                        />
                      </div>
                      <span className="text-rh-muted w-6 text-right">{count}</span>
                    </div>
                  )
                })}
            </div>
          </section>
        )}

        {/* Live call log */}
        <section>
          <div className="text-xs font-semibold text-rh-muted uppercase tracking-wide mb-2">
            Live Call Log
          </div>
          <div
            ref={logRef}
            className="bg-rh-darker border border-rh-border rounded-lg p-2 h-52 overflow-y-auto font-mono"
          >
            {logEntries.length === 0 ? (
              <div className="flex items-center justify-center h-full text-rh-muted text-xs">
                Waiting for tool calls…
              </div>
            ) : (
              logEntries.map(e => <LogEntry key={e.id} entry={e} />)
            )}
          </div>
        </section>
      </div>

      {testOpen && (
        <TestCallForm
          tools={tools}
          onClose={() => { setTestOpen(false); setTestTool(null) }}
        />
      )}
    </div>
  )
}
