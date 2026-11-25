export default function Dashboard({ meta, health }) {
  const cached = meta?.resolution_source === 'LLM_CACHE'
  const failed = meta?.fallback_attempts || 0

  return (
    <aside className="dashboard" aria-label="Latest reply details">
      <h2>Latest reply</h2>

      <div className={`stat source ${!meta ? '' : cached ? 'is-cache' : 'is-live'}`}>
        <span>Source</span>
        <strong>{meta ? meta.resolution_source : 'Waiting…'}</strong>
      </div>
      <div className="stat speed">
        <span>Latency</span>
        <strong>{meta ? `${meta.latency_ms} ms` : '–'}</strong>
      </div>
      <div className="pair">
        <div className="stat in">
          <span>Input tokens</span>
          <strong>{meta ? meta.input_tokens : '–'}</strong>
        </div>
        <div className="stat out">
          <span>Output tokens</span>
          <strong>{meta ? meta.output_tokens : '–'}</strong>
        </div>
      </div>
      <div className="stat">
        <span>Model</span>
        <em>{meta ? meta.model : '–'}</em>
      </div>
      <div className="stat">
        <span>Key route</span>
        {!meta && <em>–</em>}
        {meta && cached && <em>Cache hit, no key used</em>}
        {meta && !cached && (
          <p className="keys">
            {Array.from({ length: failed }, (_, i) => (
              <b key={i} className="down">
                key_{i + 1} ✕
              </b>
            ))}
            <b className="up">{meta.key_id} ✓</b>
          </p>
        )}
      </div>

      <p className="pool">
        {health
          ? `${health.keys_configured} API keys in pool · cache ${health.cache_enabled ? 'on' : 'off'}`
          : 'Key pool status unavailable'}
      </p>
    </aside>
  )
}
