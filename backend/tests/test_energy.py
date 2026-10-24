"""Tahmini enerji hesabı (energy.estimate) birim testleri."""

import pytest
from fastapi.testclient import TestClient

from app import config, db, energy
from app.main import app


def test_formula_with_explicit_assumptions():
    result = energy.estimate(0.5, 0.1, watts=65, runs_per_day=10_000)
    assert result["joules_per_run"] == pytest.approx(0.4 * 65)  # 26 J
    assert result["kwh_per_year"] == pytest.approx(26 * 10_000 * 365 / 3_600_000)  # ≈ 26,36 kWh
    assert (result["watts"], result["runs_per_day"]) == (65, 10_000)


def test_one_second_at_3600_watts_once_a_day_is_365_kwh():
    # 1 s × 3600 W = 3600 J = 1 Wh = 0,001 kWh; günde 1000 kez × 365 gün = 365 kWh.
    assert energy.estimate(2.0, 1.0, watts=3600, runs_per_day=1000)["kwh_per_year"] == pytest.approx(365)


def test_defaults_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "CPU_POWER_WATTS", 100.0)
    monkeypatch.setattr(config, "RUNS_PER_DAY", 24.0)
    result = energy.estimate(1.0, 0.5)
    assert (result["watts"], result["runs_per_day"]) == (100.0, 24.0)
    assert result["joules_per_run"] == pytest.approx(50)


def test_default_assumptions_are_65w_and_10000_runs():
    assert (config.CPU_POWER_WATTS, config.RUNS_PER_DAY) == (65.0, 10_000.0)


def test_scales_linearly_with_assumptions():
    base = energy.estimate(0.3, 0.1, watts=65, runs_per_day=10_000)["kwh_per_year"]
    assert energy.estimate(0.3, 0.1, watts=130, runs_per_day=10_000)["kwh_per_year"] == pytest.approx(2 * base)
    assert energy.estimate(0.3, 0.1, watts=65, runs_per_day=1_000)["kwh_per_year"] == pytest.approx(base / 10)


@pytest.mark.parametrize("old, new", [
    (0.1, 0.2),    # yeni kod daha yavaş
    (0.1, 0.1),    # fark yok
    (None, 0.1),   # süre ölçülmedi
    (0.1, None),
    (None, None),
])
def test_no_estimate_when_not_faster_or_not_measured(old, new):
    assert energy.estimate(old, new, watts=65, runs_per_day=10_000) is None


@pytest.mark.parametrize("watts, runs", [(0, 10), (-5, 10), (65, 0), (65, -1)])
def test_invalid_assumptions_raise(watts, runs):
    with pytest.raises(ValueError):
        energy.estimate(0.5, 0.1, watts=watts, runs_per_day=runs)


# --------------------------------------------------------------------------- #
# /api/energy/estimate
# --------------------------------------------------------------------------- #

@pytest.fixture
def client():
    db.configure_engine("sqlite://")
    with TestClient(app) as c:
        yield c


def test_endpoint_uses_same_function(client):
    body = client.post("/api/energy/estimate", json={
        "old_seconds": 0.5, "new_seconds": 0.1, "watts": 30, "runs_per_day": 500,
    }).json()
    assert body["estimate"] == energy.estimate(0.5, 0.1, watts=30, runs_per_day=500)


def test_endpoint_returns_null_when_slower(client):
    body = client.post("/api/energy/estimate", json={
        "old_seconds": 0.1, "new_seconds": 0.5, "watts": 65, "runs_per_day": 10_000,
    }).json()
    assert body == {"estimate": None}


@pytest.mark.parametrize("field, value", [("watts", 0), ("runs_per_day", -3)])
def test_endpoint_rejects_non_positive_assumptions(client, field, value):
    payload = {"old_seconds": 0.5, "new_seconds": 0.1, "watts": 65, "runs_per_day": 10_000, field: value}
    assert client.post("/api/energy/estimate", json=payload).status_code == 422
