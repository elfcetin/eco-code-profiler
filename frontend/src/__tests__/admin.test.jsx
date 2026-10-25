import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api, setAuthToken } from '../api.js'
import AdminControls from '../components/AdminControls.jsx'
import { useAdminSession } from '../adminSession.js'

vi.mock('../api.js', () => ({
  api: { adminStatus: vi.fn(), adminLogin: vi.fn(), adminLogout: vi.fn() },
  setAuthToken: vi.fn(),
}))

function Harness() {
  const admin = useAdminSession()
  return <AdminControls admin={admin} />
}

const inHours = (h) => new Date(Date.now() + h * 3600 * 1000).toISOString()

beforeEach(() => {
  localStorage.clear()
  vi.mocked(api.adminStatus).mockResolvedValue({ enabled: true })
  vi.mocked(api.adminLogout).mockResolvedValue(null)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

async function loginWith(password) {
  fireEvent.click(screen.getByRole('button', { name: 'Yönetici girişi' }))
  fireEvent.change(screen.getByLabelText('Yönetici şifresi'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Giriş' }))
}

describe('Yönetici girişi', () => {
  it('doğru şifreyle "Yönetici modu" ve "Çıkış" görünür, token API\'ye verilir', async () => {
    vi.mocked(api.adminLogin).mockResolvedValue({ token: 'tkn', user: 'admin', expires_at: inHours(8) })
    render(<Harness />)
    await loginWith('dogru')
    expect(await screen.findByText('Yönetici modu')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Çıkış' })).toBeTruthy()
    expect(api.adminLogin).toHaveBeenCalledWith('dogru')
    expect(setAuthToken).toHaveBeenLastCalledWith('tkn')
  })

  it('yanlış şifrede hata gösterir, giriş yapılmaz', async () => {
    vi.mocked(api.adminLogin).mockRejectedValue(Object.assign(new Error('İstek başarısız: Şifre yanlış.'), { status: 401 }))
    render(<Harness />)
    await loginWith('yanlis')
    expect(await screen.findByText('Şifre yanlış.')).toBeTruthy()
    expect(screen.queryByText('Yönetici modu')).toBeNull()
  })

  it('Çıkış oturumu kapatır ve token\'ı siler', async () => {
    vi.mocked(api.adminLogin).mockResolvedValue({ token: 'tkn', user: 'admin', expires_at: inHours(8) })
    render(<Harness />)
    await loginWith('dogru')
    fireEvent.click(await screen.findByRole('button', { name: 'Çıkış' }))
    expect(await screen.findByRole('button', { name: 'Yönetici girişi' })).toBeTruthy()
    expect(api.adminLogout).toHaveBeenCalled()
    expect(setAuthToken).toHaveBeenLastCalledWith(null)
  })

  it('token süresi dolunca otomatik çıkış yapar', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(api.adminLogin).mockResolvedValue({ token: 'tkn', user: 'admin', expires_at: inHours(8) })
    render(<Harness />)
    await loginWith('dogru')
    await screen.findByText('Yönetici modu')
    await act(async () => {
      vi.advanceTimersByTime(8 * 3600 * 1000 + 1000)
    })
    await waitFor(() => expect(screen.queryByText('Yönetici modu')).toBeNull())
    expect(setAuthToken).toHaveBeenLastCalledWith(null)
  })

  it('sayfa yenilenince geçerli oturum korunur, süresi dolmuş olan yüklenmez', () => {
    localStorage.setItem('eco-admin-session', JSON.stringify({ token: 'eski', user: 'admin', expiresAt: inHours(-1) }))
    const { unmount } = render(<Harness />)
    expect(screen.getByRole('button', { name: 'Yönetici girişi' })).toBeTruthy()
    unmount()
    localStorage.setItem('eco-admin-session', JSON.stringify({ token: 'gecerli', user: 'admin', expiresAt: inHours(2) }))
    render(<Harness />)
    expect(screen.getByText('Yönetici modu')).toBeTruthy()
  })

  it('sunucuda ADMIN_PASSWORD yoksa giriş düğmesi devre dışı', async () => {
    vi.mocked(api.adminStatus).mockResolvedValue({ enabled: false })
    render(<Harness />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Yönetici girişi' }).disabled).toBe(true))
  })
})
