import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { api } from '../api.js'
import ReportTab from '../components/ReportTab.jsx'

vi.mock('../api.js', () => ({ api: { report: vi.fn() } }))

const EMPTY = {
  total_runs: 0,
  unique_codes: 0,
  status_counts: { optimized: 0, clean: 0, failed: 0 },
  success_rate: 0,
  patterns: [],
  savings: {
    measured_runs: 0, total_seconds: 0, median_seconds: 0,
    speedup_groups: {
      high: { codes: ['YK-01', 'YK-02', 'YK-05', 'YK-06', 'YK-07', 'YK-08'], runs: 0, median_speedup: 0, items: [] },
      low: { codes: ['YK-03', 'YK-04', 'YK-09', 'YK-10'], runs: 0, median_speedup: 0, items: [] },
    },
    energy: { estimated_runs: 0, total_kwh_per_year: 0, watts: 65, runs_per_day: 10000 },
  },
  top_runs: [],
}

const TOP_RUN = {
  id: 7,
  created_at: '2026-10-01T10:00:00+00:00',
  status: 'optimized',
  original_code: 'def f(a):\n    return a\n',
  green_code: 'def f(a):\n    return list(a)\n',
  findings: [{ line: 1, pattern_code: 'YK-01' }, { line: 2, pattern_code: 'YK-02' }],
  old_seconds: 1,
  new_seconds: 0.5,
  speedup: 2,
  gain_seconds: 0.5,
}

const SAMPLE = {
  total_runs: 6,
  unique_codes: 3,
  status_counts: { optimized: 4, clean: 1, failed: 1 },
  success_rate: 0.8,
  patterns: [
    { code: 'YK-01', title: 'İç içe döngü', count: 4, runs: 3 },
    { code: 'YK-02', title: 'Listede üyelik', count: 2, runs: 2 },
  ],
  savings: {
    measured_runs: 3, total_seconds: 0.75, median_seconds: 0.3,
    speedup_groups: {
      high: {
        codes: ['YK-01', 'YK-02', 'YK-05', 'YK-06', 'YK-07', 'YK-08'],
        runs: 2,
        median_speedup: 1589.4,
        items: [
          { label: 'find_duplicates', speedup: 2127.7 },
          { label: 'find_pair', speedup: 1050.2 },
        ],
      },
      low: { codes: ['YK-03', 'YK-04', 'YK-09', 'YK-10'], runs: 0, median_speedup: 0, items: [] },
    },
    energy: { estimated_runs: 2, total_kwh_per_year: 1.234567, watts: 65, runs_per_day: 10000 },
  },
  top_runs: [TOP_RUN],
}

