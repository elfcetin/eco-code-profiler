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

/** result: { kind: 'analyze' | 'optimize', code, data } */
export default function ResultView({ result, onSelectLine }) {
  const { kind, code, data } = result
  const analysis = kind === 'analyze' ? data : data.analysis
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
        title={optimized ? 'Optimize edildi ve doğrulandı' : 'Doğrulanmış optimizasyon üretilemedi'}
      >
        {data.message}
        {data.attempts > 1 && ` (${data.attempts} deneme)`}
        {!optimized && data.error && <div className="error-text">{data.error}</div>}
      </StatusCard>

      {findings.length > 0 && <FindingsTable findings={findings} onSelectLine={onSelectLine} />}

      <div className="grid-2">
        <ComplexityCard before={analysis} after={data.analysis_after} />
        {data.verification && <BenchmarkCard benchmark={data.verification.benchmark} />}
      </div>

      {data.green_code && <DiffView oldCode={code} newCode={data.green_code} />}
      {data.verification && <EquivalenceTable verification={data.verification} />}
      <ChangesCard changes={data.changes} notes={data.notes} warnings={data.warnings} />

      {data.green_code && (
        <p className="review-warning" role="note">
          ⚠ Bu kodu projeye almadan önce eşdeğerlik testini inceleyin.
        </p>
      )}
    </div>
  )
}
