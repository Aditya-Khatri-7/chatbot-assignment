const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')

export function newSessionId() {
  const random = Math.random().toString(36).slice(2, 10)
  return `s-${Date.now().toString(36)}-${random}`
}

export async function checkHealth() {
  const response = await fetch(`${API_URL}/health`)
  if (!response.ok) throw new Error('unhealthy')
  return response.json()
}

function readableError(status, detail) {
  if (status === 422) {
    const reasons = Array.isArray(detail)
      ? detail.map((item) => `${item.loc?.at(-1)}: ${item.msg}`).join('; ')
      : detail
    return `Your message could not be sent (422). ${reasons || ''}`
  }
  if (status === 503) {
    return `The AI service is unavailable right now (503: ${detail || 'try again shortly'}). Please try again.`
  }
  return `Something went wrong (${status}). Please try again.`
}

export async function sendChat({ sessionId, message, systemPrompt, simulate }) {
  const headers = { 'Content-Type': 'application/json' }
  if (simulate) headers['X-Simulate-Failure'] = simulate

  const body = { session_id: sessionId, message }
  if (systemPrompt) body.system_prompt = systemPrompt

  let response
  try {
    response = await fetch(`${API_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error('Cannot reach the server. Check your connection and try again.')
  }

  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(readableError(response.status, data?.detail))
  if (!data?.reply || !data?.metadata) throw new Error('The server sent an unexpected response.')
  return data
}
