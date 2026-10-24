import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { api } from '../api.js'
import { formatDate, parseApiDate } from '../format.js'
import HistoryTab from '../components/HistoryTab.jsx'

vi.mock('../api.js', () => ({ api: { history: vi.fn() } }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('tarih gösterimi', () => {
  it('testler UTC+3 saat diliminde çalışıyor', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('Europe/Istanbul')
  })

  it.each([
    ['2026-10-24T17:19:23.023839Z'],
    ['2026-10-24T17:19:23.023839+00:00'],
    ['2026-10-24T17:19:23.023839'], // eski API biçimi: saat dilimsiz = UTC
    ['2026-10-24T20:19:23+03:00'],
  ])('%s yerel saatle 20:19 gösterilir', (iso) => {
    expect(formatDate(iso)).toBe('24.10.2026 20:19')
  })

  it('aynı an başka bir yerel saat diliminde o bölgenin saatiyle gösterilir', () => {
    expect(formatDate('2026-10-24T17:19:23Z', 'America/New_York')).toBe('24.10.2026 13:19')
  })

  it('boş veya geçersiz tarih', () => {
    expect(parseApiDate(null)).toBeNull()
    expect(formatDate(null)).toBe('—')
    expect(formatDate('tarih değil')).toBe('—')
  })

  it('Geçmiş sekmesi UTC kaydı yerel saatle gösterir', async () => {
    vi.mocked(api.history).mockResolvedValue([
      {
        id: 1, created_at: '2026-10-24T17:19:23.023839Z', status: 'clean', original_code: 'x = 1',
        green_code: null, findings: [], old_seconds: null, new_seconds: null, speedup: null,
      },
    ])
    render(<HistoryTab onLoadRun={() => {}} />)
    expect(await screen.findByText('24.10.2026 20:19')).toBeTruthy()
  })
})
