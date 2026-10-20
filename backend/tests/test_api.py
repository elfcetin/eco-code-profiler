"""Uçtan uca API testleri: gerçek analyzer + gerçek verifier (alt süreç), LLM mock'lu."""

import pytest
from fastapi.testclient import TestClient

from app import db, llm
from app.main import app

FIND_DUPLICATES = """\
def find_duplicates(items):
    duplicates = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j] and items[i] not in duplicates:
                duplicates.append(items[i])
    return duplicates
"""

# Çıktı sırasını koruyan (ilk görülme sırası) doğru optimizasyon.
GREEN_DUPLICATES = """\
def find_duplicates(items):
    counts = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    seen = set()
    duplicates = []
    for x in items:
        if counts[x] > 1 and x not in seen:
            seen.add(x)
            duplicates.append(x)
    return duplicates
"""

# Hatalı: sırayı bozuyor (sorted).
BROKEN_DUPLICATES = """\
def find_duplicates(items):
    counts = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return sorted(x for x, c in counts.items() if c > 1)
"""

CLEAN_CODE = "def total(values):\n    return sum(values)\n"


def llm_result(green_code: str) -> dict:
    return {
        "green_code": green_code,
        "changes": [{"pattern": "YK-01", "explanation": "Sayım sözlüğü ile tek geçiş."},
                    {"pattern": "YK-02", "explanation": "Üyelik kontrolü set ile."}],
        "test_inputs": {"find_duplicates": [[[]], [[1]], [[3, 1, 3, 2, 1]], [[5, 5, 5]], [["b", "a", "b", "a"]]]},
        "benchmark_input": {"find_duplicates": "[[random.randint(0, 500) for _ in range(1500)]]"},
        "notes": "",
        "warnings": [],
        "provider": "ollama",
        "model": "mock",
    }


