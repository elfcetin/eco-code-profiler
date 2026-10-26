"""Uçtan uca API testleri: gerçek analyzer + gerçek verifier (alt süreç), LLM mock'lu."""

import pytest
from fastapi.testclient import TestClient

from app import config, db, llm, main
from app.patterns import EXAMPLE_INPUTS, PATTERNS_BY_CODE
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
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "test-sifresi")
    with TestClient(app) as c:
        # Bu dosyadaki testler yönetici olarak çalışır; yetkilendirme test_admin.py'de.
        token = c.post("/api/admin/login", json={"password": "test-sifresi"}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
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


def test_patterns_include_management_fields(client):
    first = client.get("/api/patterns").json()[0]
    assert first["is_active"] is True
    assert first["updated_at"]


def pattern_payload(**overrides) -> dict:
    payload = {
        "anti_pattern": "Kuruma özel açıklama.",
        "solution": "Kuruma özel çözüm.",
        "impact": "orta",
        "example_before": PATTERNS_BY_CODE["YK-01"]["example_before"],
        "example_after": PATTERNS_BY_CODE["YK-01"]["example_after"],
    }
    return {**payload, **overrides}


# YK-01 için eşdeğer olmayan eski örnek: set tekrarları kaybeder.
YK01_SET_AFTER = "def common(a, b):\n    b_set = set(b)\n    return [x for x in a if x in b_set]\n"
# Eşdeğer, farklı yazılmış bir örnek.
YK01_DICT_AFTER = (
    "def common(a, b):\n    counts = {}\n    for y in b:\n        counts[y] = counts.get(y, 0) + 1\n"
    "    out = []\n    for x in a:\n        out += [x] * counts.get(x, 0)\n    return out\n"
)
YK07_NO_CLEAR_AFTER = (
    "from collections import deque\n\ndef drain(tasks):\n    queue = deque(tasks)\n    done = []\n"
    "    while queue:\n        done.append(queue.popleft())\n    return done\n"
)


def yk07_payload(**overrides) -> dict:
    p = PATTERNS_BY_CODE["YK-07"]
    return {**pattern_payload(impact="yüksek", example_before=p["example_before"], example_after=p["example_after"]),
            **overrides}


def test_patterns_include_example_inputs(client):
    first = client.get("/api/patterns").json()[0]
    assert first["example_inputs"] == EXAMPLE_INPUTS["YK-01"]


def test_text_only_edit_does_not_run_equivalence_check(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("örnekler değişmedi; doğrulayıcı çalışmamalı")
    monkeypatch.setattr(main, "verify", boom)
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(solution="Yalnızca metin değişti."))
    assert resp.status_code == 200


def test_equivalent_example_edit_is_saved(client):
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(example_after=YK01_DICT_AFTER))
    assert resp.status_code == 200, resp.json()
    assert resp.json()["example_after"] == YK01_DICT_AFTER


def test_non_equivalent_example_is_rejected(client):
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(example_after=YK01_SET_AFTER))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail.startswith("'Sonra' örneği 'önce' örneğiyle eşdeğer değil")
    assert "common(*[[1, 1, 2], [1, 1, 5]]) için önce [1, 1, 1, 1], sonra [1, 1]" in detail
    saved = next(p for p in client.get("/api/patterns").json() if p["code"] == "YK-01")
    assert saved["example_after"] == PATTERNS_BY_CODE["YK-01"]["example_after"]  # kaydedilmedi


def test_side_effect_difference_in_example_is_rejected(client):
    resp = client.put("/api/patterns/YK-07", json=yk07_payload(example_after=YK07_NO_CLEAR_AFTER))
    assert resp.status_code == 400
    assert "Yan etki farkı" in resp.json()["detail"] and "`tasks`" in resp.json()["detail"]


def test_custom_example_inputs_are_validated_and_saved(client):
    before = "def double(xs):\n    out = []\n    for x in xs:\n        out.append(x * 2)\n    return out\n"
    after = "def double(xs):\n    return [x * 2 for x in xs]\n"
    inputs = {"double": [[[1, 2]], [[]], [[5]]]}
    resp = client.put("/api/patterns/YK-04", json=pattern_payload(
        impact="düşük", example_before=before, example_after=after, example_inputs=inputs))
    assert resp.status_code == 200, resp.json()
    assert resp.json()["example_inputs"] == inputs

    wrong = "def double(xs):\n    return [x * 3 for x in xs]\n"
    resp = client.put("/api/patterns/YK-04", json=pattern_payload(
        impact="düşük", example_before=before, example_after=wrong))  # kayıtlı girdiler kullanılır
    assert resp.status_code == 400 and "double(*[[1, 2]]) için önce [2, 4], sonra [3, 6]" in resp.json()["detail"]


