import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { IMPACT_RANK, formatDate } from '../format.js'
import Field from './Field.jsx'
import { ImpactBadge } from './ResultCards.jsx'

const IMPACTS = Object.keys(IMPACT_RANK)
const EDITABLE = ['anti_pattern', 'solution', 'impact', 'example_before', 'example_after']

function pick(pattern) {
  return Object.fromEntries(EDITABLE.map((key) => [key, pattern[key]]))
}

/** {"f": [[1], [2]]} -> her fonksiyon tek satırda, okunabilir JSON. */
function formatInputs(inputs) {
  const entries = Object.entries(inputs ?? {})
  if (!entries.length) return '{}'
  return `{\n${entries.map(([fn, cases]) => `  ${JSON.stringify(fn)}: ${JSON.stringify(cases)}`).join(',\n')}\n}`
}

function parseInputs(text) {
  let value
  try {
    value = JSON.parse(text)
  } catch (e) {
    throw new Error(`Test girdileri geçerli JSON değil: ${e.message}`)
  }
  const ok =
    value && typeof value === 'object' && !Array.isArray(value) &&
    Object.values(value).every((cases) => Array.isArray(cases) && cases.every(Array.isArray))
  if (!ok) throw new Error('Test girdileri {"fonksiyon_adı": [[argümanlar], ...]} biçiminde olmalı.')
  return value
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
  const [inputsText, setInputsText] = useState(() => formatInputs(pattern.example_inputs))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setError(null)
    let exampleInputs
    try {
      exampleInputs = parseInputs(inputsText)
    } catch (err) {
      setError(err.message)
      return
    }
    setSaving(true)
    try {
      await onSave({ ...form, example_inputs: exampleInputs })
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <form className="pattern-form" onSubmit={submit}>
      <Field label="Sorun">
        <textarea rows={3} value={form.anti_pattern} onChange={set('anti_pattern')} required />
      </Field>
      <Field label="Çözüm">
        <textarea rows={3} value={form.solution} onChange={set('solution')} required />
      </Field>
      <Field label="Etki" inline>
        <select value={form.impact} onChange={set('impact')}>
          {IMPACTS.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </Field>
      <div className="pattern-examples">
        <Field label="Önce">
          <textarea className="code-input" rows={8} spellCheck={false} value={form.example_before} onChange={set('example_before')} required />
        </Field>
        <Field label="Sonra">
          <textarea className="code-input" rows={8} spellCheck={false} value={form.example_after} onChange={set('example_after')} required />
        </Field>
      </div>
      <Field label="Test girdileri (JSON)">
        <textarea
          className="code-input"
          rows={4}
          spellCheck={false}
          value={inputsText}
          onChange={(e) => setInputsText(e.target.value)}
        />
      </Field>
      <p className="muted small">
        Kaydederken “Sonra” örneğinin “Önce” ile aynı davrandığı (dönüş değeri, hata tipi ve argüman yan etkileri)
        bu girdilerle doğrulanır; eşdeğer olmayan örnek kaydedilmez. Biçim:{' '}
        <code>{'{"fonksiyon_adı": [[argümanlar], ...]}'}</code>
      </p>
      {error && <p className="error-banner">{error}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving && <span className="spinner" aria-hidden="true" />}
          {saving ? 'Doğrulanıyor…' : 'Kaydet'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          İptal
        </button>
      </div>
    </form>
  )
}

/** 401: oturum yok/süresi doldu -> yerel oturumu kapat ve anlaşılır mesaj göster. */
function authMessage(err, onUnauthorized) {
  if (err.status === 401) {
    onUnauthorized?.()
    return 'Yönetici oturumunun süresi doldu veya geçersiz; yeniden giriş yapın.'
  }
  return err.message
}

function PatternCard({ pattern, onUpdated, isAdmin, onUnauthorized }) {
  const [editing, setEditing] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState(null)

  async function toggle(isActive) {
    setToggling(true)
    setError(null)
    try {
      onUpdated(await api.setPatternActive(pattern.code, isActive))
    } catch (e) {
      setError(authMessage(e, onUnauthorized))
    } finally {
      setToggling(false)
    }
  }

  async function save(form) {
    try {
      onUpdated(await api.updatePattern(pattern.code, form))
    } catch (e) {
      throw new Error(authMessage(e, onUnauthorized))
    }
    setEditing(false)
  }

  return (
    <article className={`card pattern-card ${pattern.is_active ? '' : 'inactive'}`}>
      <header className="pattern-header">
        <code className="pattern-code">{pattern.code}</code>
        <h3>{pattern.title}</h3>
        <ImpactBadge impact={pattern.impact} />
        {isAdmin ? (
          <ActiveSwitch pattern={pattern} onChange={toggle} disabled={toggling || editing} />
        ) : (
          !pattern.is_active && <span className="badge status-inactive">Pasif</span>
        )}
        {isAdmin && !editing && (
          <button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(true)}>
            Düzenle
          </button>
        )}
      </header>
      {error && <p className="error-banner">{error}</p>}
      {editing && isAdmin ? (
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
          {pattern.updated_at && (
            <p className="muted small">
              Son güncelleme: {formatDate(pattern.updated_at)}
              {pattern.updated_by && ` · ${pattern.updated_by}`}
            </p>
          )}
        </>
      )}
    </article>
  )
}

export default function PatternsTab({ isAdmin = false, onUnauthorized }) {
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
        {!isAdmin && ' Düzenlemek ve aktif/pasif yapmak için yönetici girişi yapın.'}
      </p>
      <p className="intro">
        Optimizasyon motoru yalnızca bu onaylı desenleri uygular. Her desen, statik analizde tespit edilen bir
        enerji israfı kalıbına karşılık gelir. Pasif desenler analizde raporlanmaz ve LLM'e gönderilmez.
      </p>
      {patterns.map((p) => (
        <PatternCard key={p.code} pattern={p} onUpdated={replace} isAdmin={isAdmin} onUnauthorized={onUnauthorized} />
      ))}
    </div>
  )
}
