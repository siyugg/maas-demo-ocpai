import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import type { ChatMessage, ModelKey, ToolCallEvent } from '../types'
import { streamChat } from '../api/chat'
import MessageBubble from './MessageBubble'
import { newMsgId } from '../App'

const PROMPT_POOLS = {
  general: [
    'Should I send the technician to inspect the rooftop equipment at Jurong now?',
    'Can we proceed with the Marina Bay crane lift this afternoon, or delay?',
    'Should we switch tonight deliveries to MRT near Raffles Place due to traffic risk?',
    'Is it safe to run facade cleaning at Paya Lebar between 2pm and 5pm?',
    'Do I trigger standby crews for flooding risk in Bukit Timah this evening?',
    'Should we reroute service vans away from CBD for tomorrow morning peak?',
    'Can the maintenance team start outdoor cable works at Tuas at 9am?',
    'Do we keep the rooftop event at Changi or move it indoors?',
  ],
  rain: [
    'Should I dispatch the Jurong rooftop inspection team in the next 2 hours if rain risk is high?',
    'Will thundery showers disrupt outdoor inspections in Woodlands this evening?',
    'Which zones look driest right now for urgent field maintenance?',
    'Should I hold back high-altitude work near Tuas until weather stabilizes?',
    'When is the safest weather window for site visits across the west today?',
    'Do we need rain contingency crews near low-lying areas tonight?',
  ],
  forecast: [
    'Should we schedule preventive maintenance in Jurong tomorrow morning or afternoon?',
    'For the next 4 days, which day is best for rooftop equipment audits?',
    'Will weather shifts this week affect outdoor service-level commitments?',
    'Should I plan weekend manpower with weather buffers for east-region works?',
    'Which period over the next few days has the lowest operational weather risk?',
    'Do we move non-urgent external inspections to a lower-risk day this week?',
  ],
  tempHumidity: [
    'Is it too hot/humid now for technicians to do prolonged rooftop work in the west?',
    'Which region has the highest heat-stress risk for field teams right now?',
    'Should I add rest-cycle buffers for outdoor crews based on current humidity?',
    'Compare heat exposure risk for teams in Jurong vs Tampines this hour.',
    'Do we need hydration and shorter shift protocols for today afternoon?',
    'Which area is coolest now for rescheduling outdoor maintenance jobs?',
  ],
} as const

function inferPromptTopic(messages: ChatMessage[]): keyof typeof PROMPT_POOLS {
  const lastUser = [...messages].reverse().find(m => m.role === 'user')?.content.toLowerCase() ?? ''
  if (/(rain|storm|thunder|shower|wet)/.test(lastUser)) return 'rain'
  if (/(forecast|tomorrow|week|weekend|day|days)/.test(lastUser)) return 'forecast'
  if (/(temp|temperature|humidity|hot|cool|heat)/.test(lastUser)) return 'tempHumidity'
  return 'general'
}

function buildPromptSuggestions(messages: ChatMessage[]): string[] {
  const topic = inferPromptTopic(messages)
  const pool = PROMPT_POOLS[topic]
  const userTurns = messages.filter(m => m.role === 'user').length
  const offset = userTurns % pool.length
  const rotated = [...pool.slice(offset), ...pool.slice(0, offset)]
  return rotated.slice(0, 6)
}

const MODEL_CONFIG: Record<string, { label: string; color: string }> = {
  granite: { label: 'Granite-8B', color: '#EE0000' },
  qwen: { label: 'Qwen3-8B', color: '#9333ea' },
}

interface Props {
  messages: ChatMessage[]
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  model: ModelKey
  onMapUpdate: (areas: string[]) => void
}