@pytest.mark.parametrize("inputs, message", [
    ({"baska": [[[1]]]}, "'önce' örneğinde yok: baska"),
    ({"common": []}, "En az bir test girdisi gerekli"),
])
def test_invalid_example_inputs_are_rejected(client, inputs, message):
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(example_after=YK01_DICT_AFTER, example_inputs=inputs))
    assert resp.status_code == 400 and message in resp.json()["detail"]


def test_missing_inputs_are_required_when_examples_change(client):
    with db.SessionLocal() as s:
        s.get(db.GreenPattern, "YK-01").example_inputs = None
        s.commit()
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(example_after=YK01_DICT_AFTER))
    assert resp.status_code == 400 and "test girdileri gerekli" in resp.json()["detail"]


def test_update_pattern(client):
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(solution="  Kuruma özel çözüm.  "))
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["solution"] == "Kuruma özel çözüm."
    assert body["impact"] == "orta" and body["title"] == "İç içe döngü"

    saved = next(p for p in client.get("/api/patterns").json() if p["code"] == "YK-01")
    assert saved == body
    # Analiz yeni etki düzeyini kullanır.
    findings = client.post("/api/analyze", json={"code": FIND_DUPLICATES}).json()["findings"]
    assert next(f for f in findings if f["pattern_code"] == "YK-01")["impact"] == "orta"


@pytest.mark.parametrize("overrides, message", [
    ({"impact": "çok yüksek"}, "Geçersiz etki"),
    ({"solution": "   "}, "Çözüm boş"),
    ({"anti_pattern": ""}, "Sorun açıklaması boş"),
    ({"example_after": "def f(:\n"}, "geçerli Python değil"),
])
def test_update_pattern_rejects_invalid_input(client, overrides, message):
    resp = client.put("/api/patterns/YK-01", json=pattern_payload(**overrides))
    assert resp.status_code == 400
    assert message in resp.json()["detail"]
    original = next(p for p in client.get("/api/patterns").json() if p["code"] == "YK-01")
    assert original["impact"] == "yüksek"  # hiçbir şey kaydedilmedi


def test_update_unknown_pattern_is_404(client):
    assert client.put("/api/patterns/YK-99", json=pattern_payload()).status_code == 404
    assert client.patch("/api/patterns/YK-99/active", json={"is_active": False}).status_code == 404


def test_toggle_pattern_active(client):
    body = client.patch("/api/patterns/YK-02/active", json={"is_active": False}).json()
    assert body["is_active"] is False
    findings = client.post("/api/analyze", json={"code": FIND_DUPLICATES}).json()["findings"]
    assert "YK-02" not in {f["pattern_code"] for f in findings}

    client.patch("/api/patterns/YK-02/active", json={"is_active": True})
    findings = client.post("/api/analyze", json={"code": FIND_DUPLICATES}).json()["findings"]
    assert "YK-02" in {f["pattern_code"] for f in findings}


