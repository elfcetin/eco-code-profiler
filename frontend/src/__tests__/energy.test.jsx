import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { api } from '../api.js'
import { BenchmarkCard } from '../components/ResultCards.jsx'
import ResultView from '../components/ResultView.jsx'

vi.mock('../api.js', () => ({ api: { energyEstimate: vi.fn() } }))

const BENCH = { old_seconds: 0.5, new_seconds: 0.1, speedup: 5, functions: [] }
// energy.estimate(0.5, 0.1) = 0,4 s × 65 W = 26 J; × 10.000 × 365 / 3.600.000 ≈ 26,36 kWh
const ENERGY = { joules_per_run: 26, kwh_per_year: 26.361111, watts: 65, runs_per_day: 10000 }

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

const card = () => screen.getByText('Tahmini enerji etkisi').closest('.energy')

describe('Tahmini enerji etkisi', () => {
  it('yıllık kWh, tahmin etiketi ve varsayım notunu gösterir', () => {
    render(<BenchmarkCard benchmark={BENCH} energy={ENERGY} />)
    expect(card().textContent).toContain('≈ 26,4 kWh')
    expect(card().textContent).toContain('Tahmin · ölçüm değil')
    expect(card().textContent).toContain('Çalıştırma başına ≈ 26 J')
    expect(card().textContent).toContain(
      'Varsayım: işlemci 65 W, fonksiyon günde 10.000 kez çalışıyor. Gerçek tüketim donanıma ve kullanıma bağlıdır.',
    )
    // Süre notu ölçümün süre, kWh'in tahmin olduğunu söyler.
    expect(screen.getByText(/Enerji ölçülmez; aşağıdaki kWh değeri/)).toBeTruthy()
    expect(screen.getByText(/Ölçüm, mümkün olduğunda en kötü durum girdisiyle yapılır\./)).toBeTruthy()
  })

  it('en kötü durum girdisi notlarını gösterir', () => {
    const functions = [
      { function: 'find_pair', auto: true, worst_case: true, note: "LLM'in ölçüm girdisinde fonksiyon erken döndüğü için sistemin eşleşmesiz (en kötü durum) girdisi kullanıldı." },
      { function: 'first', auto: true, worst_case: false, note: null },
    ]
    render(<BenchmarkCard benchmark={{ ...BENCH, functions }} energy={null} />)
    expect(screen.getByText(/find_pair: LLM'in ölçüm girdisinde fonksiyon erken döndüğü/)).toBeTruthy()
    expect(screen.getByText(/first: eşleşmesiz \(en kötü durum\) girdi bulunamadı/)).toBeTruthy()
    // En kötü durum doğrulanmış otomatik girdi için "temsil etmeyebilir" uyarısı çıkmaz.
    expect(screen.queryByText(/en kötü durumu temsil\s+etmeyebilir/)).toBeNull()
  })

  it('varsayım değişince backend yeniden hesaplar ve sonuç güncellenir', async () => {
    vi.useFakeTimers()
    vi.mocked(api.energyEstimate).mockResolvedValue({
      estimate: { joules_per_run: 12, kwh_per_year: 0.4383, watts: 30, runs_per_day: 1000 },
    })
    render(<BenchmarkCard benchmark={BENCH} energy={ENERGY} />)

    fireEvent.change(screen.getByLabelText('İşlemci gücü (W)'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('Günde çalışma sayısı'), { target: { value: '1000' } })
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(api.energyEstimate).toHaveBeenCalledTimes(1) // ardışık değişiklikler tek istekte
    expect(api.energyEstimate).toHaveBeenCalledWith({ old_seconds: 0.5, new_seconds: 0.1, watts: 30, runs_per_day: 1000 })
    expect(card().textContent).toContain('≈ 0,438 kWh')
    expect(card().textContent).toContain('Varsayım: işlemci 30 W, fonksiyon günde 1.000 kez çalışıyor.')
  })

  it('geçersiz varsayımda istek atmaz ve uyarır', async () => {
    vi.useFakeTimers()
    render(<BenchmarkCard benchmark={BENCH} energy={ENERGY} />)
    fireEvent.change(screen.getByLabelText('İşlemci gücü (W)'), { target: { value: '0' } })
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(api.energyEstimate).not.toHaveBeenCalled()
    expect(card().textContent).toContain('Varsayımlar pozitif sayı olmalı.')
    expect(card().textContent).not.toContain('kWh')
  })

  it('tahmin yoksa (yavaşlama / ölçüm yok) bölüm gösterilmez', () => {
    render(<BenchmarkCard benchmark={{ ...BENCH, old_seconds: 0.1, new_seconds: 0.5 }} energy={null} />)
    expect(screen.queryByText('Tahmini enerji etkisi')).toBeNull()
  })

  it('başarısız sonuçta enerji tahmini gösterilmez', () => {
    const result = {
      kind: 'optimize',
      code: 'x = 1\n',
      data: {
        status: 'failed', message: '', analysis: { findings: [], functions: [] }, analysis_after: null,
        green_code: null, changes: [], notes: '', warnings: [], attempts: 2, error: 'hata',
        verification: { passed: false, cases: [], benchmark: BENCH }, energy: ENERGY,
      },
    }
    render(<ResultView result={result} onSelectLine={() => {}} />)
    expect(screen.getByText('Ölçülen süre')).toBeTruthy()
    expect(screen.queryByText('Tahmini enerji etkisi')).toBeNull()
  })
})
