import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, setAuthToken } from '../api.js'

afterEach(() => {
  setAuthToken(null)
  vi.unstubAllGlobals()
})

function stubFetch(status, body) {
  const fetch = vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('api istemcisi', () => {
  it('token varsa Authorization: Bearer başlığı ekler', async () => {
    const fetch = stubFetch(200, {})
    setAuthToken('tkn-123')
    await api.setPatternActive('YK-01', false)
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer tkn-123')
  })

  it('token yoksa başlık eklemez', async () => {
    const fetch = stubFetch(200, [])
    await api.patterns()
    expect(fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })

  it('hata durum kodunu taşır (401 ayırt edilebilsin)', async () => {
    stubFetch(401, { detail: 'Yönetici girişi gerekli.' })
    await expect(api.updatePattern('YK-01', {})).rejects.toMatchObject({ status: 401, message: 'İstek başarısız: Yönetici girişi gerekli.' })
  })
})