const tile = (label) => screen.getByText(label).closest('.stat-tile')

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ReportTab', () => {
  it('boş veritabanında sıfırlar ve boş durum mesajları gösterir', async () => {
    vi.mocked(api.report).mockResolvedValue(EMPTY)
    render(<ReportTab onLoadRun={() => {}} />)

    await screen.findByText('Toplam analiz')
    expect(tile('Toplam analiz').querySelector('.stat-value').textContent).toBe('0')
    expect(tile('Doğrulama başarı oranı').querySelector('.stat-value').textContent).toBe('—')
    expect(tile('Yüksek etkili optimizasyonlar').querySelector('.stat-value').textContent).toBe('—')
    expect(tile('Düşük etkili optimizasyonlar').querySelector('.stat-value').textContent).toBe('—')
    expect(screen.queryByText('Medyan hızlanma')).toBeNull()
    expect(screen.getByText('Henüz desen tespit edilmedi.')).toBeTruthy()
    expect(screen.getByText(/Henüz süre kazancı ölçülmüş/)).toBeTruthy()
    expect(screen.getByText('Tüm değerler bu kurulumda yapılan gerçek analizlerden hesaplanır.')).toBeTruthy()
    expect(screen.getByText(/Henüz süresi kısalmış doğrulanmış bir optimizasyon yok/)).toBeTruthy()
  })

  it('örnek kayıtlarla özetleri, desen çubuklarını ve tabloyu gösterir', async () => {
    vi.mocked(api.report).mockResolvedValue(SAMPLE)
    const onLoadRun = vi.fn()
    render(<ReportTab onLoadRun={onLoadRun} />)

    await screen.findByText('Toplam analiz')
    expect(tile('Toplam analiz').querySelector('.stat-value').textContent).toBe('6')
    expect(tile('Toplam analiz').textContent).toContain('4 optimize · 1 temiz · 1 başarısız')
    expect(tile('Doğrulama başarı oranı').querySelector('.stat-value').textContent).toMatch(/%\s?80/)
    expect(tile('Toplam analiz').textContent).toContain('3 benzersiz fonksiyon')
    // Tek medyan yerine grup başına medyan; boş grup "—".
    expect(screen.queryByText('Medyan hızlanma')).toBeNull()
    // 3 veya daha az benzersiz kod: medyan yerine değerler tek tek.
    const high = tile('Yüksek etkili optimizasyonlar')
    expect(high.querySelector('.stat-value').textContent).toBe('find_duplicates 2.128× · find_pair 1.050×')
    expect(high.textContent).not.toContain('Medyan')
    expect(high.textContent).toContain('içeren: YK-01, 02, 05, 06, 07, 08')
    expect(high.textContent).toContain('2 benzersiz kod')
    const low = tile('Düşük etkili optimizasyonlar')
    expect(low.querySelector('.stat-value').textContent).toBe('—')
    expect(low.textContent).toContain('yalnızca YK-03, 04, 09, 10')
    expect(tile('Toplam süre kazancı').querySelector('.stat-value').textContent).toBe('750,0 ms')

    // Tahmini enerji kartı: değer, "tahmin" etiketi ve varsayım notu.
    const energyCard = screen.getByText('Toplam tahmini yıllık enerji tasarrufu').closest('section')
    expect(energyCard.textContent).toContain('≈ 1,23 kWh')
    expect(energyCard.textContent).toContain('Tahmin · ölçüm değil')
    expect(energyCard.textContent).toContain('Aynı kodun tekrarlanan analizleri bir kez sayılır.')
    expect(energyCard.textContent).toContain(
      'Varsayım: işlemci 65 W, her optimize edilen fonksiyon günde 10.000 kez çalışıyor. ' +
        'Gerçek tüketim donanıma ve kullanıma bağlıdır.',
    )

    // Çubuk genişlikleri en sık desene göre ölçeklenir.
    const bars = document.querySelectorAll('.pattern-bar-row .bar')
    expect([...bars].map((b) => b.style.width)).toEqual(['100%', '50%'])
    expect(screen.getByText('4 kez')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Editöre yükle' }))
    expect(onLoadRun).toHaveBeenCalledWith(TOP_RUN)
  })

  it('API hatasını gösterir', async () => {
    vi.mocked(api.report).mockRejectedValue(new Error('Sunucuya ulaşılamadı.'))
    render(<ReportTab onLoadRun={() => {}} />)
    expect(await screen.findByText('Sunucuya ulaşılamadı.')).toBeTruthy()
  })

  it('4 veya daha fazla benzersiz kodda medyan gösterir', async () => {
    const groups = {
      high: { codes: ['YK-01'], runs: 4, median_speedup: 750, items: [] },
      low: { codes: ['YK-03'], runs: 3, median_speedup: 1.2, items: [
        { label: 'a', speedup: 1.3 }, { label: 'b', speedup: 1.2 }, { label: 'c', speedup: 1.1 },
      ] },
    }
    vi.mocked(api.report).mockResolvedValue({ ...SAMPLE, savings: { ...SAMPLE.savings, speedup_groups: groups } })
    render(<ReportTab onLoadRun={() => {}} />)
    await screen.findByText('Toplam analiz')
    const high = tile('Yüksek etkili optimizasyonlar')
    expect(high.querySelector('.stat-value').textContent).toBe('750×')
    expect(high.textContent).toContain('Medyan hızlanma · 4 benzersiz kod')
    expect(tile('Düşük etkili optimizasyonlar').querySelector('.stat-value').textContent).toBe('a 1,3× · b 1,2× · c 1,1×')
  })
})
