import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { IMPACT_RANK, formatDate } from '../format.js'
import { ImpactBadge } from './ResultCards.jsx'

const IMPACTS = Object.keys(IMPACT_RANK)
const EDITABLE = ['anti_pattern', 'solution', 'impact', 'example_before', 'example_after']

function pick(pattern) {
  return Object.fromEntries(EDITABLE.map((key) => [key, pattern[key]]))
}

function ActiveSwitch({ pattern, onChange, disabled }) {
  return (
    <label className="switch" title={pattern.is_active ? 'Pasif yap' : 'Aktif yap'}>
      <input
        type="checkbox"
        role="switch"
        checked={pattern.is_active}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-label">{pattern.is_active ? 'Aktif' : 'Pasif'}</span>
    </label>
  )
}

function PatternForm({ pattern, onSave, onCancel }) {
  const [form, setForm] = useState(() => pick(pattern))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(form)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <form className="pattern-form" onSubmit={submit}>
      <label className="field">
        <span>Sorun</span>
        <textarea rows={3} value={form.anti_pattern} onChange={set('anti_pattern')} required />
      </label>
      <label className="field">
        <span>Çözüm</span>
        <textarea rows={3} value={form.solution} onChange={set('solution')} required />
      </label>
      <label className="field field-inline">
        <span>Etki</span>
        <select value={form.impact} onChange={set('impact')}>
          {IMPACTS.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </label>
      <div className="pattern-examples">
        <label className="field">
          <span>Önce</span>
          <textarea className="code-input" rows={8} spellCheck={false} value={form.example_before} onChange={set('example_before')} required />
        </label>
        <label className="field">
          <span>Sonra</span>
          <textarea className="code-input" rows={8} spellCheck={false} value={form.example_after} onChange={set('example_after')} required />
        </label>
      </div>
      {error && <p className="error-banner">{error}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving && <span className="spinner" aria-hidden="true" />}
          Kaydet
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          İptal
        </button>
      </div>
    </form>
  )
}

function PatternCard({ pattern, onUpdated }) {
  const [editing, setEditing] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState(null)

  async function toggle(isActive) {
    setToggling(true)
    setError(null)
    try {
      onUpdated(await api.setPatternActive(pattern.code, isActive))
    } catch (e) {
      setError(e.message)
    } finally {
      setToggling(false)
    }
  }

  async function save(form) {
    onUpdated(await api.updatePattern(pattern.code, form))
    setEditing(false)
  }

  return (
    <article className={`card pattern-card ${pattern.is_active ? '' : 'inactive'}`}>
      <header className="pattern-header">
        <code className="pattern-code">{pattern.code}</code>
        <h3>{pattern.title}</h3>
        <ImpactBadge impact={pattern.impact} />
        <ActiveSwitch pattern={pattern} onChange={toggle} disabled={toggling || editing} />
        {!editing && (
          <button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(true)}>
            Düzenle
          </button>
        )}
      </header>
      {error && <p className="error-banner">{error}</p>}
      {editing ? (
        <PatternForm pattern={pattern} onSave={save} onCancel={() => setEditing(false)} />
      ) : (
        <>
          <dl className="pattern-text">
            <dt>Sorun</dt>
            <dd>{pattern.anti_pattern}</dd>
            <dt>Çözüm</dt>
            <dd>{pattern.solution}</dd>
          </dl>
          <div className="pattern-examples">
            <figure>
              <figcaption>Önce</figcaption>
              <pre className="code-block before">{pattern.example_before}</pre>
            </figure>
            <figure>
              <figcaption>Sonra</figcaption>
              <pre className="code-block after">{pattern.example_after}</pre>
            </figure>
          </div>
          {pattern.updated_at && <p className="muted small">Son güncelleme: {formatDate(pattern.updated_at)}</p>}
        </>
      )}
    </article>
  )
}

export default function PatternsTab() {
  const [patterns, setPatterns] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.patterns().then(setPatterns).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error-banner">{error}</p>
  if (!patterns) return <p className="muted">Desenler yükleniyor…</p>

  const replace = (updated) => setPatterns((list) => list.map((p) => (p.code === updated.code ? updated : p)))

  return (
    <div className="patterns">
      <p className="note" role="note">
        Desenlerin çözüm ve örnekleri buradan yönetilir. Yeni desen türleri için tespit kuralı eklenmesi gerekir.
      </p>
      <p className="intro">
        Optimizasyon motoru yalnızca bu onaylı desenleri uygular. Her desen, statik analizde tespit edilen bir
        enerji israfı kalıbına karşılık gelir. Pasif desenler analizde raporlanmaz ve LLM'e gönderilmez.
      </p>
      {patterns.map((p) => (
        <PatternCard key={p.code} pattern={p} onUpdated={replace} />
      ))}
    </div>
  )
}
