import { useState, useCallback, useEffect } from 'react'
import UserTab from './components/UserTab'
import AdminTab from './components/AdminTab'
import type { ChatMessage, ModelKey } from './types'

type Tab = 'user' | 'admin'

let msgCounter = 0
export const newMsgId = () => `msg-${++msgCounter}`

// Build stamp injected by Vite at build time
const BUILD_TIME: string = import.meta.env.VITE_BUILD_TIME ?? 'dev'

// localStorage keys
const LS_MESSAGES = 'maas_chat_messages'
const LS_MODEL    = 'maas_chat_model'
const LS_THEME    = 'maas_theme_mode'

function save(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* quota / private mode */ }
}

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(LS_MESSAGES)
    if (raw) return (JSON.parse(raw) as ChatMessage[]).map(m => ({ ...m, streaming: false }))
  } catch { /* ignore */ }
  return []
}

function loadModel(): ModelKey {
  try {
    const v = localStorage.getItem(LS_MODEL)
    if (v === 'granite' || v === 'qwen') return v as ModelKey
  } catch { /* ignore */ }
  return 'granite'
}

function loadTheme(): 'light' | 'dark' {
  try {
    const v = localStorage.getItem(LS_THEME)
    if (v === 'light' || v === 'dark') return v
  } catch { /* ignore */ }
  return 'dark'
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('user')

  // ALL chat state at root — never lost by tab switching.
  // Saved to localStorage synchronously inside every setter call so nothing
  // can be lost between a state update and an async effect firing.
  const [messages, _setMessages] = useState<ChatMessage[]>(loadMessages)
  const [model, _setModel]       = useState<ModelKey>(loadModel)
  const [availableModels, setAvailableModels] = useState<ModelKey[]>(['granite'])
  const [theme, setTheme] = useState<'light' | 'dark'>(loadTheme)

  const setMessages = useCallback<React.Dispatch<React.SetStateAction<ChatMessage[]>>>(
    (action) => {
      _setMessages(prev => {
        const next = typeof action === 'function' ? action(prev) : action
        save(LS_MESSAGES, next)
        return next
      })
    },
    [],
  )

  const setModel = useCallback((m: ModelKey) => {
    _setModel(m)
    save(LS_MODEL, m)
  }, [])

  useEffect(() => {
    fetch('/admin/info')
      .then(r => r.json())
      .then(data => {
        const models: ModelKey[] = data.available_models ?? ['granite']
        setAvailableModels(models)
        if (!models.includes(model)) setModel(models[0])
      })
      .catch(() => { /* keep default */ })
  }, [model, setModel])

  const toggleTheme = useCallback(() => {
    setTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark'
      save(LS_THEME, next)
      return next
    })
  }, [])

  return (
    <div className={`flex flex-col h-screen bg-rh-darker overflow-hidden theme-${theme}`}>
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
              type="button"
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

        <div className="ml-auto flex items-center gap-3 text-xs text-rh-muted">
          <button
            type="button"
            onClick={toggleTheme}
            className="px-2.5 py-1 rounded-md border border-rh-border bg-rh-surface text-rh-text hover:border-rh-red/40 transition-colors"
            title="Toggle light/dark mode"
          >
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
          <span className="hidden sm:block opacity-50">build {BUILD_TIME}</span>
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
          />
        </div>
        <div
          className="absolute inset-0 transition-none"
          style={{
            visibility: activeTab === 'admin' ? 'visible' : 'hidden',
            pointerEvents: activeTab === 'admin' ? 'auto' : 'none',
          }}
        >
          <AdminTab
            model={model}
            setModel={setModel}
            availableModels={availableModels}
          />
        </div>
      </main>
    </div>
  )
}
