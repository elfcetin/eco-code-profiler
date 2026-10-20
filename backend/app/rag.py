"""LLM istemine eklenecek Yeşil Kod Desenlerini getirir.

Şimdilik kural tabanlı: analyzer'ın tespit ettiği desen kodlarıyla birebir
eşleşen kayıtlar veritabanından çekilir.

TODO: İleride embedding tabanlı benzerlik araması eklenebilir (ör. pgvector
ile desen açıklamalarının vektörleri saklanıp kullanıcı koduna en yakın
desenlerin bulunması). Bu durumda `retrieve` imzası korunup kural tabanlı
sonuçlar embedding sonuçlarıyla birleştirilebilir.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import GreenPattern, SessionLocal


def retrieve(pattern_codes: Iterable[str], session: Session | None = None) -> list[dict[str, str]]:
    """Verilen desen kodlarının kayıtlarını, ilk görülme sırasıyla ve tekrarsız döndürür.

    Veritabanında olmayan kodlar sessizce atlanır.
    """
    codes = list(dict.fromkeys(pattern_codes))
    if not codes:
        return []

    def _query(s: Session) -> list[dict[str, str]]:
        rows = s.scalars(select(GreenPattern).where(GreenPattern.code.in_(codes))).all()
        by_code = {row.code: row.to_dict() for row in rows}
        return [by_code[c] for c in codes if c in by_code]

    if session is not None:
        return _query(session)
    with SessionLocal() as s:
        return _query(s)
