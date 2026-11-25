function Route({ meta, simulate }) {
  if (meta.resolution_source === 'LLM_CACHE') {
    return <p className="route">Served from cache · no API key used</p>
  }
  if (!meta.key_id) return null
  const failed = meta.fallback_attempts || 0
  return (
    <p className="route">
      {Array.from({ length: failed }, (_, i) => (
        <span key={i}>
          <b className="bad">key_{i + 1} failed</b> →{' '}
        </span>
      ))}
      <b className="good">{meta.key_id} answered</b>
      {simulate && <span> · simulation sent: {simulate}</span>}
    </p>
  )
}

export default function Metadata({ meta, simulate }) {
  const cached = meta.resolution_source === 'LLM_CACHE'
  return (
    <footer>
      <dl className="meta">
        <div className={cached ? 'tag cache' : 'tag live'}>
          <dt className="sr-only">Source</dt>
          <dd data-testid="meta-source">{meta.resolution_source}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd data-testid="meta-model">{meta.model}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd data-testid="meta-latency">{meta.latency_ms} ms</dd>
        </div>
        <div>
          <dt>Input tokens</dt>
          <dd data-testid="meta-input-tokens">{meta.input_tokens}</dd>
        </div>
        <div>
          <dt>Output tokens</dt>
          <dd data-testid="meta-output-tokens">{meta.output_tokens}</dd>
        </div>
      </dl>
      <Route meta={meta} simulate={simulate} />
    </footer>
  )
}
