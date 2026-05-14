import { useState, useEffect, useRef } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import type { AdminMetrics, ModelMetrics } from '../types'
import { fetchAdminMetrics } from '../api/admin'

const MODEL_COLORS = { granite: '#EE0000', qwen: '#9333ea' }

interface DataPoint {
  time: string
  granite?: number
  qwen?: number
}

function MetricCard({ metrics }: { metrics: ModelMetrics }) {
  const isOk = metrics.status === 'ok'
  const color = MODEL_COLORS[metrics.model] ?? '#888'

  return (
    <div className="bg-rh-surface border border-rh-border rounded-xl p-4 flex-1 min-w-0">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
          <span className="font-semibold text-sm text-rh-text">{metrics.label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full ${isOk ? 'bg-green-400' : 'bg-red-400'}`}
          />
          <span className={`text-xs ${isOk ? 'text-green-400' : 'text-red-400'}`}>
            {isOk ? 'Serving' : 'Error'}
          </span>
        </div>
      </div>

      <div className="text-xs text-rh-muted mb-3">
        ns: <span className="text-rh-text">{metrics.namespace}</span>
      </div>
      {metrics.endpoint && (
        <div className="text-[11px] text-rh-muted mb-3 font-mono break-all">
          endpoint: <span className="text-rh-text">{metrics.endpoint}</span>
        </div>
      )}

      {isOk ? (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          <StatTile
            label="Tokens generated"
            value={metrics.tokens_total?.toLocaleString() ?? '—'}
            unit="total"
          />
          <StatTile
            label="Total tokens"
            value={metrics.total_tokens?.toLocaleString() ?? '—'}
            unit="sum"
          />
          <StatTile
            label="Avg latency"
            value={metrics.avg_latency_s != null ? `${metrics.avg_latency_s.toFixed(2)}s` : '—'}
          />
          <StatTile
            label="Avg TTFT"
            value={metrics.avg_ttft_s != null ? `${metrics.avg_ttft_s.toFixed(2)}s` : '—'}
          />
          <StatTile
            label="GPU KV cache"
            value={metrics.gpu_cache_perc != null ? `${(metrics.gpu_cache_perc * 100).toFixed(1)}%` : '—'}
          />
          <StatTile
            label="Active / queued"
            value={`${metrics.requests_running ?? 0} / ${metrics.requests_waiting ?? 0}`}
          />
          <StatTile
            label="Generation throughput"
            value={metrics.generation_tps != null ? `${metrics.generation_tps.toFixed(1)}` : '—'}
            unit="tok/s"
          />
          <StatTile
            label="Prompt throughput"
            value={metrics.prompt_tps != null ? `${metrics.prompt_tps.toFixed(1)}` : '—'}
            unit="tok/s"
          />
          <StatTile
            label="Queue ratio"
            value={metrics.queue_ratio != null ? `${(metrics.queue_ratio * 100).toFixed(1)}%` : '—'}
          />
        </div>
      ) : (
        <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2">
          {metrics.error ?? 'Unable to reach metrics endpoint'}
        </div>
      )}
    </div>
  )
}

function StatTile({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="bg-rh-darker rounded-lg px-3 py-2">
      <div className="text-xs text-rh-muted mb-0.5">{label}</div>
      <div className="text-sm font-semibold text-rh-text">
        {value}
        {unit && <span className="text-xs text-rh-muted ml-1">{unit}</span>}
      </div>
    </div>
  )
}

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [history, setHistory] = useState<DataPoint[]>([])
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = async () => {
    try {
      const data = await fetchAdminMetrics()
      setMetrics(data)
      setError(null)

      const point: DataPoint = {
        time: new Date().toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        granite: data.models.granite?.tokens_total,
        qwen: data.models.qwen?.tokens_total,
      }
      setHistory(prev => [...prev.slice(-30), point])
    } catch (e: any) {
      setError(e.message)
    }
  }

  useEffect(() => {
    load()
    intervalRef.current = setInterval(load, 5000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [])

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-rh-text">Model Metrics</h2>
        <div className="flex items-center gap-1.5 text-xs text-rh-muted">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          Live · 5s refresh
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Fleet-level MaaS KPI row */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <StatTile label="Models Healthy" value={`${metrics.fleet.models_healthy}/${metrics.fleet.models_total}`} />
          <StatTile label="Fleet Gen TPS" value={metrics.fleet.generation_tps_total.toFixed(1)} unit="tok/s" />
          <StatTile label="Fleet TTFT" value={`${metrics.fleet.avg_ttft_s.toFixed(2)}s`} />
          <StatTile label="In-flight / queued" value={`${metrics.fleet.requests_running_total} / ${metrics.fleet.requests_waiting_total}`} />
          <StatTile label="MCP success rate" value={`${(metrics.fleet.mcp_success_rate * 100).toFixed(1)}%`} />
        </div>
      )}

      {/* Side-by-side model cards — one per configured model */}
      {metrics && (
        <div className="flex gap-3 flex-wrap">
          {(Object.values(metrics.models) as ModelMetrics[]).map(m => (
            <MetricCard key={m.model} metrics={m} />
          ))}
        </div>
      )}

      {/* Shared timeline comparison chart */}
      <div className="bg-rh-surface border border-rh-border rounded-xl p-4">
        <div className="text-xs font-medium text-rh-muted mb-3">
          Tokens Generated — Comparison
        </div>
        {history.length > 1 ? (
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={history} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--rh-border) / 1)" />
              <XAxis dataKey="time" tick={{ fill: 'rgb(var(--rh-muted) / 1)', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fill: 'rgb(var(--rh-muted) / 1)', fontSize: 10 }} />
              <Tooltip
                contentStyle={{
                  background: 'rgb(var(--rh-surface) / 1)',
                  border: '1px solid rgb(var(--rh-border) / 1)',
                  borderRadius: 8,
                }}
                labelStyle={{ color: 'rgb(var(--rh-text) / 1)', fontSize: 11 }}
                itemStyle={{ fontSize: 11, color: 'rgb(var(--rh-text) / 1)' }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                type="monotone"
                dataKey="granite"
                name="Granite-8B"
                stroke={MODEL_COLORS.granite}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="qwen"
                name="Qwen3-8B"
                stroke={MODEL_COLORS.qwen}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-rh-muted text-sm">
            Collecting data…
          </div>
        )}
      </div>
    </div>
  )
}
