"""Veritabanı modelleri ve oturum yönetimi (SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Engine, Float, Integer, String, Text, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config
from .patterns import GREEN_PATTERNS

# PostgreSQL'de JSONB, diğerlerinde (SQLite) genel JSON tipi.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class GreenPattern(Base):
    __tablename__ = "green_patterns"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    anti_pattern: Mapped[str] = mapped_column(Text)
    solution: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(String(16))
    example_before: Mapped[str] = mapped_column(Text)
    example_after: Mapped[str] = mapped_column(Text)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "anti_pattern": self.anti_pattern,
            "solution": self.solution,
            "impact": self.impact,
            "example_before": self.example_before,
            "example_after": self.example_after,
        }


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    original_code: Mapped[str] = mapped_column(Text)
    green_code: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    old_seconds: Mapped[float | None] = mapped_column(Float)
    new_seconds: Mapped[float | None] = mapped_column(Float)
    speedup: Mapped[float | None] = mapped_column(Float)


def make_engine(url: str = config.DATABASE_URL) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool  # bellek içi DB tüm bağlantılarda aynı kalsın
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def configure_engine(url: str) -> Engine:
    """Motoru başka bir veritabanına yönlendirir (testler için)."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)
    return engine


def sync_patterns(session: Session) -> dict[str, int]:
    """green_patterns tablosunu patterns.py ile eşitler (tek kaynak patterns.py).

    Eksik desenler eklenir, içeriği değişmiş olanlar güncellenir; böylece katalogdaki
    düzeltmeler mevcut kurulumlara da ulaşır. patterns.py'de olmayan kayıtlara dokunulmaz.
    """
    existing = {row.code: row for row in session.scalars(select(GreenPattern))}
    added = updated = 0
    for data in GREEN_PATTERNS:
        row = existing.get(data["code"])
        if row is None:
            session.add(GreenPattern(**data))
            added += 1
        elif row.to_dict() != data:
            for key, value in data.items():
                setattr(row, key, value)
            updated += 1
    session.commit()
    return {"added": added, "updated": updated}


def init_db(bind: Engine | None = None) -> None:
    """Eksik tabloları oluşturur ve desen tablosunu patterns.py ile eşitler."""
    bind = bind or engine
    Base.metadata.create_all(bind)
    with Session(bind) as session:
        sync_patterns(session)


def get_session() -> Iterator[Session]:
    """FastAPI bağımlılığı olarak kullanılacak oturum üreteci."""
    with SessionLocal() as session:
        yield session
