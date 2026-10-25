import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { api } from '../api.js'
import PatternsTab from '../components/PatternsTab.jsx'

vi.mock('../api.js', () => ({
  api: { patterns: vi.fn(), updatePattern: vi.fn(), setPatternActive: vi.fn() },
}))

const PATTERNS = [
  {
    code: 'YK-01',
    title: 'İç içe döngü',
    anti_pattern: 'Eski sorun',
    solution: 'Eski çözüm',
    impact: 'yüksek',
    example_before: 'x = 1',
    example_after: 'y = 2',
    is_active: true,
    updated_at: '2026-10-24T10:00:00+00:00',
    example_inputs: { f: [[1], [2]] },
  },
  {
    code: 'YK-02',
    title: 'Listede üyelik',
    anti_pattern: 'Sorun 2',
    solution: 'Çözüm 2',
    impact: 'orta',
    example_before: 'a = 1',
    example_after: 'b = 2',
    is_active: false,
    updated_at: null,
    example_inputs: null,
  },
]

const card = (code) => screen.getByText(code).closest('article')

beforeEach(() => {
  vi.mocked(api.patterns).mockResolvedValue(PATTERNS)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('PatternsTab', () => {
  it('yönetim notunu gösterir, pasif desen soluk görünür', async () => {
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    expect(screen.getByText(/Yeni desen türleri için tespit kuralı eklenmesi gerekir/)).toBeTruthy()
    expect(card('YK-01').classList.contains('inactive')).toBe(false)
    expect(card('YK-02').classList.contains('inactive')).toBe(true)
    expect(screen.queryByRole('button', { name: /ekle/i })).toBeNull() // yeni desen ekleme yok
  })

  it('Düzenle → form; Kaydet API çağırır ve kartı günceller', async () => {
    vi.mocked(api.updatePattern).mockImplementation(async (code, form) => ({ ...PATTERNS[0], ...form }))
    render(<PatternsTab />)
    await screen.findByText('YK-01')

    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    const form = within(card('YK-01'))
    fireEvent.change(form.getByLabelText('Çözüm'), { target: { value: 'Yeni çözüm' } })
    fireEvent.change(form.getByLabelText('Etki'), { target: { value: 'düşük' } })
    fireEvent.click(form.getByRole('button', { name: 'Kaydet' }))

    await screen.findByText('Yeni çözüm')
    expect(api.updatePattern).toHaveBeenCalledWith('YK-01', {
      anti_pattern: 'Eski sorun',
      solution: 'Yeni çözüm',
      impact: 'düşük',
      example_before: 'x = 1',
      example_after: 'y = 2',
      example_inputs: { f: [[1], [2]] },
    })
    expect(within(card('YK-01')).queryByRole('button', { name: 'Kaydet' })).toBeNull()
  })

  it('İptal değişiklikleri atar', async () => {
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    fireEvent.change(within(card('YK-01')).getByLabelText('Çözüm'), { target: { value: 'Vazgeçilen' } })
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'İptal' }))

    expect(screen.getByText('Eski çözüm')).toBeTruthy()
    expect(screen.queryByText('Vazgeçilen')).toBeNull()
    expect(api.updatePattern).not.toHaveBeenCalled()
  })

  it('sunucu 400 dönerse hata formda gösterilir', async () => {
    vi.mocked(api.updatePattern).mockRejectedValue(new Error('İstek başarısız: Çözüm boş olamaz.'))
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Kaydet' }))

    await screen.findByText(/Çözüm boş olamaz/)
    expect(within(card('YK-01')).getByRole('button', { name: 'Kaydet' })).toBeTruthy() // form açık kalır
  })

  it('aktif/pasif anahtarı API çağırır ve kartı soluklaştırır', async () => {
    vi.mocked(api.setPatternActive).mockResolvedValue({ ...PATTERNS[0], is_active: false })
    render(<PatternsTab />)
    await screen.findByText('YK-01')

    fireEvent.click(within(card('YK-01')).getByRole('switch'))

    await waitFor(() => expect(card('YK-01').classList.contains('inactive')).toBe(true))
    expect(api.setPatternActive).toHaveBeenCalledWith('YK-01', false)
  })

  it('test girdileri okunabilir JSON olarak gelir ve düzenlenebilir', async () => {
    vi.mocked(api.updatePattern).mockImplementation(async (code, form) => ({ ...PATTERNS[0], ...form }))
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    const field = within(card('YK-01')).getByLabelText('Test girdileri (JSON)')
    expect(field.value).toBe('{\n  "f": [[1],[2]]\n}')

    fireEvent.change(field, { target: { value: '{"f": [[3], [4, 5]]}' } })
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Kaydet' }))
    await waitFor(() => expect(api.updatePattern).toHaveBeenCalled())
    expect(api.updatePattern.mock.calls[0][1].example_inputs).toEqual({ f: [[3], [4, 5]] })
  })

  it.each([
    ['{bozuk', 'Test girdileri geçerli JSON değil'],
    ['[[1]]', 'biçiminde olmalı'],
    ['{"f": [1, 2]}', 'biçiminde olmalı'],
  ])('geçersiz test girdisi (%s) sunucuya gönderilmez', async (text, message) => {
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    fireEvent.change(within(card('YK-01')).getByLabelText('Test girdileri (JSON)'), { target: { value: text } })
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Kaydet' }))
    expect(await within(card('YK-01')).findByText(new RegExp(message))).toBeTruthy()
    expect(api.updatePattern).not.toHaveBeenCalled()
  })

  it('eşdeğer olmayan örnek için sunucu hatası formda gösterilir', async () => {
    vi.mocked(api.updatePattern).mockRejectedValue(
      new Error("İstek başarısız: 'Sonra' örneği 'önce' örneğiyle eşdeğer değil: common(*[[1, 1]]) için önce [1, 1], sonra [1]."),
    )
    render(<PatternsTab />)
    await screen.findByText('YK-01')
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Düzenle' }))
    fireEvent.click(within(card('YK-01')).getByRole('button', { name: 'Kaydet' }))
    expect(await screen.findByText(/eşdeğer değil: common/)).toBeTruthy()
    expect(within(card('YK-01')).getByRole('button', { name: 'Kaydet' })).toBeTruthy()
  })
})

