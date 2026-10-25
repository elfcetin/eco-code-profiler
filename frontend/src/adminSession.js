import { useCallback, useEffect, useState } from 'react'
import { api, setAuthToken } from './api.js'

const KEY = 'eco-admin-session'

/** Yalnızca bu tarayıcıdaki kolaylık: sayfa yenilenince oturum korunur. Erişilemezse oturum bellekte kalır. */
function load() {
  try {
    const session = JSON.parse(localStorage.getItem(KEY) || 'null')
    return session && Date.parse(session.expiresAt) > Date.now() ? session : null
  } catch {
    return null
  }
}

function store(session) {
  try {
    if (session) localStorage.setItem(KEY, JSON.stringify(session))
    else localStorage.removeItem(KEY)
  } catch {
    /* depolama kapalıysa yok say */
  }
}

/** Yönetici oturumu: giriş/çıkış, token'ın API'ye verilmesi ve süre dolunca otomatik çıkış. */
export function useAdminSession() {
  const [session, setSession] = useState(load)
  const [enabled, setEnabled] = useState(true)

  useEffect(() => {
    api.adminStatus().then((s) => setEnabled(s.enabled)).catch(() => {})
  }, [])

  useEffect(() => {
    setAuthToken(session?.token ?? null)
    store(session)
    if (!session) return
    const ms = Date.parse(session.expiresAt) - Date.now()
    const id = setTimeout(() => setSession(null), Math.max(ms, 0)) // süre dolunca otomatik çıkış
    return () => clearTimeout(id)
  }, [session])

  const login = useCallback(async (password) => {
    const body = await api.adminLogin(password)
    setSession({ token: body.token, user: body.user, expiresAt: body.expires_at })
  }, [])

  const logout = useCallback(() => {
    api.adminLogout().catch(() => {})
    setSession(null)
  }, [])

  // Sunucu token'ı reddettiyse (ör. backend yeniden başladı) sunucuya sormadan yerel oturumu kapat.
  const expire = useCallback(() => setSession(null), [])

  return { session, isAdmin: Boolean(session), enabled, login, logout, expire }
}
