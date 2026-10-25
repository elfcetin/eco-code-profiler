"""Yönetici yetkilendirmesi: giriş, token, süre dolumu, kapalı mod, updated_by."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app import auth, config, db
from app.main import app
from app.patterns import PATTERNS_BY_CODE

PASSWORD = "dogru-sifre-123"
FIELDS = ("anti_pattern", "solution", "impact", "example_before", "example_after")


@pytest.fixture
def client(monkeypatch):
    db.configure_engine("sqlite://")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setattr(config, "ADMIN_TOKEN_HOURS", 8.0)
    auth._tokens.clear()
    with TestClient(app) as c:
        yield c
    auth._tokens.clear()


def login(client, password=PASSWORD):
    return client.post("/api/admin/login", json={"password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def edit_payload(code="YK-04", **overrides):
    return {**{k: PATTERNS_BY_CODE[code][k] for k in FIELDS}, **overrides}


# --------------------------------------------------------------------------- #
# Giriş
# --------------------------------------------------------------------------- #

def test_login_with_correct_password_returns_expiring_token(client):
    resp = login(client)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["token"]) >= 32 and body["user"] == "admin"
    hours = (datetime.fromisoformat(body["expires_at"]).timestamp() - auth._now()) / 3600
    assert 7.9 < hours <= 8.0


@pytest.mark.parametrize("password", ["yanlis", "", PASSWORD + " ", PASSWORD.upper()])
def test_login_with_wrong_password_is_401(client, password):
    resp = login(client, password)
    assert resp.status_code == 401 and resp.json()["detail"] == "Şifre yanlış."


def test_admin_status(client, monkeypatch):
    assert client.get("/api/admin/status").json() == {"enabled": True}
    monkeypatch.setattr(config, "ADMIN_PASSWORD", None)
    assert client.get("/api/admin/status").json() == {"enabled": False}


# --------------------------------------------------------------------------- #
# Düzenleme uçları
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("headers", [{}, bearer("uydurma-token"), {"Authorization": "Basic abc"}, bearer("")])
def test_edit_without_valid_token_is_401(client, headers):
    put = client.put("/api/patterns/YK-04", json=edit_payload(solution="Yetkisiz."), headers=headers)
    patch = client.patch("/api/patterns/YK-04/active", json={"is_active": False}, headers=headers)
    assert put.status_code == 401 and patch.status_code == 401
    pattern = next(p for p in client.get("/api/patterns").json() if p["code"] == "YK-04")
    assert pattern["solution"] == PATTERNS_BY_CODE["YK-04"]["solution"] and pattern["is_active"] is True


def test_edit_with_valid_token_records_updated_by(client):
    token = login(client).json()["token"]
    put = client.put("/api/patterns/YK-04", json=edit_payload(solution="Kurum çözümü."), headers=bearer(token))
    assert put.status_code == 200, put.json()
    assert put.json()["solution"] == "Kurum çözümü." and put.json()["updated_by"] == "admin"

    patch = client.patch("/api/patterns/YK-02/active", json={"is_active": False}, headers=bearer(token))
    assert patch.status_code == 200 and patch.json()["updated_by"] == "admin"


def test_read_endpoints_stay_public(client):
    assert client.get("/api/patterns").status_code == 200
    assert client.get("/api/report").status_code == 200
    assert client.get("/api/history").status_code == 200
    assert client.post("/api/analyze", json={"code": "x = 1\n"}).status_code == 200
    assert client.get("/api/patterns").json()[0]["updated_by"] is None  # başlangıç verisi


def test_expired_token_is_401(client, monkeypatch):
    token = login(client).json()["token"]
    now = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: now + 8 * 3600 + 1)  # 8 saat + 1 sn sonra
    resp = client.patch("/api/patterns/YK-02/active", json={"is_active": False}, headers=bearer(token))
    assert resp.status_code == 401 and "süresi doldu" in resp.json()["detail"]
    assert token not in auth._tokens  # süresi dolan token silinir


def test_token_valid_just_before_expiry(client, monkeypatch):
    token = login(client).json()["token"]
    now = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: now + 8 * 3600 - 5)
    resp = client.patch("/api/patterns/YK-02/active", json={"is_active": False}, headers=bearer(token))
    assert resp.status_code == 200


def test_logout_invalidates_token(client):
    token = login(client).json()["token"]
    assert client.post("/api/admin/logout", headers=bearer(token)).status_code == 204
    resp = client.patch("/api/patterns/YK-02/active", json={"is_active": False}, headers=bearer(token))
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# ADMIN_PASSWORD tanımlı değil: kapalı mod
# --------------------------------------------------------------------------- #

def test_without_admin_password_login_and_edits_are_closed(client, monkeypatch):
    token = login(client).json()["token"]  # şifre varken alınmış token bile işe yaramamalı
    monkeypatch.setattr(config, "ADMIN_PASSWORD", None)
    assert login(client, "").status_code == 403
    resp = client.patch("/api/patterns/YK-02/active", json={"is_active": False}, headers=bearer(token))
    assert resp.status_code == 403 and "ADMIN_PASSWORD" in resp.json()["detail"]
    assert client.get("/api/patterns").status_code == 200


def test_startup_warns_when_admin_password_missing(monkeypatch, caplog):
    db.configure_engine("sqlite://")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", None)
    with caplog.at_level("WARNING", logger="uvicorn.error"), TestClient(app):
        pass
    assert any("ADMIN_PASSWORD tanımlı değil" in r.message for r in caplog.records)


def test_no_hardcoded_password_in_config():
    source = (config.__file__ and open(config.__file__, encoding="utf-8").read())
    assert 'os.getenv("ADMIN_PASSWORD")' in source
    assert 'getenv("ADMIN_PASSWORD", "' not in source  # varsayılan şifre yok


# --------------------------------------------------------------------------- #
# Eski veritabanı: updated_by sütunu eklenir
# --------------------------------------------------------------------------- #

def test_updated_by_column_is_added_to_old_database():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE green_patterns (code VARCHAR(16) PRIMARY KEY, title VARCHAR(200), anti_pattern TEXT, "
            "solution TEXT, impact VARCHAR(16), example_before TEXT, example_after TEXT)"
        ))
    db.init_db(eng)
    assert "updated_by" in {c["name"] for c in inspect(eng).get_columns("green_patterns")}
    eng.dispose()
