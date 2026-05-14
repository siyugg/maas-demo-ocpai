import { useState } from 'react'
import type { ChatMessage } from '../types'

const MODEL_COLORS: Record<string, string> = {
  granite: '#EE0000',
  qwen: '#9333ea',
}

interface Props {
  message: ChatMessage
}

export default function MessageBubble({ message }: Props) {
  const [toolsExpanded, setToolsExpanded] = useState(false)
  const [evidenceExpanded, setEvidenceExpanded] = useState(false)
  const isUser = message.role === 'user'
  const hasTools = (message.toolCalls?.length ?? 0) > 0
  const hasDecisionCard = !!message.decisionCard
  const hasEvidence = !!message.evidence
  const phaseLatencies = message.phaseLatenciesMs

  // Deduplicate tool calls (tool_call and tool_result arrive separately)
  const tools = (message.toolCalls ?? []).filter(tc => tc.tool)
  const uniqueTools = tools.reduce<typeof tools>((acc, tc) => {
    const existing = acc.find(x => x.tool === tc.tool)
    if (!existing) acc.push(tc)
    else if (tc.preview) existing.preview = tc.preview
    return acc
  }, [])

  const riskTone = 'text-red-200 border-red-500/60 bg-red-500/15'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] ${isUser ? 'order-2' : ''}`}>
        {/* Model badge for assistant messages */}
        {!isUser && message.model && (
          <div className="flex items-center gap-1.5 mb-1 ml-1">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: MODEL_COLORS[message.model] ?? '#888' }}
            />
            <span className="text-xs text-rh-muted">
              {message.model === 'granite' ? 'Granite-8B' : 'Qwen3-8B'}
            </span>
          </div>
        )}

        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-rh-red text-white rounded-tr-sm'
              : 'bg-rh-surface border border-rh-border text-rh-text rounded-tl-sm'
          }`}
        >
          {message.content}
          {message.streaming && !message.content && (
            <span className="text-rh-muted italic">Thinking…</span>
          )}
          {message.streaming && message.content && (
            <span className="cursor-blink" />
          )}
        </div>

        {hasDecisionCard && !isUser && (
          <div className={`mt-2 ml-1 rounded-xl border px-3 py-2 text-xs ${riskTone}`}>
            <div className="font-semibold mb-1">Decision Card</div>
            <div><span className="text-red-100/90">Risk level:</span> {message.decisionCard?.risk_level}</div>
            <div><span className="text-red-100/90">Recommended action:</span> {message.decisionCard?.recommended_action}</div>
            <div>
              <span className="text-red-100/90">Confidence:</span>{' '}
              {Math.round((message.decisionCard?.confidence ?? 0) * 100)}%
            </div>
            {(message.decisionCard?.why ?? []).length > 0 && (
              <div className="mt-1">
                <span className="text-red-100/90">Why:</span>{' '}
                {(message.decisionCard?.why ?? []).join(' | ')}
              </div>
            )}
          </div>
        )}

        {phaseLatencies && !isUser && (
          <div className="mt-2 ml-1 rounded-xl border border-rh-border bg-rh-darker px-3 py-2 text-xs">
            <div className="text-rh-muted mb-1">Prompt + Tool Timeline</div>
            <div className="flex flex-wrap gap-2 text-rh-text">
              <span className="px-2 py-0.5 rounded bg-rh-surface">Weather {phaseLatencies.weather_specialist}ms</span>
              <span className="px-2 py-0.5 rounded bg-rh-surface">Transport {phaseLatencies.transport_specialist}ms</span>
              <span className="px-2 py-0.5 rounded bg-rh-surface">Fusion {phaseLatencies.fusion}ms</span>
            </div>
          </div>
        )}

        {hasEvidence && !isUser && (
          <div className="mt-2 ml-1">
            <button
              onClick={() => setEvidenceExpanded(v => !v)}
              className="flex items-center gap-1.5 text-xs text-rh-muted hover:text-rh-text transition-colors"
            >
              <span>How this answer was built</span>
              <span className="text-rh-border">{evidenceExpanded ? '▲' : '▼'}</span>
            </button>
            {evidenceExpanded && (
              <div className="mt-1.5 rounded-xl border border-rh-border bg-rh-darker px-3 py-2 text-xs space-y-1.5">
                <div><span className="text-rh-muted">Weather timestamp:</span> {message.evidence?.weather_timestamp || 'N/A'}</div>
                <div><span className="text-rh-muted">Transport dataset:</span> {message.evidence?.transport_dataset}</div>
                <div><span className="text-rh-muted">Tools used:</span> {(message.evidence?.tools_used ?? []).join(', ') || 'N/A'}</div>
                <div>
                  <span className="text-rh-muted">Model split:</span>{' '}
                  {message.evidence?.model_split.weather_specialist} / {message.evidence?.model_split.transport_specialist} / {message.evidence?.model_split.fusion}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tool calls disclosure */}
        {hasTools && (
          <div className="mt-1.5 ml-1">
            <button
              onClick={() => setToolsExpanded(v => !v)}
              className="flex items-center gap-1.5 text-xs text-rh-muted hover:text-rh-text transition-colors"
            >
              <span className="text-amber-400">⚡</span>
              <span>{uniqueTools.length} MCP tool{uniqueTools.length !== 1 ? 's' : ''} called</span>
              <span className="text-rh-border">{toolsExpanded ? '▲' : '▼'}</span>
            </button>

            {toolsExpanded && (
              <div className="mt-1.5 space-y-1.5">
                {uniqueTools.map((tc, i) => (
                  <div key={i} className="bg-rh-darker border border-rh-border rounded-lg px-3 py-2 font-mono text-xs">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-amber-400">fn</span>
                      <span className="text-blue-400">{tc.tool}</span>
                      {Object.keys(tc.args).length > 0 && (
                        <span className="text-rh-muted">
                          ({JSON.stringify(tc.args)})
                        </span>
                      )}
                    </div>
                    {tc.preview && (
                      <div className="text-rh-muted border-t border-rh-border/50 pt-1 mt-1 truncate">
                        {tc.preview}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
