import { useState, useCallback } from 'react'
import ChatPanel from './ChatPanel'
import SingaporeMap from './SingaporeMap'
import type { ChatMessage, ModelKey } from '../types'

interface Props {
  messages: ChatMessage[]
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  model: ModelKey
}

export default function UserTab({
  messages, setMessages, model,
}: Props) {
  const [highlightedAreas, setHighlightedAreas] = useState<string[]>([])

  const handleMapUpdate = useCallback((areas: string[]) => {
    setHighlightedAreas(areas)
    setTimeout(() => setHighlightedAreas([]), 8000)
  }, [])

  return (
    <div className="flex h-full">
      {/* Left — Chat */}
      <div className="w-1/2 border-r border-rh-border flex flex-col min-h-0">
        <ChatPanel
          messages={messages}
          setMessages={setMessages}
          model={model}
          onMapUpdate={handleMapUpdate}
        />
      </div>
      {/* Right — Map */}
      <div className="w-1/2 flex flex-col min-h-0">
        <SingaporeMap highlightedAreas={highlightedAreas} />
      </div>
    </div>
  )
}
