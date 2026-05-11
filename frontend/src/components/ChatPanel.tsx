import { useState, useRef, useEffect, useCallback } from 'react'
import type { ChatMessage, ModelKey, ToolCallEvent } from '../types'
import { streamChat } from '../api/chat'
import MessageBubble from './MessageBubble'
import { newMsgId } from '../App'

const SUGGESTED_PROMPTS = [
  "What's the weather like in Tampines right now?",
  "Will it rain anywhere in Singapore today?",
  "What's the 4-day forecast for Singapore?",
  "Which areas have thundery showers currently?",
  "What's the temperature and humidity in the east?",
]

const MODEL_CONFIG: Record<string, { label: string; color: string }> = {
  granite: { label: 'Granite-8B', color: '#EE0000' },
  qwen: { label: 'Qwen3-8B', color: '#9333ea' },
}

interface Props {
  messages: ChatMessage[]
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  model: ModelKey
  setModel: (m: ModelKey) => void
  availableModels: ModelKey[]
  setAvailableModels: (models: ModelKey[]) => void
  onMapUpdate: (areas: string[]) => void
}

export default function ChatPanel({
  messages, setMessages, model, setModel, availableModels, setAvailableModels, onMapUpdate,
}: Props) {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Fetch which models are actually configured in the backend (once on mount)
  useEffect(() => {
    fetch('/admin/info')
      .then(r => r.json())
      .then(data => {
        const models: ModelKey[] = data.available_models ?? ['granite']
        setAvailableModels(models)
        if (!models.includes(model)) setModel(models[0])
      })
      .catch(() => { /* keep default */ })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      onMapUpdate,
      onDone: (_, label) => {
        setMessages(prev =>
          prev.map(m => m.id === assistantId ? { ...m, streaming: false } : m)
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
  }, [messages, model, isStreaming, onMapUpdate])

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
          {/* Model toggle — only shown when multiple models are available */}
          <div className="flex items-center gap-2 bg-rh-surface rounded-full px-1 py-1">
            {availableModels.map(m => (
              <button
                key={m}
                onClick={() => !isStreaming && setModel(m)}
                disabled={isStreaming}
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
          <button
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

      {/* Quick-question chips — always visible */}
      <div className="border-t border-rh-border/50 px-3 pt-2 pb-1 shrink-0 bg-rh-dark">
        <div className="flex flex-wrap gap-1.5">
          {SUGGESTED_PROMPTS.map(p => (
            <button
              key={p}
              onClick={() => sendMessage(p)}
              disabled={isStreaming}
              className="text-xs px-2.5 py-1 rounded-full bg-rh-surface border border-rh-border text-rh-muted hover:text-rh-text hover:border-rh-red/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {p}
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
            placeholder="Ask about Singapore weather…"
            rows={1}
            className="flex-1 bg-rh-surface border border-rh-border rounded-lg px-3 py-2 text-sm text-rh-text placeholder-rh-muted resize-none focus:outline-none focus:border-rh-red/50 max-h-32"
            style={{ minHeight: '38px' }}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={stopStreaming}
              className="px-3 py-2 bg-rh-surface border border-rh-border rounded-lg text-sm text-rh-muted hover:text-red-400 hover:border-red-400/40 transition-colors shrink-0"
            >
              ■ Stop
            </button>
          ) : (
            <button
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
