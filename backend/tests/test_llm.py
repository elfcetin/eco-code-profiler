import json

import httpx
import pytest

from app import config, llm
from app.patterns import PATTERNS_BY_CODE

ORIGINAL = """\
def find_pair(numbers, target):
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            if numbers[i] + numbers[j] == target:
                return (i, j)
    return None
"""

GREEN = """\
def find_pair(numbers, target):
    seen = {}
    for j, x in enumerate(numbers):
        i = seen.get(target - x)
        if i is not None:
            return (i, j)
        seen.setdefault(x, j)
    return None
"""

FINDINGS = [{"line": 2, "pattern_code": "YK-05", "title": "two-sum", "detail": "iç içe döngü", "impact": "yüksek"}]
PATTERNS = [PATTERNS_BY_CODE["YK-05"]]


def llm_payload(**overrides) -> dict:
    payload = {
        "green_code": GREEN,
        "changes": [{"pattern": "YK-05", "explanation": "Hash map ile tek geçiş."}],
        "test_inputs": {"find_pair": [[[], 3], [[1], 2], [[1, 2, 3], 5], [[3, 3], 6]]},
        "benchmark_input": {"find_pair": "[[random.randint(0, 9999) for _ in range(5000)], -1]"},
        "notes": "",
    }
    payload.update(overrides)
    return payload


def ollama_client(content: str, seen: list | None = None, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, text=content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def ollama_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama.test:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3:8b")


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #

def test_ollama_request_and_parsed_result():
    seen: list[httpx.Request] = []
    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(json.dumps(llm_payload()), seen))

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://ollama.test:11434/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "llama3:8b"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["options"]["temperature"] == 0.2
    assert body["messages"][0]["role"] == "system"
    assert "SADECE verilen Yeşil Kod Desenlerini kullan" in body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    assert "YK-05" in user and "find_pair(numbers, target)" in user

    assert result["green_code"] == GREEN
    assert result["changes"][0]["pattern"] == "YK-05"
    assert len(result["test_inputs"]["find_pair"]) == 4
    assert "find_pair" in result["benchmark_input"]
    assert result["warnings"] == []
    assert result["provider"] == "ollama" and result["model"] == "llama3:8b"


def test_feedback_is_included_in_prompt():
    seen: list[httpx.Request] = []
    llm.optimize(
        ORIGINAL, FINDINGS, PATTERNS, feedback="Girdi [3, 3] için sonuç farklı.",
        client=ollama_client(json.dumps(llm_payload()), seen),
    )
    assert "Girdi [3, 3] için sonuç farklı." in json.loads(seen[0].content)["messages"][1]["content"]


def test_markdown_fenced_json_is_accepted():
    content = "```json\n" + json.dumps(llm_payload()) + "\n```"
    assert llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))["green_code"] == GREEN


def test_broken_json_raises():
    with pytest.raises(llm.LLMResponseError, match="JSON"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client('{"green_code": "x = 1",'))


def test_green_code_syntax_error_raises():
    content = json.dumps(llm_payload(green_code="def find_pair(numbers, target)\n    return None\n"))
    with pytest.raises(llm.LLMResponseError, match="sözdizimi"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))


def test_changed_signature_raises():
    content = json.dumps(llm_payload(green_code="def find_pair(numbers, target=0):\n    return None\n"))
    with pytest.raises(llm.LLMResponseError, match="imzası değiştirilmiş"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))


def test_missing_function_raises():
    content = json.dumps(llm_payload(green_code="def other(numbers, target):\n    return None\n"))
    with pytest.raises(llm.LLMResponseError, match="eksik"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))


def test_too_few_test_inputs_is_a_warning():
    content = json.dumps(llm_payload(test_inputs={"find_pair": [[[1, 2], 3]]}))
    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))
    assert any("en az 4" in w for w in result["warnings"])


def test_ollama_unreachable_gives_turkish_message():
    def handler(request):
        raise httpx.ConnectError("Connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(llm.LLMUnavailableError, match="ulaşılamadı"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=client)


def test_ollama_model_not_found():
    client = ollama_client('{"error":"model \\"llama3:8b\\" not found, try pulling it first"}', status=404)
    with pytest.raises(llm.LLMUnavailableError, match="ollama pull llama3:8b"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=client)


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

def test_gemini_request_and_parsed_result(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-test")
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": json.dumps(llm_payload())}]}}]
        })

    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=httpx.Client(transport=httpx.MockTransport(handler)))

    request = seen[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path.endswith("/models/gemini-test:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["generationConfig"] == {"temperature": 0.2, "responseMimeType": "application/json"}
    assert "SADECE" in body["systemInstruction"]["parts"][0]["text"]
    assert result["green_code"] == GREEN
    assert result["provider"] == "gemini" and result["model"] == "gemini-test"


def test_gemini_without_key_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client("{}"))


# --------------------------------------------------------------------------- #
# Test girdisi biçimi
# --------------------------------------------------------------------------- #

DUP_ORIGINAL = "def find_duplicates(items):\n    return []\n"


def test_prompt_shows_argument_shape_per_function():
    prompt = llm.build_prompt(DUP_ORIGINAL, [], [])
    assert "[<items>]" in prompt
    assert "[<numbers>, <target>]" in llm.build_prompt(ORIGINAL, [], [])


def test_inputs_with_too_few_arguments_raise():
    content = json.dumps(llm_payload(test_inputs={"find_pair": [[[1, 2]], [[3]]]}))
    with pytest.raises(llm.LLMResponseError, match="imzaya uymuyor"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))


