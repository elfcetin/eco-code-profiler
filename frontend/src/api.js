let authToken = null

/** Yönetici token'ı; düzenleme isteklerine Authorization başlığı olarak eklenir. */
export function setAuthToken(token) {
  authToken = token
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let resp
  try {
    resp = await fetch(path, { headers, ...options })
  } catch {
    throw new Error('Sunucuya ulaşılamadı. Backend çalışıyor mu? (uvicorn, port 8000)')
  }
  let body = null
  try {
    body = await resp.json()
  } catch {
    body = null
  }
  if (!resp.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail || `HTTP ${resp.status}`
    const error = new Error(`İstek başarısız: ${message}`)
    error.status = resp.status
    throw error
  }
  return body
}

const send = (method) => (path, data) => request(path, { method, body: JSON.stringify(data) })
const post = send('POST')
const put = send('PUT')
const patch = send('PATCH')

export const api = {
  health: () => request('/api/health'),
  patterns: () => request('/api/patterns'),
  updatePattern: (code, data) => put(`/api/patterns/${encodeURIComponent(code)}`, data),
  setPatternActive: (code, isActive) => patch(`/api/patterns/${encodeURIComponent(code)}/active`, { is_active: isActive }),
  history: () => request('/api/history'),
  adminStatus: () => request('/api/admin/status'),
  adminLogin: (password) => post('/api/admin/login', { password }),
  adminLogout: () => request('/api/admin/logout', { method: 'POST' }),
  report: () => request('/api/report'),
  energyEstimate: (data) => post('/api/energy/estimate', data),
  analyze: (code) => post('/api/analyze', { code }),
  optimize: (code) => post('/api/optimize', { code }),
}
