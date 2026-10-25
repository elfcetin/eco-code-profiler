import { useState } from 'react'
import { formatDate } from '../format.js'

/** Üst bar: "Yönetici girişi" düğmesi / "Yönetici modu" rozeti ve "Çıkış". */
export default function AdminControls({ admin }) {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (admin.isAdmin) {
    return (
      <div className="admin-controls">
        <span className="badge admin-badge" title={`Oturum bitişi: ${formatDate(admin.session.expiresAt)}`}>
          Yönetici modu
        </span>
        <button type="button" className="btn btn-secondary btn-small" onClick={admin.logout}>
          Çıkış
        </button>
      </div>
    )
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await admin.login(password)
      setPassword('')
      setOpen(false)
    } catch (err) {
      setError(err.status === 401 ? 'Şifre yanlış.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="admin-controls">
      <button
        type="button"
        className="btn btn-secondary btn-small"
        onClick={() => setOpen((v) => !v)}
        disabled={!admin.enabled}
        title={admin.enabled ? undefined : 'Sunucuda ADMIN_PASSWORD tanımlı değil; düzenleme kapalı.'}
        aria-expanded={open}
      >
        Yönetici girişi
      </button>
      {open && (
        <form className="card admin-login" onSubmit={submit}>
          <label htmlFor="admin-password">Yönetici şifresi</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="error-text">{error}</p>}
          <div className="actions">
            <button type="submit" className="btn btn-primary btn-small" disabled={busy || !password}>
              Giriş
            </button>
            <button type="button" className="btn btn-secondary btn-small" onClick={() => setOpen(false)}>
              İptal
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
