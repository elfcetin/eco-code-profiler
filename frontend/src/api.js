async function request(path, options = {}) {
  let resp
  try {
    resp = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
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
    throw new Error(`İstek başarısız: ${message}`)
  }
  return body
}

const post = (path, data) => request(path, { method: 'POST', body: JSON.stringify(data) })

export const api = {
  health: () => request('/api/health'),
  patterns: () => request('/api/patterns'),
  history: () => request('/api/history'),
  analyze: (code) => post('/api/analyze', { code }),
  optimize: (code) => post('/api/optimize', { code }),
}
