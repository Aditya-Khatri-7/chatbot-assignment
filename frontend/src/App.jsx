import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { checkHealth, newSessionId, sendChat } from './api.js'
import Metadata from './Metadata.jsx'
import TopBar from './TopBar.jsx'
import Dashboard from './Dashboard.jsx'

const FAILURE_TESTS = [
  { value: '', label: 'Off' },
  { value: 'key_1=429', label: 'Rate limit key 1 (429)' },
  { value: 'key_1=500', label: 'Server error on key 1 (500)' },
  { value: '*=429', label: 'Fail every key (503)' },
]

const SUGGESTIONS = [
  'What is the capital of France?',
  'Explain API key failover in simple words',
  'My name is Sam. Remember it.',
]

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [simulate, setSimulate] = useState('')
  const [sending, setSending] = useState(false)
  const [health, setHealth] = useState(null)
  const [server, setServer] = useState('checking')
  const bottom = useRef(null)

  useEffect(() => {
    checkHealth()
      .then((data) => {
        setHealth(data)
        setServer('ready')
      })
      .catch(() => setServer('unreachable'))
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  async function send(suggestion) {
    const text = (suggestion ?? input).trim()
    if (!text || sending) return
    setInput('')
    setSending(true)
    setMessages((list) => [...list, { role: 'user', content: text }])
    try {
      const data = await sendChat({
        sessionId,
        message: text,
        systemPrompt: systemPrompt.trim(),
        simulate,
      })
      setServer('ready')
      setMessages((list) => [
        ...list,
        { role: 'assistant', content: data.reply, metadata: data.metadata, simulate },
      ])
    } catch (error) {
      setMessages((list) => [...list, { role: 'error', content: error.message }])
      setInput((current) => current || text)
    } finally {
      setSending(false)
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  function startNewChat() {
    setSessionId(newSessionId())
    setMessages([])
    setInput('')
  }

  return (
    <div className="shell">
      <TopBar
        server={server}
        sending={sending}
        onNewChat={startNewChat}
        systemPrompt={systemPrompt}
        onSystemPrompt={setSystemPrompt}
      />

      <div className="workspace">
        <main className={messages.length === 0 ? 'chat empty' : 'chat'}>
          <section className="messages" aria-live="polite">
            <div className="thread">
              {messages.length === 0 && (
                <div className="welcome">
                  <h2>How can I help you today?</h2>
                  <p>Replies stay available when an API key fails, and repeats come from cache.</p>
                </div>
              )}

              {messages.map((message, index) => {
                if (message.role === 'user') {
                  return (
                    <article key={index} className="user">
                      {message.content}
                    </article>
                  )
                }
                if (message.role === 'error') {
                  return (
                    <article key={index} className="error" role="alert">
                      <strong>Message not sent</strong>
                      <span>{message.content}</span>
                    </article>
                  )
                }
                return (
                  <article key={index} className="assistant" data-testid="assistant-message">
                    <img className="avatar" src="/logo.svg" alt="" />
                    <div className="reply">
                      <Markdown>{message.content}</Markdown>
                    </div>
                    <Metadata meta={message.metadata} simulate={message.simulate} />
                  </article>
                )
              })}

              {sending && (
                <div className="typing" role="status" aria-label="Waiting for reply">
                  <i />
                  <i />
                  <i />
                </div>
              )}
              <div ref={bottom} />
            </div>
          </section>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault()
              send()
            }}
          >
            <div className="box">
              <textarea
                data-testid="chat-input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Message the assistant…"
                aria-label="Message"
                rows={1}
                autoFocus
              />
              <div className="tools">
                <label className={simulate ? 'test on' : 'test'}>
                  <span className="sr-only">Failover test</span>
                  <select value={simulate} onChange={(event) => setSimulate(event.target.value)}>
                    {FAILURE_TESTS.map((test) => (
                      <option key={test.value} value={test.value}>
                        Failover test: {test.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="submit"
                  className="send"
                  data-testid="send-button"
                  aria-label="Send"
                  disabled={sending || !input.trim()}
                >
                  ↑
                </button>
              </div>
            </div>
            <p className={simulate ? 'hint warning' : 'hint'}>
              {simulate
                ? `Test mode: ${simulate} is sent with every message until you turn it off.`
                : 'Enter to send · Shift+Enter for a new line'}
            </p>
          </form>

          {messages.length === 0 && (
            <div className="suggestions">
              {SUGGESTIONS.map((text) => (
                <button key={text} type="button" onClick={() => send(text)}>
                  {text}
                </button>
              ))}
            </div>
          )}
        </main>
        <Dashboard
          meta={[...messages].reverse().find((m) => m.role === 'assistant')?.metadata}
          health={health}
        />
      </div>
    </div>
  )
}
