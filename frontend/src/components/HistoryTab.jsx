import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatDate, formatSeconds, formatSpeedup } from '../format.js'

const STATUS_LABEL = { clean: 'Temiz', optimized: 'Optimize edildi', failed: 'Başarısız' }

export default function HistoryTab({ onLoadCode }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setError(null)
    api.history().then(setItems).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  return (
    <section className="card">
      <div className="card-header">
        <h3>Son 20 analiz</h3>
        <button type="button" className="btn btn-secondary" onClick={load}>Yenile</button>
      </div>
      {error && <p className="error-banner">{error}</p>}
      {!items && !error && <p className="muted">Yükleniyor…</p>}
      {items?.length === 0 && <p className="muted">Henüz analiz yapılmadı.</p>}
      {items?.length > 0 && (
        <div className="table-wrap">
          <table className="table history">
            <thead>
              <tr>
                <th>Tarih</th>
                <th>Durum</th>
                <th>Desenler</th>
                <th className="num">Eski</th>
                <th className="num">Yeni</th>
                <th className="num">Hızlanma</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((run) => {
                const codes = [...new Set(run.findings.map((f) => f.pattern_code))]
                return (
                  <tr key={run.id}>
                    <td className="nowrap">{formatDate(run.created_at)}</td>
                    <td><span className={`badge status-${run.status}`}>{STATUS_LABEL[run.status] ?? run.status}</span></td>
                    <td>
                      {codes.length ? codes.map((c) => <code className="pattern-code" key={c}>{c}</code>) : '—'}
                    </td>
                    <td className="num">{formatSeconds(run.old_seconds)}</td>
                    <td className="num">{formatSeconds(run.new_seconds)}</td>
                    <td className="num strong">{formatSpeedup(run.speedup)}</td>
                    <td className="right">
                      <button type="button" className="btn btn-link" onClick={() => onLoadCode(run.original_code)}>
                        Editöre yükle
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
