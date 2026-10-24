"""Zaman damgaları UTC saklanır ve API'den saat dilimiyle (ISO 8601) döner."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import db
from app.db import AnalysisRun
from app.main import app

TR = timezone(timedelta(hours=3))
ZONED = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def client():
    db.configure_engine("sqlite://")
    with TestClient(app) as c:
        yield c


def insert_legacy_run(created_at: str) -> None:
    """Eski sürümün yazdığı biçim: SQLite'ta saat dilimi olmadan, UTC değeriyle metin."""
    with db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO analysis_runs (created_at, original_code, green_code, findings, status) "
            "VALUES (:created_at, 'x = 1', NULL, '[]', 'clean')"
        ), {"created_at": created_at})


def test_legacy_rows_are_read_as_utc(client):
    insert_legacy_run("2026-10-24 17:19:23.023839")
    with Session(db.engine) as s:
        run = s.query(AnalysisRun).one()
    assert run.created_at == datetime(2026, 10, 24, 17, 19, 23, 23839, tzinfo=timezone.utc)


def test_history_returns_zoned_timestamps_for_old_and_new_runs(client):
    insert_legacy_run("2026-10-24 17:19:23.023839")
    before = datetime.now(timezone.utc)
    client.post("/api/optimize", json={"code": "def total(values):\n    return sum(values)\n"})
    after = datetime.now(timezone.utc)

    new, old = client.get("/api/history").json()[:2]
    assert ZONED.search(old["created_at"]) and ZONED.search(new["created_at"])
    # Eski kayıt: 17:19 UTC = Türkiye saatiyle 20:19.
    assert parse(old["created_at"]).astimezone(TR).strftime("%H:%M") == "20:19"
    # Yeni kayıt: şu anki an (yerel saat değil, UTC olarak doğru an).
    assert before - timedelta(seconds=1) <= parse(new["created_at"]) <= after + timedelta(seconds=1)


def test_non_utc_input_is_stored_as_same_instant(client):
    with Session(db.engine) as s:
        run = AnalysisRun(original_code="x = 1", status="clean",
                          created_at=datetime(2026, 10, 24, 20, 0, tzinfo=TR))
        s.add(run)
        s.commit()
        run_id = run.id
    with db.engine.connect() as conn:
        raw = conn.execute(text("SELECT created_at FROM analysis_runs WHERE id = :id"), {"id": run_id}).scalar()
    assert raw.startswith("2026-10-24 17:00:00")  # UTC olarak saklandı
    item = client.get("/api/history").json()[0]
    assert parse(item["created_at"]) == datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)


def test_report_and_patterns_return_zoned_timestamps(client):
    insert_legacy_run("2026-10-24 17:19:23")
    with db.engine.begin() as conn:  # eski kayıtta updated_at da etiketsiz
        conn.execute(text("UPDATE green_patterns SET updated_at = '2026-10-24 17:07:27' WHERE code = 'YK-01'"))
        conn.execute(text(
            "INSERT INTO analysis_runs (created_at, original_code, findings, status, old_seconds, new_seconds, speedup) "
            "VALUES ('2026-10-20 21:04:00', 'x = 1', '[]', 'optimized', 1.0, 0.5, 2.0)"
        ))

    top = client.get("/api/report").json()["top_runs"][0]
    assert parse(top["created_at"]) == datetime(2026, 10, 20, 21, 4, tzinfo=timezone.utc)

    patterns = {p["code"]: p for p in client.get("/api/patterns").json()}
    assert parse(patterns["YK-01"]["updated_at"]) == datetime(2026, 10, 24, 17, 7, 27, tzinfo=timezone.utc)
    assert all(ZONED.search(p["updated_at"]) for p in patterns.values() if p["updated_at"])
