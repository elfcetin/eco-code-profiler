import { IMPACT_CLASS, formatSeconds, formatSpeedup } from '../format.js'

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

export function BenchmarkCard({ benchmark }) {
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
  const { old_seconds: oldS, new_seconds: newS, speedup } = benchmark
  const max = Math.max(oldS, newS) || 1
  const faster = speedup >= 1
  return (
    <section className="card">
      <h3>Ölçülen süre</h3>
      <div className="speedup">
        <span className={faster ? 'speedup-value' : 'speedup-value slower'}>
          {formatSpeedup(faster ? speedup : 1 / speedup)}
        </span>
        <span className="speedup-label">{faster ? 'kat hızlı' : 'kat yavaş'}</span>
      </div>
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
      {benchmark.functions?.some((f) => f.auto) && (
        <p className="footnote warn-text">
          Ölçüm girdisi sistem tarafından örnek girdilerden otomatik üretildi; en kötü durumu temsil
          etmeyebilir.
        </p>
      )}
      <p className="footnote">
        <strong>Gerçek ölçüm:</strong> iki sürüm aynı rastgele girdiyle yalıtılmış bir süreçte çalıştırıldı
        (timeit, 3 tekrarın en iyisi). Sonuç sunucu donanımına bağlıdır; enerji (Watt/kWh) değeri değildir.
      </p>
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
                    {c.note && <div className="finding-detail">{c.note}</div>}
                    {c.minimal && (
                      <div className="finding-detail">
                        En küçük karşı örnek: <code>{c.function}(*{c.minimal.input})</code> → eski{' '}
                        <code>{c.minimal.old}</code>, yeni <code>{c.minimal.new}</code>
                      </div>
                    )}
                  </td>
                  <td className="center" aria-label={c.equal ? 'eşit' : 'farklı'}>{c.equal ? '✅' : '❌'}</td>
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