export default function ChatPanel({
  messages, setMessages, model, onMapUpdate,
}: Props) {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const suggestedPrompts = useMemo(() => buildPromptSuggestions(messages), [messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    const userMsg: ChatMessage = { id: newMsgId(), role: 'user', content: text }
    const assistantId = newMsgId()
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      model,
      toolCalls: [],
      streaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    setIsStreaming(true)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    const history = [...messages, userMsg]
    const phaseMarks: Record<string, number> = {}

    await streamChat(history, model, {
      onToken: (text) => {
        setMessages(prev =>
          prev.map(m => m.id === assistantId ? { ...m, content: m.content + text } : m)
        )
      },
      onToolCall: (event: ToolCallEvent) => {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, toolCalls: [...(m.toolCalls ?? []), event] }
              : m
          )
        )
      },
      onDecisionCard: (card) => {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, decisionCard: card }
              : m
          )
        )
      },
      onPhaseStart: (phase, tMs) => {
        phaseMarks[phase] = tMs
        setMessages(prev =>
          prev.map(m => {
            if (m.id !== assistantId) return m
            const current = m.phaseLatenciesMs ?? { weather_specialist: 0, transport_specialist: 0, fusion: 0 }
            if (phase === 'transport_specialist' && phaseMarks.weather_specialist != null) {
              return {
                ...m,
                phaseLatenciesMs: {
                  ...current,
                  weather_specialist: Math.max(0, tMs - phaseMarks.weather_specialist),
                },
              }
            }
            if (phase === 'fusion' && phaseMarks.transport_specialist != null) {
              return {
                ...m,
                phaseLatenciesMs: {
                  ...current,
                  transport_specialist: Math.max(0, tMs - phaseMarks.transport_specialist),
                },
              }
            }
            return { ...m, phaseLatenciesMs: current }
          }),
        )
      },
      onMapUpdate,
      onDone: (payload) => {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? {
                ...m,
                streaming: false,
                decisionCard: payload.decision_card ?? m.decisionCard,
                evidence: payload.evidence ?? m.evidence,
                phaseLatenciesMs: payload.phase_latencies_ms ?? m.phaseLatenciesMs,
              }
              : m,
          )
        )
        setIsStreaming(false)
      },
      onError: (msg) => {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: m.content || `Error: ${msg}`, streaming: false }
              : m
          )
        )
        setIsStreaming(false)
      },
    }, ctrl.signal)
  }, [messages, model, isStreaming, onMapUpdate, setMessages])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const stopStreaming = () => {
    abortRef.current?.abort()
    setMessages(prev =>
      prev.map(m => m.streaming ? { ...m, streaming: false } : m)
    )
    setIsStreaming(false)
  }

  const clearChat = () => {
    if (!isStreaming) setMessages([])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Panel header with model toggle */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-rh-border bg-rh-dark shrink-0">
        <span className="text-sm font-medium text-rh-text">Chat</span>
        <div className="flex items-center gap-3">
          <div className="text-xs text-rh-muted">
            Active model: <span className="text-rh-text">{MODEL_CONFIG[model]?.label ?? model}</span> (set in Admin)
          </div>
          <button
            type="button"
            onClick={clearChat}
            disabled={isStreaming}
            className="text-xs text-rh-muted hover:text-rh-text transition-colors disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <div>
              <div className="w-12 h-12 rounded-full bg-rh-red/10 border border-rh-red/30 flex items-center justify-center mx-auto mb-3">
                <span className="text-rh-red text-xl">⛅</span>
              </div>
              <p className="text-rh-text font-medium">Singapore Weather Assistant</p>
              <p className="text-rh-muted text-sm mt-1">Powered by live data.gov.sg via MCP</p>
            </div>
          </div>
        )}
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Dynamic quick-question chips — refreshed after every prompt */}
      <div className="border-t border-rh-border/50 px-3 pt-2 pb-2 shrink-0 bg-rh-dark">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wide text-rh-muted font-semibold">
            Suggested Questions
          </span>
          <span className="text-[11px] text-rh-muted/70">
            updates each turn
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {suggestedPrompts.map(p => (
            <button
              type="button"
              key={p}
              onClick={() => sendMessage(p)}
              disabled={isStreaming}
              className="group text-left text-xs px-2.5 py-2 rounded-lg bg-gradient-to-r from-rh-surface to-rh-darker border border-rh-border text-rh-muted hover:text-rh-text hover:border-rh-red/40 hover:from-rh-surface hover:to-rh-surface/80 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <span className="inline-flex items-center gap-1">
                <span className="text-rh-red/70 group-hover:text-rh-red">{'>'}</span>
                {p}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-rh-border p-3 shrink-0 bg-rh-dark">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask an operational decision question..."
            rows={1}
            className="flex-1 bg-rh-surface border border-rh-border rounded-lg px-3 py-2 text-sm text-rh-text placeholder-rh-muted resize-none focus:outline-none focus:border-rh-red/50 max-h-32"
            style={{ minHeight: '38px' }}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={stopStreaming}
              className="px-3 py-2 bg-rh-surface border border-rh-border rounded-lg text-sm text-rh-muted hover:text-red-400 hover:border-red-400/40 transition-colors shrink-0"
            >
              ■ Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={() => sendMessage(input)}
              disabled={!input.trim()}
              className="px-3 py-2 bg-rh-red hover:bg-rh-darkred text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              Send
            </button>
          )}
        </div>
        <p className="text-xs text-rh-muted mt-1.5 ml-1">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