def test_expected_output_appended_to_inputs_is_trimmed():
    """llama3:8b gerçekte böyle yanıt verdi: [girdi, beklenen_çıktı]."""
    content = json.dumps(llm_payload(
        green_code=DUP_ORIGINAL,
        test_inputs={"find_duplicates": [[[1, 2, 2, 3], [2]], [[], []], [[5], []], [[1, 1], [1]]]},
        benchmark_input={},
    ))
    result = llm.optimize(DUP_ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))
    assert result["test_inputs"] == {"find_duplicates": [[[1, 2, 2, 3]], [[]], [[5]], [[1, 1]]]}
    assert any("beklenen çıktı" in w for w in result["warnings"])


def test_inputs_with_wrong_arity_are_filtered():
    content = json.dumps(llm_payload(
        test_inputs={"find_pair": [[[1, 2], 3], [[1]], [[], 0], [[4], 8], [[3, 3], 6]], "yok": [[1]]},
    ))
    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))
    assert result["test_inputs"] == {"find_pair": [[[1, 2], 3], [[], 0], [[4], 8], [[3, 3], 6]]}
    assert any("imzaya uymayan 1" in w for w in result["warnings"])
    assert any("'yok'" in w for w in result["warnings"])


# --------------------------------------------------------------------------- #
# Parametre adı onarımı (llama3:8b gerçekte `numbers` yerine `nums` yazdı)
# --------------------------------------------------------------------------- #

RENAMED_GREEN = """\
def find_pair(nums, target):
    seen = {}  # değer -> indeks
    for j, x in enumerate(nums):
        i = seen.get(target - x)
        if i is not None:
            return (i, j)
        seen.setdefault(x, j)
    return None
"""


def test_renamed_parameters_are_restored():
    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(json.dumps(llm_payload(green_code=RENAMED_GREEN))))
    assert result["green_code"].startswith("def find_pair(numbers, target):")
    assert "enumerate(numbers)" in result["green_code"]
    assert "nums" not in result["green_code"]
    assert "# değer -> indeks" in result["green_code"]  # biçim ve yorumlar korunur
    assert any("nums → numbers" in w for w in result["warnings"])


def test_rename_is_refused_when_names_collide():
    green = "numbers = []\ndef find_pair(nums, target):\n    return numbers or nums\n"
    with pytest.raises(llm.LLMResponseError, match="find_pair\\(numbers, target\\) olmalı"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(json.dumps(llm_payload(green_code=green))))


def test_type_hints_are_not_a_signature_change():
    green = "def find_pair(numbers: list[int], target: int) -> tuple | None:\n    return None\n"
    result = llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(json.dumps(llm_payload(green_code=green))))
    assert result["green_code"] == green


# --------------------------------------------------------------------------- #
# JSON kaçış onarımı (llama3:8b f-string içindeki \n'i tek \ ile yazdı)
# --------------------------------------------------------------------------- #

REPORT_ORIGINAL = (
    'def build_report(records):\n'
    '    report = ""\n'
    '    for record in records:\n'
    '        report += f"{record} (toplam {len(records)} kayıt)\\n"\n'
    '    return report\n'
)


def test_broken_newline_escape_in_string_is_repaired():
    # Modelin JSON'unda "\n" (tek ters eğik çizgi) -> çözülünce string içinde gerçek satır sonu.
    raw = (
        '{"green_code": "def build_report(records):\\n    n = len(records)\\n'
        '    return \\"\\".join(f\\"{r} (toplam {n} kayıt)\\n\\" for r in records)\\n",'
        ' "changes": [], "test_inputs": {"build_report": [[["a"]], [[]], [["a", "b"]], [["x"]]]},'
        ' "benchmark_input": {}, "notes": ""}'
    )
    result = llm.optimize(REPORT_ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(raw))
    assert 'kayıt)\\n" for r in records)' in result["green_code"]
    assert any("onarıldı" in w for w in result["warnings"])
    ns = {}
    exec(result["green_code"], ns)
    assert ns["build_report"](["a", "b"]) == "a (toplam 2 kayıt)\nb (toplam 2 kayıt)\n"


def test_real_syntax_error_is_not_repaired():
    content = json.dumps(llm_payload(green_code="def find_pair(numbers, target):\n    return (\n"))
    with pytest.raises(llm.LLMResponseError, match="sözdizimi"):
        llm.optimize(ORIGINAL, FINDINGS, PATTERNS, client=ollama_client(content))


def test_prompt_asks_for_worst_case_benchmark_input():
    prompt = llm.build_prompt(ORIGINAL, FINDINGS, PATTERNS)
    assert "eşleşmenin HİÇ" in prompt and "ulaşılamayan bir hedef değer" in prompt


def test_prompt_forbids_changing_regex_and_constants():
    prompt = llm.build_prompt(ORIGINAL, FINDINGS, PATTERNS)
    assert "Regex desenlerini, sabitleri" in prompt and "regex'in kendisini değiştirme" in prompt

