"""Veritabanı modelleri ve oturum yönetimi (SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Engine, Float, Integer, String, Text, TypeDecorator, create_engine, inspect, select,
    text, true, update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config
from .patterns import EXAMPLE_INPUTS, GREEN_PATTERNS

# PostgreSQL'de JSONB, diğerlerinde (SQLite) genel JSON tipi.
JSONType = JSON().with_variant(JSONB(), "postgresql")
# None -> SQL NULL (JSON 'null' değil); "girdi tanımlı değil" sorgulanabilsin.
NullableJSON = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    """ISO 8601, saat dilimiyle (ör. 2026-10-24T17:19:23+00:00)."""
    return value.isoformat() if value else None


class UTCDateTime(TypeDecorator):
    """Zamanı UTC olarak saklar ve HER ZAMAN saat dilimli (UTC) datetime olarak döndürür.

    SQLite saat dilimini saklamaz: değer UTC'ye çevrilip etiketsiz yazılır, okunurken UTC
    etiketi geri eklenir. Uygulama zamanları baştan beri UTC ürettiğinden (`_utcnow`) eski
    kayıtlar da doğru yorumlanır. PostgreSQL'de `timestamptz` zaten saat dilimlidir.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # etiketsiz değerler UTC kabul edilir
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class GreenPattern(Base):
    __tablename__ = "green_patterns"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    anti_pattern: Mapped[str] = mapped_column(Text)
    solution: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(String(16))
    example_before: Mapped[str] = mapped_column(Text)
    example_after: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Örneklerin eşdeğerlik kontrolü için test girdileri: {fonksiyon: [[argümanlar], ...]}
    example_inputs: Mapped[dict | None] = mapped_column(NullableJSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self) -> dict[str, str]:
        """Desenin içeriği (RAG ile LLM'e gönderilen alanlar)."""
        return {
            "code": self.code,
            "title": self.title,
            "anti_pattern": self.anti_pattern,
            "solution": self.solution,
            "impact": self.impact,
            "example_before": self.example_before,
            "example_after": self.example_after,
        }

    def to_api_dict(self) -> dict:
        """İçerik + yönetim alanları (desen yönetim ekranı için)."""
        return {
            **self.to_dict(),
            "is_active": self.is_active,
            "updated_at": iso_utc(self.updated_at),
            "example_inputs": self.example_inputs,
        }


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
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


def seed_patterns(session: Session) -> int:
    """patterns.py'deki başlangıç desenlerinden tabloda OLMAYANLARI ekler.

    Asıl kaynak veritabanıdır: mevcut kayıtların (arayüzden yapılan düzenlemeler ve
    aktif/pasif durumu dahil) üzerine yazılmaz. Eklenen kayıt sayısını döndürür.
    """
    existing = set(session.scalars(select(GreenPattern.code)))
    missing = [data for data in GREEN_PATTERNS if data["code"] not in existing]
    session.add_all(GreenPattern(**data, example_inputs=EXAMPLE_INPUTS.get(data["code"])) for data in missing)
    # Test girdisi olmayan mevcut kayıtlara (eski sürümden gelen) varsayılan girdiler; tanımlı
    # girdilere dokunulmaz ve updated_at değişmez.
    for code, inputs in EXAMPLE_INPUTS.items():
        session.execute(
            update(GreenPattern)
            .where(GreenPattern.code == code, GreenPattern.example_inputs.is_(None))
            .values(example_inputs=inputs, updated_at=GreenPattern.updated_at)
        )
    session.commit()
    return len(missing)


def _add_missing_columns(bind: Engine) -> None:
    """Eski sürümde oluşturulmuş green_patterns tablosuna yeni sütunları ekler (veri korunur).

    create_all mevcut tabloları değiştirmediği için gerekli. Yeni sütunlar NULL olabilir
    veya varsayılan değerlidir; mevcut satırlar aktif kalır.
    """
    columns = {c["name"] for c in inspect(bind).get_columns(GreenPattern.__tablename__)}
    table = GreenPattern.__table__
    statements = []
    if "is_active" not in columns:
        true = "1" if bind.dialect.name == "sqlite" else "TRUE"
        statements.append(f"ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT {true}")
    if "updated_at" not in columns:
        statements.append(f"ADD COLUMN updated_at {table.c.updated_at.type.compile(dialect=bind.dialect)}")
    if "example_inputs" not in columns:
        statements.append(f"ADD COLUMN example_inputs {table.c.example_inputs.type.compile(dialect=bind.dialect)}")
    if statements:
        with bind.begin() as conn:
            for stmt in statements:  # SQLite tek ALTER'da tek sütun kabul eder
                conn.execute(text(f"ALTER TABLE {table.name} {stmt}"))


def init_db(bind: Engine | None = None) -> None:
    """Eksik tabloları/sütunları oluşturur ve eksik başlangıç desenlerini ekler."""
    bind = bind or engine
    Base.metadata.create_all(bind)
    _add_missing_columns(bind)
    with Session(bind) as session:
        seed_patterns(session)


def load_catalog(session: Session) -> dict[str, dict]:
    """Analizci için desen kataloğu: kod -> {title, impact, is_active}."""
    return {
        row.code: {"title": row.title, "impact": row.impact, "is_active": row.is_active}
        for row in session.scalars(select(GreenPattern))
    }


def get_session() -> Iterator[Session]:
    """FastAPI bağımlılığı olarak kullanılacak oturum üreteci."""
    with SessionLocal() as session:
        yield session
