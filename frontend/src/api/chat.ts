import type { ChatMessage, ModelKey, ToolCallEvent } from '../types'

export interface ChatStreamCallbacks {
  onToken: (text: string, model: ModelKey) => void
  onToolCall: (event: ToolCallEvent) => void
  onMapUpdate: (areas: string[]) => void
  onDone: (model: ModelKey, label: string) => void
  onError: (message: string) => void
}

export async function streamChat(
  messages: ChatMessage[],
  model: ModelKey,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const payload = {
    messages: messages.map(m => ({ role: m.role, content: m.content })),
    model,
  }

  const resp = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!resp.ok || !resp.body) {
    callbacks.onError(`Server error: ${resp.status}`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    let eventType = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          switch (eventType) {
            case 'token':
              callbacks.onToken(data.text, data.model)
              break
            case 'tool_call':
              callbacks.onToolCall({ tool: data.tool, args: data.args })
              break
            case 'tool_result':
              callbacks.onToolCall({ tool: data.tool, args: {}, preview: data.preview })
              break
            case 'map_update':
              callbacks.onMapUpdate(data.areas)
              break
            case 'done':
              callbacks.onDone(data.model, data.model_label)
              break
            case 'error':
              callbacks.onError(data.message)
              break
          }
        } catch {
          // ignore parse errors
        }
        eventType = ''
      }
    }
  }
}
