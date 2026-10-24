import { formatDate } from '../format.js'
import DiffView from './DiffView.jsx'
import {
  BenchmarkCard,
  ChangesCard,
  ComplexityCard,
  EquivalenceTable,
  FindingsTable,
  StatusCard,
} from './ResultCards.jsx'

const CLEAN_TITLE = 'İsraf tespit edilmedi'
const OPTIMIZED_TITLE = 'Optimize edildi ve doğrulandı'
const FAILED_TITLE = 'Doğrulanmış optimizasyon üretilemedi'

/** Sonucun statik analiz kısmı. Geçmiş kayıtlarında yalnızca bulgular saklanır. */
export function analysisOf({ kind, data }) {
  if (kind === 'analyze') return data
  if (kind === 'history') return { findings: data.findings }
  return data.analysis
}

/** Geçmişten yüklenen kayıt: aynı kurallar (başarısızsa kod önerilmez, kopyalanamaz). */
function HistoryResult({ code, run, onSelectLine }) {
  const failed = run.status === 'failed'
  const title = { clean: CLEAN_TITLE, optimized: OPTIMIZED_TITLE }[run.status] ?? FAILED_TITLE
  return (
    <div className="results">
      <StatusCard tone={failed ? 'bad' : 'ok'} title={title}>
        {failed && 'Doğrulanmış bir optimizasyon üretilemedi; orijinal kodu kullanmaya devam edin. '}
        Geçmiş kaydı ({formatDate(run.created_at)}). Ayrıntılı doğrulama tablosu saklanmaz; yeniden
        doğrulamak için “Optimize Et”i kullanın.
      </StatusCard>
      {run.findings.length > 0 && <FindingsTable findings={run.findings} onSelectLine={onSelectLine} />}
      {run.green_code && <DiffView oldCode={code} newCode={run.green_code} failed={failed} />}
    </div>
  )
}

/** result: { kind: 'analyze' | 'optimize' | 'history', code, data } */
export default function ResultView({ result, onSelectLine }) {
  const { kind, code, data } = result
  if (kind === 'history') return <HistoryResult code={code} run={data} onSelectLine={onSelectLine} />

  const analysis = analysisOf(result)
  const syntaxError = analysis?.syntax_error
  const findings = analysis?.findings ?? []

  if (syntaxError) {
    return (
      <div className="results">
        <StatusCard tone="bad" title="Sözdizimi hatası">
          Satır {syntaxError.line ?? '?'}: {syntaxError.message}
        </StatusCard>
      </div>
    )
  }

  if (kind === 'analyze') {
    return (
      <div className="results">
        {findings.length === 0 ? (
          <StatusCard tone="ok" title={CLEAN_TITLE}>
            Statik analiz, bilinen Yeşil Kod desenlerine aykırı bir yapı bulmadı.
          </StatusCard>
        ) : (
          <StatusCard tone="info" title={`${findings.length} bulgu tespit edildi`}>
            Yeniden yazım ve doğrulama için “Optimize Et”i kullanın.
          </StatusCard>
        )}
        {findings.length > 0 && <FindingsTable findings={findings} onSelectLine={onSelectLine} />}
        <div className="grid-2">
          <ComplexityCard before={analysis} />
        </div>
      </div>
    )
  }

  if (data.status === 'clean') {
    return (
      <div className="results">
        <StatusCard tone="ok" title={CLEAN_TITLE}>{data.message}</StatusCard>
        <div className="grid-2">
          <ComplexityCard before={analysis} />
        </div>
      </div>
    )
  }

  const optimized = data.status === 'optimized'
  return (
    <div className="results">
      <StatusCard
        tone={optimized ? 'ok' : 'bad'}
        title={optimized ? OPTIMIZED_TITLE : FAILED_TITLE}
      >
        {data.message}
        {data.attempts > 1 && ` (${data.attempts} deneme)`}
        {!optimized && data.error && <div className="error-text">{data.error}</div>}
      </StatusCard>

      {findings.length > 0 && <FindingsTable findings={findings} onSelectLine={onSelectLine} />}

      <div className="grid-2">
        <ComplexityCard before={analysis} after={data.analysis_after} />
        {data.verification && (
          <BenchmarkCard benchmark={data.verification.benchmark} energy={optimized ? data.energy : null} />
        )}
      </div>

      {data.green_code && <DiffView oldCode={code} newCode={data.green_code} failed={!optimized} />}
      {data.verification && <EquivalenceTable verification={data.verification} />}
      <ChangesCard changes={data.changes} notes={data.notes} warnings={data.warnings} />

      {optimized && data.green_code && (
        <p className="review-warning" role="note">
          ⚠ Bu kodu projeye almadan önce eşdeğerlik testini inceleyin.
        </p>
      )}
    </div>
  )
}
