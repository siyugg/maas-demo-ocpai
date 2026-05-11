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
  const isUser = message.role === 'user'
  const hasTools = (message.toolCalls?.length ?? 0) > 0

  // Deduplicate tool calls (tool_call and tool_result arrive separately)
  const tools = (message.toolCalls ?? []).filter(tc => tc.tool)
  const uniqueTools = tools.reduce<typeof tools>((acc, tc) => {
    const existing = acc.find(x => x.tool === tc.tool)
    if (!existing) acc.push(tc)
    else if (tc.preview) existing.preview = tc.preview
    return acc
  }, [])

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
