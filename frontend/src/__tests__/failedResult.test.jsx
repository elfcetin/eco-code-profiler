import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import DiffView from '../components/DiffView.jsx'
import ResultView from '../components/ResultView.jsx'
import { EquivalenceTable } from '../components/ResultCards.jsx'

afterEach(cleanup)

const OLD = 'def f(a):\n    return [x for x in a]\n'
const NEW = 'def f(a):\n    return list(a)\n'
const FINDINGS = [{ line: 2, pattern_code: 'YK-01', title: 'İç içe döngü', detail: 'ayrıntı', impact: 'yüksek' }]

const copyButton = () => screen.queryByRole('button', { name: /Yeşil Kodu Kopyala/ })
const notRecommended = () => screen.queryByText('Önerilmez')

function optimizeResult(status) {
  return {
    kind: 'optimize',
    code: OLD,
    data: {
      status,
      message:
        status === 'failed'
          ? 'Doğrulanmış bir optimizasyon üretilemedi; orijinal kodu kullanmaya devam edin.'
          : 'Kod optimize edildi ve davranışın korunduğu doğrulandı.',
      analysis: { syntax_error: null, functions: [], findings: FINDINGS },
      analysis_after: null,
      green_code: NEW,
      changes: [],
      verification: null,
      notes: '',
      warnings: [],
      attempts: 2,
      error: status === 'failed' ? 'Optimize edilmiş kod orijinalle aynı sonuçları vermedi.' : null,
    },
  }
}

function historyResult(status) {
  return {
    kind: 'history',
    code: OLD,
    data: {
      id: 1,
      created_at: '2026-10-24T10:00:00+00:00',
      status,
      original_code: OLD,
      green_code: NEW,
      findings: FINDINGS,
      old_seconds: null,
      new_seconds: null,
      speedup: null,
    },
  }
}

describe('DiffView', () => {
  it('başarılı sonuçta kopyala düğmesi var, Önerilmez etiketi yok', () => {
    render(<DiffView oldCode={OLD} newCode={NEW} />)
    expect(copyButton()).not.toBeNull()
    expect(notRecommended()).toBeNull()
  })

  it('başarısız sonuçta kopyala düğmesi gizli, Önerilmez etiketi var', () => {
    render(<DiffView oldCode={OLD} newCode={NEW} failed />)
    expect(copyButton()).toBeNull()
    expect(notRecommended()).not.toBeNull()
  })
})

describe('ResultView (Optimize Et)', () => {
  it('failed: kırmızı uyarı kartı kalır, kod kopyalanamaz', () => {
    render(<ResultView result={optimizeResult('failed')} onSelectLine={() => {}} />)
    expect(screen.getByText('Doğrulanmış optimizasyon üretilemedi')).toBeTruthy()
    expect(screen.getByText(/orijinal kodu kullanmaya devam edin/)).toBeTruthy()
    expect(copyButton()).toBeNull()
    expect(notRecommended()).not.toBeNull()
    expect(screen.queryByText(/projeye almadan önce/)).toBeNull()
  })

  it('optimized: kopyala düğmesi görünür', () => {
    render(<ResultView result={optimizeResult('optimized')} onSelectLine={() => {}} />)
    expect(copyButton()).not.toBeNull()
    expect(notRecommended()).toBeNull()
  })
})

describe('ResultView (Geçmişten yükleme)', () => {
  it('failed kayıt: aynı kurallar geçerli', () => {
    render(<ResultView result={historyResult('failed')} onSelectLine={() => {}} />)
    expect(screen.getByText('Doğrulanmış optimizasyon üretilemedi')).toBeTruthy()
    expect(screen.getByText(/orijinal kodu kullanmaya devam edin/)).toBeTruthy()
    expect(copyButton()).toBeNull()
    expect(notRecommended()).not.toBeNull()
  })

  it('optimized kayıt: kopyala düğmesi görünür', () => {
    render(<ResultView result={historyResult('optimized')} onSelectLine={() => {}} />)
    expect(copyButton()).not.toBeNull()
    expect(notRecommended()).toBeNull()
  })
})

describe('Eşdeğerlik tablosu: yan etki farkı', () => {
  it('argümanın çağrı sonrası halini eski/yeni olarak gösterir', () => {
    const verification = {
      passed: false,
      error: 'Yan etki farkı: dönüş değerleri orijinalle aynı, ancak yeni kod argümanları farklı değiştiriyor (ör. `tasks` = [1, 2, 3] için çağrı sonrası orijinalde [], yeni kodda [1, 2, 3]).',
      cases: [{
        function: 'process_queue', input: '[[1, 2, 3]]', old: '[2, 4, 6]', new: '[2, 4, 6]', equal: false,
        note: 'Yan etki farkı: dönüş değerleri aynı, ama `tasks` çağrıdan sonra orijinal koddakinden farklı kalıyor.',
        side_effect: [{ name: 'tasks', before: '[1, 2, 3]', old: '[]', new: '[1, 2, 3]' }],
      }],
    }
    render(<EquivalenceTable verification={verification} />)
    expect(screen.getByText(/^Yan etki farkı: dönüş değerleri orijinalle aynı/)).toBeTruthy()
    const row = screen.getByText(/çağrıdan sonra: eski kodda/).closest('tr')
    expect(row.textContent).toContain('tasks çağrıdan sonra: eski kodda [], yeni kodda [1, 2, 3]')
    expect(row.querySelector('[aria-label="yan etki farkı"]').textContent).toContain('yan etki')
  })
})