def test_inactive_patterns_are_not_sent_to_llm(client, monkeypatch):
    client.patch("/api/patterns/YK-02/active", json={"is_active": False})
    fake = use_llm(monkeypatch, llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()

    reported = {f["pattern_code"] for f in body["analysis"]["findings"]}
    assert "YK-02" not in reported and "YK-01" in reported
    assert {f["pattern_code"] for f in fake.calls[0]["findings"]} == reported
    assert {p["code"] for p in fake.calls[0]["patterns"]} == reported


def test_all_detected_patterns_inactive_means_clean(client, monkeypatch):
    detected = {f["pattern_code"] for f in client.post("/api/analyze", json={"code": FIND_DUPLICATES}).json()["findings"]}
    for code in detected:
        client.patch(f"/api/patterns/{code}/active", json={"is_active": False})
    fake = use_llm(monkeypatch)
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()
    assert body["status"] == "clean"
    assert fake.calls == []


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

    # Tahmini enerji: doğrulanmış ve hızlanmış sonuçta, ölçülen sürelerden.
    bench = body["verification"]["benchmark"]
    assert body["energy"]["kwh_per_year"] > 0
    assert body["energy"]["joules_per_run"] == pytest.approx((bench["old_seconds"] - bench["new_seconds"]) * 65)

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
    assert body["energy"] is None  # doğrulanmamış koda enerji tahmini yok


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


def test_fib_without_llm_benchmark_input_is_still_measured(client, monkeypatch):
    naive = "def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n"
    iterative = "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"
    result = {**llm_result(iterative), "test_inputs": {"fib": [[0], [1], [5], [10], [18]]}, "benchmark_input": {}}
    use_llm(monkeypatch, result)
    body = client.post("/api/optimize", json={"code": naive}).json()

    assert body["status"] == "optimized"
    bench = body["verification"]["benchmark"]
    assert bench is not None and bench["speedup"] > 10
    assert "en büyüğüyle" in bench["functions"][0]["note"]
    assert body["energy"] is not None


PROCESS_QUEUE = (
    "def process_queue(tasks):\n    done = []\n    while tasks:\n        done.append(tasks.pop(0) * 2)\n    return done\n"
)


def queue_result(green_code: str) -> dict:
    return {**llm_result(green_code), "changes": [{"pattern": "YK-07", "explanation": "deque"}],
            "test_inputs": {"process_queue": [[[1, 2, 3]], [[]], [[5]], [[4, 4, 1]]]}, "benchmark_input": {}}


def test_side_effect_feedback_tells_llm_how_argument_differs(client, monkeypatch):
    no_clear = ("from collections import deque\ndef process_queue(tasks):\n    queue = deque(tasks)\n"
                "    done = []\n    while queue:\n        done.append(queue.popleft() * 2)\n    return done\n")
    with_clear = no_clear.replace("    queue = deque(tasks)\n", "    queue = deque(tasks)\n    tasks.clear()\n")
    fake = use_llm(monkeypatch, queue_result(no_clear), queue_result(with_clear))
    body = client.post("/api/optimize", json={"code": PROCESS_QUEUE}).json()

    feedback = fake.calls[1]["feedback"]
    assert "YAN ETKİ FARKI" in feedback
    assert "`tasks` argümanını [] hâline getiriyor, senin kodun [1, 2, 3] bırakıyor" in feedback
    assert "bu yan etkiyi koru" in feedback
    assert "beklenen (orijinal) [2, 4, 6], senin kodun [2, 4, 6]" not in feedback  # çelişkili satır yok
    assert body["status"] == "optimized" and body["attempts"] == 2


def test_side_effect_failure_message(client, monkeypatch):
    no_clear = ("from collections import deque\ndef process_queue(tasks):\n    queue = deque(tasks)\n"
                "    done = []\n    while queue:\n        done.append(queue.popleft() * 2)\n    return done\n")
    use_llm(monkeypatch, queue_result(no_clear), queue_result(no_clear))
    body = client.post("/api/optimize", json={"code": PROCESS_QUEUE}).json()
    assert body["status"] == "failed"
    assert body["error"].startswith("Yan etki farkı")


# --------------------------------------------------------------------------- #
# Tespit edilen desenleri gidermeyen (ör. değişmemiş) kod optimizasyon sayılmaz
# --------------------------------------------------------------------------- #

TOP_SCORES = (
    "def top_scores(scores):\n    result = []\n    for s in scores:\n"
    "        result.append(s)\n        result.sort()\n    return result[-3:]\n"
)
TOP_SCORES_GREEN = "def top_scores(scores):\n    return sorted(scores)[-3:]\n"


def scores_result(green_code: str) -> dict:
    return {**llm_result(green_code), "changes": [{"pattern": "YK-08", "explanation": "tek sıralama"}],
            "test_inputs": {"top_scores": [[[50, 90, 70, 80]], [[]], [[5]], [[3, 3, 1]]]}, "benchmark_input": {}}


@pytest.fixture
def verify_calls(monkeypatch):
    calls = []
    real = main.verify

    def counting(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(main, "verify", counting)
    return calls


def test_unchanged_code_is_rejected_without_verification(client, monkeypatch, verify_calls):
    fake = use_llm(monkeypatch, scores_result(TOP_SCORES), scores_result(TOP_SCORES_GREEN))
    body = client.post("/api/optimize", json={"code": TOP_SCORES}).json()

    assert body["status"] == "optimized" and body["attempts"] == 2
    assert verify_calls == [TOP_SCORES_GREEN]  # değişmemiş kod doğrulayıcıya gönderilmedi
    feedback = fake.calls[1]["feedback"]
    assert "orijinal kodla AYNI" in feedback and "YK-08" in feedback and "Satır 5" in feedback


def test_whitespace_only_change_counts_as_unchanged(client, monkeypatch):
    reformatted = TOP_SCORES.replace("    ", "\t").replace("\n", "  \r\n")
    use_llm(monkeypatch, scores_result(reformatted), scores_result(reformatted))
    body = client.post("/api/optimize", json={"code": TOP_SCORES}).json()
    assert body["status"] == "failed"
    assert body["error"].startswith("Önerilen kod orijinalle aynı")


def test_changed_code_that_keeps_all_patterns_is_rejected(client, monkeypatch, verify_calls):
    # Kod değişmiş ama döngü içindeki sıralama duruyor (sorted() ile).
    still_sorting = (
        "def top_scores(scores):\n    result = []\n    for s in scores:\n"
        "        result = sorted(result + [s])\n    return result[-3:]\n"
    )
    fake = use_llm(monkeypatch, scores_result(still_sorting), scores_result(still_sorting))
    body = client.post("/api/optimize", json={"code": TOP_SCORES}).json()

    assert body["status"] == "failed" and body["attempts"] == 2
    assert body["error"] == "Önerilen kod tespit edilen desenlerin hiçbirini gidermiyor; hâlâ YK-08 içeriyor."
    assert body["verification"] is None and verify_calls == []
    assert body["green_code"] == still_sorting  # inceleme için gösterilir ("Önerilmez")
    feedback = fake.calls[1]["feedback"]
    assert "HİÇBİRİNİ gidermedi" in feedback
    assert "YK-08 Döngü içinde sıralama — satır 4: `result = sorted(result + [s])`" in feedback


def test_partial_progress_goes_to_verification(client, monkeypatch, verify_calls):
    # find_duplicates: YK-01 + YK-02 (+ YK-04). Yalnızca YK-02 giderildi, iç içe döngü duruyor.
    only_membership = """\
def find_duplicates(items):
    duplicates = []
    seen = set()
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j] and items[i] not in seen:
                seen.add(items[i])
                duplicates.append(items[i])
    return duplicates
"""
    use_llm(monkeypatch, llm_result(only_membership))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()
    assert verify_calls == [only_membership]
    assert body["status"] == "optimized", body["error"]


# --------------------------------------------------------------------------- #
# Sıra ipucu önerilen koda göre
# --------------------------------------------------------------------------- #

HEAP_TOP3 = (
    "import heapq\n\ndef top_scores(scores):\n    result = []\n    for s in scores:\n"
    "        heapq.heappush(result, s)\n        if len(result) > 3:\n            heapq.heappop(result)\n"
    "    return result\n"
)


def test_heap_order_error_gets_heap_hint_not_set_hint(client, monkeypatch):
    fake = use_llm(monkeypatch, scores_result(HEAP_TOP3), scores_result(TOP_SCORES_GREEN))
    body = client.post("/api/optimize", json={"code": TOP_SCORES}).json()
    feedback = fake.calls[1]["feedback"]
    assert "SIRASI farklı" in feedback
    assert "heapq listeyi sıralı TUTMAZ" in feedback and "sorted(...)" in feedback
    assert "ARTAN SIRADA" in feedback          # orijinal sonuç sıralı
    assert "set'in dolaşma sırası" not in feedback  # kodda set yok
    assert body["status"] == "optimized"


def test_set_order_error_keeps_set_hint(client, monkeypatch):
    set_order = (
        "def find_duplicates(items):\n    seen, dups = set(), set()\n    for x in items:\n"
        "        (dups if x in seen else seen).add(x)\n    return list(dups)\n"
    )
    fake = use_llm(monkeypatch, llm_result(set_order), llm_result(GREEN_DUPLICATES))
    client.post("/api/optimize", json={"code": FIND_DUPLICATES})
    feedback = fake.calls[1]["feedback"]
    assert "set'in dolaşma sırası tanımsızdır" in feedback and "heapq" not in feedback


def test_order_hint_without_set_or_heap_is_generic():
    from app.main import _order_hint
    hint = _order_hint([{"old": "[3, 1, 2]", "new": "[1, 2, 3]"}], "def f(a):\n    return sorted(a)\n")
    assert "çıktı sırasını" in hint and "set" not in hint and "heapq" not in hint


# --------------------------------------------------------------------------- #
# Tekrar sayısı ipucu (veriden çıkarılır, fonksiyona özel değil)
# --------------------------------------------------------------------------- #

from app.main import _multiplicity_lost  # noqa: E402

COMMON_USERS = (
    "def find_common_users(group_a, group_b):\n    common = []\n    for a in group_a:\n"
    "        for b in group_b:\n            if a == b:\n                common.append(a)\n    return common\n"
)
COMMON_FILTER = (
    "from collections import Counter\n\ndef find_common_users(group_a, group_b):\n"
    "    counts = Counter(group_b)\n    return [x for x in group_a if counts[x] > 0]\n"
)
COMMON_COUNTS = (
    "from collections import Counter\n\ndef find_common_users(group_a, group_b):\n"
    "    counts = Counter(group_b)\n    result = []\n    for x in group_a:\n"
    "        result.extend([x] * counts[x])\n    return result\n"
)


def users_result(green_code: str) -> dict:
    return {**llm_result(green_code), "changes": [{"pattern": "YK-01", "explanation": "Counter"}],
            "test_inputs": {"find_common_users": [[[1, 2, 3], [2, 3, 4]], [[], [1]], [[1], [1, 1]], [["a"], ["b"]]]},
            "benchmark_input": {}}


@pytest.mark.parametrize("old, new, expected", [
    ("[1, 1]", "[1]", True),                 # tekrar eksik
    ("[1, 1, 2, 2, 2]", "[1, 2]", True),
    ("['a', 'a', 'b']", "['a', 'b']", True),
    ("[1, 2]", "[2, 1]", False),             # yalnızca sıra farkı (sıra ipucunun alanı)
    ("[1, 1]", "[]", False),                 # eleman kaybı: farklı elemanlar
    ("[1, 1]", "[1, 2]", False),             # yeni eleman
    ("[1]", "[1, 1]", False),                # fazla tekrar
    ("[1, 1]", "[1, 1]", False),             # eşit
    ("5", "3", False),                       # liste değil
    ("[[1], [1]]", "[[1]]", True),           # hash'lenemeyen elemanlar repr ile sayılır
])
def test_multiplicity_lost(old, new, expected):
    assert _multiplicity_lost(old, new) is expected


def test_lost_repeats_get_counter_hint(client, monkeypatch):
    fake = use_llm(monkeypatch, users_result(COMMON_FILTER), users_result(COMMON_COUNTS))
    body = client.post("/api/optimize", json={"code": COMMON_USERS}).json()
    feedback = fake.calls[1]["feedback"]
    assert "TEKRAR SAYILARI eksik" in feedback
    assert "find_common_users(*[[1], [1, 1]]) için orijinal [1, 1], seninki [1]" in feedback  # en küçük karşı örnek
    assert "result.extend([x] * counts[x])" in feedback
    assert "SIRASI farklı" not in feedback
    assert body["status"] == "optimized" and body["attempts"] == 2


def test_order_only_difference_does_not_get_repeat_hint(client, monkeypatch):
    set_order = (
        "def find_duplicates(items):\n    seen, dups = set(), set()\n    for x in items:\n"
        "        (dups if x in seen else seen).add(x)\n    return list(dups)\n"
    )
    fake = use_llm(monkeypatch, llm_result(set_order), llm_result(GREEN_DUPLICATES))
    client.post("/api/optimize", json={"code": FIND_DUPLICATES})
    assert "TEKRAR SAYILARI" not in fake.calls[1]["feedback"]


# --------------------------------------------------------------------------- #
# Doğru ama ölçümde YAVAŞ kod optimizasyon sayılmaz
# --------------------------------------------------------------------------- #

LABEL = "def label(items):\n    out = []\n    for item in items:\n        out.append(f\"{item}/{len(items)}\")\n    return out\n"
LABEL_FAST = "def label(items):\n    n = len(items)\n    return [f\"{item}/{n}\" for item in items]\n"
# Desen giderildi ve sonuç doğru, ama her çağrı 20 ms bekliyor: ölçümde daha yavaş.
LABEL_SLOW = "import time\n\ndef label(items):\n    time.sleep(0.02)\n    n = len(items)\n    return [f\"{item}/{n}\" for item in items]\n"


def label_result(green_code: str) -> dict:
    return {**llm_result(green_code), "changes": [{"pattern": "YK-04", "explanation": "len dışarı"}],
            "test_inputs": {"label": [[["a", "b"]], [[]], [["x"]], [[1, 2, 3]]]},
            "benchmark_input": {"label": "[[random.randint(0, 9) for _ in range(200)]]"}}


def test_slower_code_is_retried_with_feedback(client, monkeypatch):
    fake = use_llm(monkeypatch, label_result(LABEL_SLOW), label_result(LABEL_FAST))
    body = client.post("/api/optimize", json={"code": LABEL}).json()
    feedback = fake.calls[1]["feedback"]
    assert "eski koddan YAVAŞ" in feedback and "eşdeğerlik testini geçti" in feedback
    assert body["status"] == "optimized" and body["attempts"] == 2
    assert body["verification"]["benchmark"]["speedup"] >= 1


def test_slower_code_twice_is_failed_not_optimized(client, monkeypatch):
    use_llm(monkeypatch, label_result(LABEL_SLOW), label_result(LABEL_SLOW))
    body = client.post("/api/optimize", json={"code": LABEL}).json()
    assert body["status"] == "failed"
    assert body["verification"]["passed"] is True  # eşdeğerlik geçti; tabloda "Geçti" görünür
    assert body["error"].startswith("Önerilen kod doğru ama ölçümde eski koddan yavaş")
    assert body["energy"] is None


# --------------------------------------------------------------------------- #
# Sıra ipucu: orijinal ve önerilen kodun sırası veriden tarif edilir
# --------------------------------------------------------------------------- #

from app.main import _order_rule  # noqa: E402

SECOND_SEEN = (
    "def find_duplicates(items):\n    seen = set()\n    dups = []\n    added = set()\n"
    "    for x in items:\n        if x in seen:\n            if x not in added:\n"
    "                added.add(x)\n                dups.append(x)\n        else:\n"
    "            seen.add(x)\n    return dups\n"
)


@pytest.mark.parametrize("examples, expected", [
    ([([1, 2, 2, 1], [1, 2]), ([3, 1, 3, 2, 1], [3, 1])], "ilk görülme"),
    # [1, 2, 2, 1] → [2, 1] ilk görülmeyi, [1, 2, 1, 2, 1] → [1, 2] son görülmeyi dışlar.
    ([([1, 2, 2, 1], [2, 1]), ([1, 2, 1, 2, 1], [1, 2])], "ikinci görülme"),
    ([([1, 2, 2, 1], [1, 2])], "ilk görülme"),
    ([([5, 5, 4], [5, 4])], None),            # hem ilk hem son görülmeye uyuyor: belirsiz
    ([([1, 2, 1], [2, 1])], "son görülme"),
    ([([1, 2, 3], [1, 2, 3])], None),        # bütün kurallar aynı sırayı veriyor: belirsiz
    ([([1, 2], [9, 1])], None),               # girdide olmayan eleman
])
def test_order_rule(examples, expected):
    assert _order_rule(examples) == expected


def test_order_feedback_describes_first_vs_second_occurrence(client, monkeypatch):
    fake = use_llm(monkeypatch, llm_result(SECOND_SEEN), llm_result(GREEN_DUPLICATES))
    body = client.post("/api/optimize", json={"code": FIND_DUPLICATES}).json()
    feedback = fake.calls[1]["feedback"]
    assert "Orijinal kod elemanları girdideki İLK GÖRÜLME SIRASINA göre döndürüyor" in feedback
    assert "senin kodun ise ikinci görülme sırasına göre döndürüyor" in feedback
    assert "ARTAN SIRADA" not in feedback  # küçük [1, 2] örneği tesadüfen sıralı; yanıltıcı cümle yok
    assert body["status"] == "optimized"

