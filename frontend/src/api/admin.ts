import type { AdminMetrics, AdminInfo, McpLogEntry } from '../types'

export async function fetchAdminMetrics(): Promise<AdminMetrics> {
  const resp = await fetch('/admin/metrics')
  if (!resp.ok) throw new Error(`Metrics error: ${resp.status}`)
  return resp.json()
}

export async function fetchAdminInfo(): Promise<AdminInfo> {
  const resp = await fetch('/admin/info')
  if (!resp.ok) throw new Error(`Info error: ${resp.status}`)
  return resp.json()
}

export async function callMcpTool(tool: string, args: Record<string, unknown>): Promise<{ success: boolean; result?: string; error?: string }> {
  const resp = await fetch('/admin/mcp-test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, arguments: args }),
  })
  return resp.json()
}

export function subscribeMcpLog(
  onEntry: (entry: McpLogEntry) => void,
  signal?: AbortSignal,
): () => void {
  const es = new EventSource('/admin/mcp/log')

  es.addEventListener('tool_call', (e: MessageEvent) => {
    try {
      onEntry(JSON.parse(e.data))
    } catch { /* ignore */ }
  })

  es.onerror = () => {
    // EventSource will auto-reconnect
  }

  signal?.addEventListener('abort', () => es.close())

  return () => es.close()
}
