const STATUS = {
  checking: 'Connecting…',
  ready: 'Online',
  unreachable: 'Not reachable yet',
}

export default function TopBar({ server, sending, onNewChat, systemPrompt, onSystemPrompt }) {
  return (
    <header className="topbar">
      <div className="brand">
        <img className="logo" src="/logo.svg" alt="" />
        <div>
          <h1>Resilient Chat</h1>
          <p>LLM gateway with key failover and caching</p>
        </div>
      </div>

      <p className={`status ${server}`}>{STATUS[server]}</p>

      <details className="prompt">
        <summary>System prompt</summary>
        <div className="popover">
          <textarea
            data-testid="system-prompt-input"
            value={systemPrompt}
            onChange={(event) => onSystemPrompt(event.target.value)}
            placeholder="e.g. You are a travel guide. Be brief."
            maxLength={4000}
            rows={5}
          />
          <small>Stays in effect for this chat until you send a different one.</small>
        </div>
      </details>

      <button type="button" className="new-chat" onClick={onNewChat} disabled={sending}>
        ＋ New chat
      </button>
    </header>
  )
}
