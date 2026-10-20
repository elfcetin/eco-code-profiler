import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { ImpactBadge } from './ResultCards.jsx'

export default function PatternsTab() {
  const [patterns, setPatterns] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.patterns().then(setPatterns).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error-banner">{error}</p>
  if (!patterns) return <p className="muted">Desenler yükleniyor…</p>

  return (
    <div className="patterns">
      <p className="intro">
        Optimizasyon motoru yalnızca bu onaylı desenleri uygular. Her desen, statik analizde tespit edilen
        bir enerji israfı kalıbına karşılık gelir.
      </p>
      {patterns.map((p) => (
        <article className="card pattern-card" key={p.code}>
          <header className="pattern-header">
            <code className="pattern-code">{p.code}</code>
            <h3>{p.title}</h3>
            <ImpactBadge impact={p.impact} />
          </header>
          <dl className="pattern-text">
            <dt>Sorun</dt>
            <dd>{p.anti_pattern}</dd>
            <dt>Çözüm</dt>
            <dd>{p.solution}</dd>
          </dl>
          <div className="pattern-examples">
            <figure>
              <figcaption>Önce</figcaption>
              <pre className="code-block before">{p.example_before}</pre>
            </figure>
            <figure>
              <figcaption>Sonra</figcaption>
              <pre className="code-block after">{p.example_after}</pre>
            </figure>
          </div>
        </article>
      ))}
    </div>
  )
}
