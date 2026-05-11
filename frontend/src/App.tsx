import { useState, useEffect } from 'react'
import UserTab from './components/UserTab'
import AdminTab from './components/AdminTab'
import type { ChatMessage, ModelKey } from './types'

type Tab = 'user' | 'admin'

let msgCounter = 0
export const newMsgId = () => `msg-${++msgCounter}`

const SESSION_KEY = 'maas_chat_messages'
const MODEL_KEY   = 'maas_chat_model'

function loadMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (raw) {
      const parsed: ChatMessage[] = JSON.parse(raw)
      // Ensure no message is stuck in streaming state after a reload
      return parsed.map(m => ({ ...m, streaming: false }))
    }
  } catch { /* ignore */ }
  return []
}

function loadModel(): ModelKey {
  try {
    const v = sessionStorage.getItem(MODEL_KEY)
    if (v === 'granite' || v === 'qwen') return v
  } catch { /* ignore */ }
  return 'granite'
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('user')

  // Chat state at root — survives tab switching.
  // sessionStorage provides a second layer of persistence across reloads.
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages)
  const [model, setModel] = useState<ModelKey>(loadModel)
  const [availableModels, setAvailableModels] = useState<ModelKey[]>(['granite'])

  // Persist messages and model to sessionStorage on every change
  useEffect(() => {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(messages)) } catch { /* ignore */ }
  }, [messages])

  useEffect(() => {
    try { sessionStorage.setItem(MODEL_KEY, model) } catch { /* ignore */ }
  }, [model])

  return (
    <div className="flex flex-col h-screen bg-rh-darker overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-4 px-6 py-3 bg-rh-dark border-b border-rh-border shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-rh-red rounded flex items-center justify-center">
            <span className="text-white text-xs font-bold">RH</span>
          </div>
          <span className="font-semibold text-sm text-rh-text">OpenShift AI</span>
          <span className="text-rh-muted text-sm">/ MaaS Demo</span>
        </div>

        <div className="flex gap-1 ml-4 bg-rh-surface rounded-lg p-1">
          {(['user', 'admin'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${
                activeTab === tab
                  ? 'bg-rh-red text-white'
                  : 'text-rh-muted hover:text-rh-text'
              }`}
            >
              {tab === 'user' ? 'User' : 'Admin Panel'}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2 text-xs text-rh-muted">
          <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
          <span>maas-demo namespace</span>
        </div>
      </header>

      {/* Tab content — both always mounted to preserve state (chat, map, metrics).
          Using visibility+pointer-events instead of display:none so Leaflet
          can still measure its container dimensions when the map tab is hidden. */}
      <main className="flex-1 min-h-0 relative overflow-hidden">
        <div
          className="absolute inset-0 transition-none"
          style={{
            visibility: activeTab === 'user' ? 'visible' : 'hidden',
            pointerEvents: activeTab === 'user' ? 'auto' : 'none',
          }}
        >
          <UserTab
            messages={messages}
            setMessages={setMessages}
            model={model}
            setModel={setModel}
            availableModels={availableModels}
            setAvailableModels={setAvailableModels}
          />
        </div>
        <div
          className="absolute inset-0 transition-none"
          style={{
            visibility: activeTab === 'admin' ? 'visible' : 'hidden',
            pointerEvents: activeTab === 'admin' ? 'auto' : 'none',
          }}
        >
          <AdminTab />
        </div>
      </main>
    </div>
  )
}
