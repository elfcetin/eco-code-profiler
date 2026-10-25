"""Basit yönetici yetkilendirmesi (tam bir kullanıcı sistemi değil).

- Şifre `ADMIN_PASSWORD` ortam değişkeninden okunur; tanımlı değilse giriş ve düzenleme kapalıdır.
- Doğru şifreyle süreli (`ADMIN_TOKEN_HOURS`, varsayılan 8 saat) rastgele bir token verilir. Tokenlar
  sunucu belleğinde tutulur: backend yeniden başlatılınca geçersiz olur (yeniden giriş gerekir) ve
  birden çok worker süreciyle paylaşılmaz.
- Düzenleme uçları `Authorization: Bearer <token>` başlığı ister; yoksa / geçersizse / süresi
  dolduysa 401.
"""

from __future__ import annotations

import hmac
import secrets
import time
from datetime import datetime, timezone

from fastapi import Header, HTTPException

from . import config

ADMIN_USER = "admin"
DISABLED_MESSAGE = "Yönetici girişi kapalı: sunucuda ADMIN_PASSWORD tanımlı değil."

_tokens: dict[str, float] = {}  # token -> son geçerlilik (epoch saniye)


def _now() -> float:
    return time.time()  # testlerde değiştirilebilsin


def enabled() -> bool:
    return bool(config.ADMIN_PASSWORD)


def login(password: str) -> dict:
    if not enabled():
        raise HTTPException(status_code=403, detail=DISABLED_MESSAGE)
    # Zamanlama saldırısına karşı sabit süreli karşılaştırma.
    if not hmac.compare_digest(password.encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Şifre yanlış.")
    now = _now()
    for token, expires in list(_tokens.items()):  # süresi dolanları temizle
        if expires <= now:
            del _tokens[token]
    token = secrets.token_urlsafe(32)
    expires = now + config.ADMIN_TOKEN_HOURS * 3600
    _tokens[token] = expires
    return {
        "token": token,
        "user": ADMIN_USER,
        "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
    }


def logout(token: str | None) -> None:
    if token:
        _tokens.pop(token, None)


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """FastAPI bağımlılığı: geçerli yönetici token'ı yoksa 401 (kapalıysa 403)."""
    if not enabled():
        raise HTTPException(status_code=403, detail=DISABLED_MESSAGE)
    token = bearer_token(authorization)
    expires = _tokens.get(token) if token else None
    if expires is None:
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.",
                            headers={"WWW-Authenticate": "Bearer"})
    if expires <= _now():
        _tokens.pop(token, None)
        raise HTTPException(status_code=401, detail="Yönetici oturumunun süresi doldu; yeniden giriş yapın.",
                            headers={"WWW-Authenticate": "Bearer"})
    return ADMIN_USER
