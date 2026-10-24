import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import {
  energyAssumptionNote,
  formatDate,
  formatEstimate,
  formatPercent,
  formatSeconds,
  formatSpeedup,
} from '../format.js'

function StatTile({ label, value, sub }) {
  return (
    <div className="card stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

/** ["YK-01", "YK-02", "YK-05"] -> YK-01, 02, 05 (kod adı satır sonunda bölünmez) */
function ShortCodes({ codes }) {
  const [first, ...rest] = codes
  return (
    <>
      <span className="nowrap">{first}</span>
      {rest.map((c) => `, ${c.replace(/^YK-/, '')}`).join('')}
    </>
  )
}

/** 4+ benzersiz kodda medyan; 1–3 kodda medyan yanıltıcı olacağından değerler tek tek. */
function SpeedupTile({ label, group, scope }) {
  const listed = group.items?.length > 0
  return (
    <StatTile
      label={label}
      value={
        !group.runs ? (
          '—'
        ) : listed ? (
          <span className="stat-items">
            {group.items.map((item, i) => (
              <Fragment key={i}>
                {i > 0 && ' · '}
                <span className="nowrap">
                  {item.label} <strong>{formatSpeedup(item.speedup)}</strong>
                </span>
              </Fragment>
            ))}
          </span>
        ) : (
          formatSpeedup(group.median_speedup)
        )
      }
      sub={
        <>
          {listed ? 'Hızlanma' : 'Medyan hızlanma'} · {group.runs} benzersiz kod
          <br />
          {scope} <ShortCodes codes={group.codes} />
        </>
      }
    />
  )
}

function Summary({ report }) {
  const { total_runs: total, status_counts: counts, savings } = report
  const attempted = counts.optimized + counts.failed
  const measured = savings.measured_runs > 0
  return (
    <div className="stat-grid">
      <StatTile
        label="Toplam analiz"
        value={total}
        sub={
          <>
            {counts.optimized} optimize · {counts.clean} temiz · {counts.failed} başarısız
            <br />
            {report.unique_codes} benzersiz fonksiyon
          </>
        }
      />
      <StatTile
        label="Doğrulama başarı oranı"
        value={attempted ? formatPercent(report.success_rate) : '—'}
        sub={attempted ? `${counts.optimized} / ${attempted} öneri doğrulandı` : 'Henüz optimizasyon denenmedi'}
      />
      <SpeedupTile label="Yüksek etkili optimizasyonlar" group={savings.speedup_groups.high} scope="içeren:" />
      <SpeedupTile label="Düşük etkili optimizasyonlar" group={savings.speedup_groups.low} scope="yalnızca" />
      <StatTile
        label="Toplam süre kazancı"
        value={measured ? formatSeconds(savings.total_seconds) : '—'}
        sub={measured ? `Medyan ${formatSeconds(savings.median_seconds)} / benzersiz kod` : 'Ölçüm yok'}
      />
    </div>
  )
}

function EnergyCard({ energy }) {
  const has = energy.estimated_runs > 0
  return (
    <section className="card energy">
      <div className="energy-header">
        <h3>Toplam tahmini yıllık enerji tasarrufu</h3>
        <span className="badge estimate-badge">Tahmin · ölçüm değil</span>
      </div>
      {has ? (
        <div className="energy-value">
          <span className="energy-number">≈ {formatEstimate(energy.total_kwh_per_year)} kWh</span>
          <span className="speedup-label">/ yıl · {energy.estimated_runs} benzersiz kodun doğrulanmış optimizasyonu</span>
        </div>
      ) : (
        <p className="muted">Henüz süresi kısalmış doğrulanmış bir optimizasyon yok.</p>
      )}
      <p className="footnote">
        Her doğrulanmış ve hızlanmış optimizasyonun ölçülen süre farkı ayrı ayrı enerjiye çevrilip toplanır. Aynı
        kodun tekrarlanan analizleri bir kez sayılır.{' '}
        {energyAssumptionNote(energy.watts, energy.runs_per_day, 'her optimize edilen fonksiyon')}
      </p>
    </section>
  )
}

function PatternChart({ patterns }) {
  const max = Math.max(...patterns.map((p) => p.count), 1)
  return (
    <section className="card">
      <h3>En sık tespit edilen desenler</h3>
      {patterns.length === 0 ? (
        <p className="muted">Henüz desen tespit edilmedi.</p>
      ) : (
        <ul className="pattern-bars" aria-label="Desen sıklığı">
          {patterns.map((p) => (
            <li
              key={p.code}
              className="pattern-bar-row"
              title={`${p.code} · ${p.title}: ${p.count} tespit, ${p.runs} benzersiz kodda`}
            >
              <span className="pattern-bar-label">
                <code className="pattern-code">{p.code}</code>
                <span className="pattern-bar-title">{p.title}</span>
              </span>
              <span className="bar-track">
                <span className="bar bar-new" style={{ width: `${(p.count / max) * 100}%` }} />
              </span>
              <span className="bar-value">{p.count} kez</span>
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">
        Her benzersiz kodun yalnızca en son başarılı analizi (hiç başarılı analizi yoksa en son analizi) sayılır. Bir
        kodda aynı desen birden çok satırda bulunabilir; her tespit ayrı sayılır.
      </p>
    </section>
  )
}

function TopRuns({ runs, onLoadRun }) {
  return (
    <section className="card">
      <h3>En çok kazanç sağlayan analizler</h3>
      {runs.length === 0 ? (
        <p className="muted">Henüz süre kazancı ölçülmüş doğrulanmış bir optimizasyon yok.</p>
      ) : (
        <div className="table-wrap">
          <table className="table history">
            <thead>
              <tr>
                <th>Tarih</th>
                <th>Desenler</th>
                <th className="num">Eski</th>
                <th className="num">Yeni</th>
                <th className="num">Kazanç</th>
                <th className="num">Hızlanma</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const codes = [...new Set(run.findings.map((f) => f.pattern_code))]
                return (
                  <tr key={run.id}>
                    <td className="nowrap">{formatDate(run.created_at)}</td>
                    <td>
                      {codes.length ? codes.map((c) => <code className="pattern-code" key={c}>{c}</code>) : '—'}
                    </td>
                    <td className="num">{formatSeconds(run.old_seconds)}</td>
                    <td className="num">{formatSeconds(run.new_seconds)}</td>
                    <td className="num strong">{formatSeconds(run.gain_seconds)}</td>
                    <td className="num">{formatSpeedup(run.speedup)}</td>
                    <td className="right">
                      <button type="button" className="btn btn-link" onClick={() => onLoadRun(run)}>
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
      {runs.length > 0 && <p className="footnote">Her kod bir kez listelenir (en son başarılı analizi).</p>}
    </section>
  )
}

export default function ReportTab({ onLoadRun }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setError(null)
    api.report().then(setReport).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  if (error) return <p className="error-banner">{error}</p>
  if (!report) return <p className="muted">Rapor yükleniyor…</p>

  return (
    <div className="results">
      <div className="card-header">
        <h3>Kurum geneli enerji verimliliği</h3>
        <button type="button" className="btn btn-secondary" onClick={load}>Yenile</button>
      </div>
      <Summary report={report} />
      <p className="note" role="note">Tüm değerler bu kurulumda yapılan gerçek analizlerden hesaplanır.</p>
      <EnergyCard energy={report.savings.energy} />
      <PatternChart patterns={report.patterns} />
      <TopRuns runs={report.top_runs} onLoadRun={onLoadRun} />
      <p className="footnote">
        Süre kazancı yalnızca eşdeğerlik testinden geçmiş optimizasyonların ölçülen çalışma sürelerinden (eski − yeni)
        hesaplanır ve sunucu donanımına bağlıdır. Ölçülen değer süredir; kWh değeri ölçüm değil, bu sürelerden
        varsayımlarla hesaplanan bir tahmindir.
      </p>
    </div>
  )
}
