import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Field from './Field.jsx'
import { IMPACT_CLASS, energyAssumptionNote, formatEstimate, formatSeconds, formatSpeedup } from '../format.js'

export function ImpactBadge({ impact }) {
  return <span className={`badge impact-${IMPACT_CLASS[impact] ?? 'low'}`}>{impact}</span>
}

export function StatusCard({ tone, title, children }) {
  return (
    <div className={`status-card tone-${tone}`} role="status">
      <div className="status-icon" aria-hidden="true">
        {tone === 'ok' ? '✓' : tone === 'bad' ? '!' : 'i'}
      </div>
      <div>
        <div className="status-title">{title}</div>
        {children && <div className="status-body">{children}</div>}
      </div>
    </div>
  )
}

export function FindingsTable({ findings, onSelectLine }) {
  return (
    <section className="card">
      <h3>Bulgular <span className="count">{findings.length}</span></h3>
      <div className="table-wrap">
        <table className="table findings">
          <thead>
            <tr>
              <th>Satır</th>
              <th>Desen</th>
              <th>Sorun</th>
              <th>Etki</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f, i) => (
              <tr key={i} className="clickable" onClick={() => onSelectLine(f.line)} title="Kodda göster">
                <td className="num">{f.line}</td>
                <td><code className="pattern-code">{f.pattern_code}</code></td>
                <td>
                  <div className="finding-title">{f.title}</div>
                  <div className="finding-detail">{f.detail}</div>
                </td>
                <td><ImpactBadge impact={f.impact} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function ComplexityCard({ before, after }) {
  const afterByName = new Map((after?.functions ?? []).map((f) => [f.name, f]))
  const functions = before?.functions ?? []
  return (
    <section className="card">
      <h3>Tahmini karmaşıklık</h3>
      {functions.length === 0 ? (
        <p className="muted">Üst seviye fonksiyon bulunamadı.</p>
      ) : (
        <ul className="complexity-list">
          {functions.map((f) => {
            const next = afterByName.get(f.name)
            const improved = next && next.complexity !== f.complexity
            return (
              <li key={f.name}>
                <span className="fn-name">{f.name}</span>
                <span className="complexity">
                  <span className={improved ? 'cx-old' : 'cx'}>{f.complexity}</span>
                  {next && (
                    <>
                      <span className="arrow" aria-label="sonra">→</span>
                      <span className={improved ? 'cx-new' : 'cx'}>{next.complexity}</span>
                    </>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      <p className="footnote">Kodun yapısından (AST) çıkarılan tahmindir, ölçüm değildir.</p>
    </section>
  )
}

/** Ölçülen süre farkından TAHMİNİ enerji etkisi. Varsayımlar kartta değiştirilebilir; hesap backend'de
 *  (energy.py) yapılır, böylece formül tek yerdedir. */
export function EnergyEstimate({ initial, oldSeconds, newSeconds }) {
  const [watts, setWatts] = useState(String(initial.watts))
  const [runs, setRuns] = useState(String(initial.runs_per_day))
  const [estimate, setEstimate] = useState(initial)
  const [error, setError] = useState(null)

  const w = Number(watts)
  const r = Number(runs)
  const valid = watts !== '' && runs !== '' && w > 0 && r > 0

  useEffect(() => {
    if (!valid) return
    if (w === initial.watts && r === initial.runs_per_day) {
      setEstimate(initial)
      setError(null)
      return
    }
    let current = true // eski istekler yeni sonucun üzerine yazmasın
    const id = setTimeout(() => {
      api
        .energyEstimate({ old_seconds: oldSeconds, new_seconds: newSeconds, watts: w, runs_per_day: r })
        .then((body) => current && (setEstimate(body.estimate), setError(null)))
        .catch((e) => current && setError(e.message))
    }, 150)
    return () => {
      current = false
      clearTimeout(id)
    }
  }, [valid, w, r, initial, oldSeconds, newSeconds])

  return (
    <div className="energy">
      <div className="energy-header">
        <h4>Tahmini enerji etkisi</h4>
        <span className="badge estimate-badge">Tahmin · ölçüm değil</span>
      </div>
      {valid && estimate ? (
        <div className="energy-value">
          <span className="energy-number">≈ {formatEstimate(estimate.kwh_per_year)} kWh</span>
          <span className="speedup-label">yıllık tasarruf</span>
        </div>
      ) : (
        <p className="muted small">{valid ? 'Tahmin hesaplanamadı.' : 'Varsayımlar pozitif sayı olmalı.'}</p>
      )}
      {valid && estimate && (
        <p className="muted small">Çalıştırma başına ≈ {formatEstimate(estimate.joules_per_run)} J</p>
      )}
      <div className="energy-inputs">
        <Field label="İşlemci gücü (W)" inline>
          <input type="number" min="1" step="1" value={watts} onChange={(e) => setWatts(e.target.value)} />
        </Field>
        <Field label="Günde çalışma sayısı" inline>
          <input type="number" min="1" step="1000" value={runs} onChange={(e) => setRuns(e.target.value)} />
        </Field>
      </div>
      {error && <p className="error-text">{error}</p>}
      <p className="footnote">{valid ? energyAssumptionNote(w, r) : 'Gerçek tüketim donanıma ve kullanıma bağlıdır.'}</p>
    </div>
  )
}

export function BenchmarkCard({ benchmark, energy }) {
  if (!benchmark || benchmark.old_seconds == null || benchmark.new_seconds == null) {
    const reason =
      benchmark?.error ||
      benchmark?.functions?.find((f) => f.error)?.error ||
      (benchmark?.functions?.some((f) => f.outputs_equal === false) &&
        'eski ve yeni kod ölçüm girdisinde farklı sonuç verdi')
    return (
      <section className="card">
        <h3>Ölçülen süre</h3>
        <p className="muted">Performans ölçümü yapılamadı{reason ? `: ${reason}` : '.'}</p>
      </section>
    )
  }
  const { old_seconds: oldS, new_seconds: newS, speedup, speedup_is_lower_bound: lowerBound } = benchmark
  const max = Math.max(oldS, newS) || 1
  const faster = speedup >= 1
  return (
    <section className="card">
      <h3>Ölçülen süre</h3>
      {speedup == null ? (
        <p className="muted">Süreler 1 µs'nin altında; hızlanma oranı güvenilir biçimde hesaplanamadı.</p>
      ) : (
        <div className="speedup">
          <span className={faster ? 'speedup-value' : 'speedup-value slower'}>
            {lowerBound && '≥ '}
            {formatSpeedup(faster ? speedup : 1 / speedup)}
          </span>
          <span className="speedup-label">{faster ? 'kat hızlı' : 'kat yavaş'}</span>
        </div>
      )}
      {lowerBound && (
        <p className="footnote warn-text">
          Yeşil Kod süresi 1 µs'nin altında, ölçüm çözünürlüğüne yakın. Hızlanma 1 µs'ye göre hesaplanan bir alt
          sınırdır.
        </p>
      )}
      <div className="bars">
        {[
          ['Eski kod', oldS, 'bar-old'],
          ['Yeşil Kod', newS, 'bar-new'],
        ].map(([label, value, cls]) => (
          <div className="bar-row" key={label}>
            <span className="bar-label">{label}</span>
            <div className="bar-track">
              <div className={`bar ${cls}`} style={{ width: `${Math.max((value / max) * 100, 0.8)}%` }} />
            </div>
            <span className="bar-value">{formatSeconds(value)}</span>
          </div>
        ))}
      </div>
      {benchmark.functions?.some((f) => f.error) && (
        <p className="footnote warn-text">
          {benchmark.functions.filter((f) => f.error).map((f) => `${f.function}: ${f.error}`).join(' · ')}
        </p>
      )}
      {benchmark.functions?.some((f) => f.auto && f.worst_case == null && !f.note) && (
        <p className="footnote warn-text">
          Ölçüm girdisi sistem tarafından örnek girdilerden otomatik üretildi; en kötü durumu temsil
          etmeyebilir.
        </p>
      )}
      {benchmark.functions?.filter((f) => f.note).map((f) => (
        <p className={`footnote${f.worst_case == null ? ' warn-text' : ''}`} key={`note-${f.function}`}>
          {f.function}: {f.note}
        </p>
      ))}
      {benchmark.functions?.filter((f) => f.worst_case === false).map((f) => (
        <p className="footnote warn-text" key={`worst-${f.function}`}>
          {f.function}: eşleşmesiz (en kötü durum) girdi bulunamadı; fonksiyon ölçümde erken döndü, kazanç
          olduğundan küçük görünebilir.
        </p>
      ))}
      <p className="footnote">
        <strong>Gerçek ölçüm (süre):</strong> iki sürüm aynı rastgele girdiyle yalıtılmış bir süreçte
        çalıştırıldı (timeit, 3 tekrarın en iyisi; her tekrar önbelleği boş, temiz yüklenmiş kodla başlar). Ölçüm, mümkün olduğunda en kötü durum girdisiyle yapılır.
        Sonuç sunucu donanımına bağlıdır. Enerji ölçülmez; aşağıdaki
        kWh değeri bu süre farkından varsayımlarla hesaplanan bir tahmindir.
      </p>
      {energy && <EnergyEstimate key={`${oldS}:${newS}`} initial={energy} oldSeconds={oldS} newSeconds={newS} />}
    </section>
  )
}

export function EquivalenceTable({ verification }) {
  const { cases = [], passed, error, timed_out: timedOut } = verification
  return (
    <section className="card">
      <h3>
        Eşdeğerlik testi
        <span className={`badge ${passed ? 'pass' : 'fail'}`}>{passed ? 'Geçti' : 'Geçmedi'}</span>
      </h3>
      {(error || timedOut) && <p className="error-text">{error || 'Zaman aşımı.'}</p>}
      {cases.length > 0 && (
        <div className="table-wrap">
          <table className="table equivalence">
            <thead>
              <tr>
                <th>Girdi</th>
                <th>Eski sonuç</th>
                <th>Yeni sonuç</th>
                <th className="center">Eşit</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c, i) => (
                <tr key={i} className={c.equal ? '' : 'row-fail'}>
                  <td>
                    <code>{c.function}(*{c.input})</code>
                    {c.derived && <div className="finding-detail">Sistemin türettiği girdi ({c.derived})</div>}
                  </td>
                  <td><code>{c.old ?? '—'}</code></td>
                  <td>
                    <code>{c.new ?? '—'}</code>
                    {c.note && <div className={c.side_effect ? 'finding-detail fail-text' : 'finding-detail'}>{c.note}</div>}
                    {c.side_effect?.map((change) => (
                      <div className="finding-detail" key={change.name}>
                        <code>{change.name}</code> çağrıdan sonra: eski kodda <code>{change.old}</code>, yeni kodda{' '}
                        <code>{change.new}</code>
                      </div>
                    ))}
                    {c.minimal && (
                      <div className="finding-detail">
                        En küçük karşı örnek: <code>{c.function}(*{c.minimal.input})</code> → eski{' '}
                        <code>{c.minimal.old}</code>, yeni <code>{c.minimal.new}</code>
                      </div>
                    )}
                  </td>
                  <td className="center" aria-label={c.equal ? 'eşit' : c.side_effect ? 'yan etki farkı' : 'farklı'}>
                    {c.equal ? '✅' : '❌'}
                    {c.side_effect && <div className="finding-detail fail-text nowrap">yan etki</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function ChangesCard({ changes, notes, warnings }) {
  if (!changes?.length && !notes && !warnings?.length) return null
  return (
    <section className="card">
      <h3>Yapılan değişiklikler</h3>
      {changes?.length > 0 && (
        <ul className="changes">
          {changes.map((c, i) => (
            <li key={i}>
              <code className="pattern-code">{c.pattern}</code>
              <span>{c.explanation}</span>
            </li>
          ))}
        </ul>
      )}
      {notes && <p className="notes"><strong>Not:</strong> {notes}</p>}
      {warnings?.length > 0 && (
        <ul className="warnings">
          {warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </section>
  )
}