class FakeLLM:
    """llm.optimize yerine geçer; sıradaki yanıtları döndürür ve çağrıları kaydeder."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, code, findings, patterns, feedback=None, **kwargs):
        self.calls.append({"code": code, "findings": findings, "patterns": patterns, "feedback": feedback})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def client(monkeypatch):
    db.configure_engine("sqlite://")
    monkeypatch.setattr(llm, "health_check", lambda: {
        "provider": "ollama", "model": "mock", "reachable": True, "message": "mock"
    })
    with TestClient(app) as c:
        yield c


def use_llm(monkeypatch, *responses) -> FakeLLM:
    fake = FakeLLM(*responses)
    monkeypatch.setattr(llm, "optimize", fake)
    return fake


# --------------------------------------------------------------------------- #

def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["llm"]["provider"] == "ollama"


def test_patterns(client):
    body = client.get("/api/patterns").json()
    assert [p["code"] for p in body][:2] == ["YK-01", "YK-02"]
    assert len(body) == 10


def test_analyze_endpoint(client):
    body = client.post("/api/analyze", json={"code": FIND_DUPLICATES}).json()
    assert {"YK-01", "YK-02"} <= {f["pattern_code"] for f in body["findings"]}


def test_cors_allows_vite_dev_server(client):
    resp = client.options(
        "/api/analyze",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_clean_code_does_not_call_llm(client, monkeypatch):
    fake = use_llm(monkeypatch)  # yanıt yok: çağrılırsa IndexError
    body = client.post("/api/optimize", json={"code": CLEAN_CODE}).json()

    assert body["status"] == "clean"
    assert body["message"] == "Algoritmik enerji israfı tespit edilmedi"
    assert body["green_code"] is None
    assert fake.calls == []


def test_find_duplicates_is_optimized_and_verified(client, monkeypatch):
    fake = use_llm(monkeypatch, llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "optimized", body
    assert body["attempts"] == 1
    assert body["verification"]["passed"] is True
    assert len([c for c in body["verification"]["cases"] if "derived" not in c]) == 5
    assert body["verification"]["benchmark"]["speedup"] > 1
    assert body["green_code"] == GREEN_DUPLICATES
    assert [c["pattern"] for c in body["changes"]] == ["YK-01", "YK-02"]

    before = {f["pattern_code"] for f in body["analysis"]["findings"]}
    after = {f["pattern_code"] for f in body["analysis_after"]["findings"]}
    assert {"YK-01", "YK-02"} <= before
    assert not after & {"YK-01", "YK-02"}

    # LLM'e yalnızca tespit edilen desenler verildi.
    assert {p["code"] for p in fake.calls[0]["patterns"]} == before


def test_failed_verification_retries_once_with_feedback(client, monkeypatch):
    fake = use_llm(monkeypatch, llm_result(BROKEN_DUPLICATES), llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "optimized"
    assert body["attempts"] == 2
    assert fake.calls[0]["feedback"] is None
    assert "GEÇEMEDİ" in fake.calls[1]["feedback"]


def test_two_failed_attempts_give_failed(client, monkeypatch):
    fake = use_llm(monkeypatch, llm_result(BROKEN_DUPLICATES), llm_result(BROKEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "failed"
    assert body["attempts"] == 2 and len(fake.calls) == 2
    assert body["verification"]["passed"] is False


def test_llm_unavailable_gives_failed_without_retry(client, monkeypatch):
    fake = use_llm(monkeypatch, llm.LLMUnavailableError("Yerel LLM servisine (Ollama) ulaşılamadı"))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "failed"
    assert "ulaşılamadı" in body["error"]
    assert len(fake.calls) == 1


def test_invalid_llm_response_is_retried(client, monkeypatch):
    fake = use_llm(monkeypatch, llm.LLMResponseError("LLM geçerli bir JSON döndürmedi."), llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "optimized"
    assert "JSON" in fake.calls[1]["feedback"]


def test_syntax_error_is_failed_without_llm(client, monkeypatch):
    fake = use_llm(monkeypatch)
    body = client.post("/api/optimize", json={"code": "def f(:\n"}).json()
    assert body["status"] == "failed" and "Satır 1" in body["error"]
    assert fake.calls == []


def test_history_records_runs_newest_first(client, monkeypatch):
    use_llm(monkeypatch, llm_result(GREEN_DUPLICATES))
    client.post("/api/optimize", json={"code": CLEAN_CODE})
    client.post("/api/optimize", json={"code": FIND_DUPLICATES})

    items = client.get("/api/history").json()
    assert [i["status"] for i in items[:2]] == ["optimized", "clean"]
    assert items[0]["speedup"] > 1 and items[0]["green_code"] == GREEN_DUPLICATES
    assert items[1]["green_code"] is None


def test_history_is_limited_to_20(client, monkeypatch):
    for _ in range(22):
        client.post("/api/optimize", json={"code": CLEAN_CODE})
    assert len(client.get("/api/history").json()) == 20


def test_empty_code_is_rejected(client):
    assert client.post("/api/optimize", json={"code": ""}).status_code == 422


def test_order_only_difference_gets_specific_feedback(client, monkeypatch):
    set_order = (
        "def find_duplicates(items):\n"
        "    seen, dups = set(), set()\n"
        "    for x in items:\n"
        "        (dups if x in seen else seen).add(x)\n"
        "    return list(dups)\n"
    )
    fake = use_llm(monkeypatch, llm_result(set_order), llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    assert body["status"] == "optimized" and body["attempts"] == 2
    assert "SIRASI farklı" in fake.calls[1]["feedback"]


def test_wrong_values_do_not_get_order_hint(client, monkeypatch):
    always_empty = "def find_duplicates(items):\n    return []\n"
    fake = use_llm(monkeypatch, llm_result(always_empty), llm_result(GREEN_DUPLICATES))
    client.post("/api/optimize", json={"code": FIND_DUPLICATES})
    assert "SIRASI farklı" not in fake.calls[1]["feedback"]
