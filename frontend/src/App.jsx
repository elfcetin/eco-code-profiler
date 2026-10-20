import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { IMPACT_CLASS, IMPACT_RANK } from './format.js'
import { SAMPLES } from './samples.js'
import CodeEditor from './components/CodeEditor.jsx'
import ResultView from './components/ResultView.jsx'
import PatternsTab from './components/PatternsTab.jsx'
import HistoryTab from './components/HistoryTab.jsx'

const TABS = [
  ['analysis', 'Analiz'],
  ['patterns', 'Yeşil Kod Desenleri'],
  ['history', 'Geçmiş'],
]

function useHealth() {
  const [health, setHealth] = useState({ state: 'loading', label: 'Kontrol ediliyor…', detail: '' })
  useEffect(() => {
    let alive = true
    const check = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return
          setHealth({
            state: h.llm.reachable ? 'ok' : 'down',
            label: `LLM: ${h.llm.provider} · ${h.llm.model}`,
            detail: `${h.llm.message}${h.database.ok ? '' : ` · Veritabanı: ${h.database.message}`}`,
          })
        })
        .catch(() => alive && setHealth({ state: 'down', label: 'Sunucu bağlantısı yok', detail: 'Backend yanıt vermiyor.' }))
    check()
    const id = setInterval(check, 30000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])
  return health
}

function useElapsed(active) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!active) return
    setSeconds(0)
    const started = Date.now()
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(id)
  }, [active])
  return seconds
}

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M20 3C10 3 4 8.5 4 15.5c0 1.6.4 3 1 4.2C6.5 15 10 11.5 15 9.5c-4 2.6-6.8 6-8.2 10.3 1.2.8 2.7 1.2 4.2 1.2C18 21 21 13 20 3z"
      />
    </svg>
  )
}

export default function App() {
  const [tab, setTab] = useState('analysis')
  const [code, setCode] = useState(SAMPLES[0].code)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(null) // 'analyze' | 'optimize' | null
  const [error, setError] = useState(null)
  const [focus, setFocus] = useState(null)
  const health = useHealth()
  const elapsed = useElapsed(loading)

  // Vurgular yalnızca sonuç, editördeki kodun kendisine aitse gösterilir.
  const highlights = useMemo(() => {
    if (!result || result.code !== code) return new Map()
    const analysis = result.kind === 'analyze' ? result.data : result.data.analysis
    const worst = new Map() // satır -> en yüksek etki
    for (const f of analysis?.findings ?? []) {
      if (!worst.has(f.line) || IMPACT_RANK[f.impact] > IMPACT_RANK[worst.get(f.line)]) worst.set(f.line, f.impact)
    }
    const map = new Map([...worst].map(([line, impact]) => [line, IMPACT_CLASS[impact]]))
    if (analysis?.syntax_error?.line) map.set(analysis.syntax_error.line, 'error')
    return map
  }, [result, code])

  async function run(kind) {
    setLoading(kind)
    setError(null)
    try {
      const data = kind === 'analyze' ? await api.analyze(code) : await api.optimize(code)
      setResult({ kind, code, data })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(null)
    }
  }

  function loadCode(newCode) {
    setCode(newCode)
    setResult(null)
    setError(null)
  }

  const busy = loading !== null
  const empty = code.trim() === ''

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">Eco-Code Profiler</div>
            <div className="brand-sub">Algoritmik enerji israfı analizi</div>
          </div>
        </div>
        <div className={`health health-${health.state}`} title={health.detail}>
          <span className="dot" aria-hidden="true" />
          <span>{health.label}</span>
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`tab ${tab === id ? 'active' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === 'analysis' && (
          <>
            <section className="card editor-card">
              <div className="card-header">
                <h3>Python kodu</h3>
                <div className="samples">
                  <span className="muted small">Örnekler:</span>
                  {SAMPLES.map((s) => (
                    <button
                      key={s.name}
                      type="button"
                      className="btn btn-chip"
                      onClick={() => loadCode(s.code)}
                      disabled={busy}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>
              </div>
              <CodeEditor value={code} onChange={setCode} highlights={highlights} focus={focus} disabled={busy} />
              <div className="actions">
                <button type="button" className="btn btn-secondary" onClick={() => run('analyze')} disabled={busy || empty}>
                  {loading === 'analyze' && <span className="spinner" aria-hidden="true" />}
                  Hızlı Analiz
                </button>
                <button type="button" className="btn btn-primary" onClick={() => run('optimize')} disabled={busy || empty}>
                  {loading === 'optimize' && <span className="spinner" aria-hidden="true" />}
                  Optimize Et
                </button>
                {loading === 'optimize' && (
                  <span className="muted small" aria-live="polite">
                    Analiz, yeniden yazım ve doğrulama sürüyor… {elapsed} sn
                    {elapsed >= 10 && ' (yerel LLM birkaç dakika sürebilir)'}
                  </span>
                )}
              </div>
            </section>

            {error && <p className="error-banner">{error}</p>}
            {result && (
              <ResultView result={result} onSelectLine={(line) => setFocus({ line, nonce: Date.now() })} />
            )}
          </>
        )}
        {tab === 'patterns' && <PatternsTab />}
        {tab === 'history' && (
          <HistoryTab
            onLoadCode={(c) => {
              loadCode(c)
              setTab('analysis')
            }}
          />
        )}
      </main>
    </div>
  )
}
