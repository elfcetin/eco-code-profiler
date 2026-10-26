"""LLM ile Yeşil Kod Desenlerine göre yeniden yazma.

Sağlayıcı `LLM_PROVIDER` ile seçilir: "ollama" (yerel, varsayılan) veya "gemini".
Model yalnızca belirli bir JSON nesnesi döndürmeye zorlanır; yanıt burada
doğrulanır (JSON yapısı, green_code sözdizimi, fonksiyon imzaları).
"""

from __future__ import annotations

import ast
import json
import time
from contextlib import contextmanager
from typing import Iterator

import httpx

from . import config

SYSTEM_PROMPT = (
    "Sen Eco-Code Profiler'ın optimizasyon motorusun. SADECE verilen Yeşil Kod Desenlerini kullan, "
    "fonksiyon adlarını ve imzalarını değiştirme, davranışı (çıktı sırası dahil) koru, emin "
    "olmadığın değişikliği yapma. Watt/kWh/saniye uydurma.\n"
    "Yanıtın yalnızca tek bir JSON nesnesi olmalı; JSON dışında metin veya markdown yazma."
)

RESPONSE_FORMAT = """\
Yanıtı TAM OLARAK şu yapıda bir JSON nesnesi olarak ver:
{
  "green_code": "<optimize edilmiş, çalıştırılabilir tam Python kodu>",
  "changes": [{"pattern": "YK-xx", "explanation": "<Türkçe kısa açıklama>"}],
  "test_inputs": {"<fonksiyon_adı>": [[arg1, arg2], ...]},
  "benchmark_input": {"<fonksiyon_adı>": "<argüman listesi üreten Python ifadesi>"},
  "notes": "<Türkçe notlar>"
}

Kurallar:
- green_code, orijinal koddaki tüm fonksiyonları AYNI ad ve imzayla içermeli; gereken importları eklemeli.
  Parametre adlarını AYNEN koru; desen örneklerindeki adları (ör. nums, items) kopyalama.
- changes: yalnızca gerçekten uyguladığın desenleri listele.
- Yalnızca tespit edilen desenleri uygula; başka hiçbir şeyi "iyileştirme". Regex desenlerini, sabitleri,
  metin biçimlerini, yuvarlama/biçimlendirmeyi ve kenar durum davranışını (boş girdi, hata fırlatma) AYNEN koru.
  Örneğin döngüdeki re.compile'ı dışarı alırken regex'in kendisini değiştirme.
- test_inputs: her fonksiyon için EN AZ 4 girdi ver; en az biri boş/kenar durum olsun (ör. boş liste, tek eleman).
  Her girdi, fonksiyonun argümanlarını SIRAYLA içeren bir listedir; eleman sayısı argüman sayısına EŞİT olmalı.
  Örnekler:
    f(items) tek argüman alır, her girdi [items] olur:
      "f": [[[3, 1, 3, 2]], [[]], [[7]], [[5, 5, 5]]]
    g(numbers, target) iki argüman alır, her girdi [numbers, target] olur:
      "g": [[[1, 2, 3], 5], [[], 1], [[4], 8], [[3, 3], 6]]
  Girdiye beklenen çıktıyı EKLEME; beklenen sonuç orijinal kod çalıştırılarak hesaplanır.
  Girdiler, orijinal kodun HATASIZ çalıştığı gerçekçi değerler olmalı.
  Yalnızca JSON değerleri (sayı, string, liste, sözlük, true/false/null) kullan.
- benchmark_input: her fonksiyon için, değerlendirildiğinde yine [arg1, arg2, ...] biçiminde ARGÜMAN LİSTESİ
  döndüren tek bir Python ifadesi (string). random modülü kullanılabilir; yaklaşık 5000 elemanlı veri üret.
  Örnekler: f(items) için "[[random.randint(0, 1000) for _ in range(5000)]]",
            g(numbers, target) için "[[random.randint(0, 10000) for _ in range(5000)], -1]".
  Orijinal sürümü üstel (O(2^N)) olan fonksiyonlarda N'yi küçük tut (ör. 25).
  Fonksiyon bir şey arıyor ve bulunca erken dönüyorsa (return), benchmark girdisini eşleşmenin HİÇ
  bulunmadığı veya en sonda bulunduğu şekilde üret (ör. two-sum için ulaşılamayan bir hedef değer).
- Bir deseni güvenle uygulayamıyorsan o kısmı değiştirme ve nedenini notes alanında açıkla.
"""


class LLMError(Exception):
    """LLM katmanındaki tüm hataların temeli."""


class LLMUnavailableError(LLMError):
    """LLM servisine ulaşılamadı veya servis hata döndürdü."""


class LLMResponseError(LLMError):
    """LLM yanıtı beklenen JSON'a veya kurallara uymuyor."""


# --------------------------------------------------------------------------- #
# İstem
# --------------------------------------------------------------------------- #

def _function_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    """Üst seviye fonksiyonlar ve sınıf metotları (Sınıf.metot) -> düğüm."""
    result: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result[f"{node.name}.{item.name}"] = item
    return result


def _all_params(fn: ast.AST) -> list[ast.arg]:
    a = fn.args
    return [*a.posonlyargs, *a.args, *filter(None, [a.vararg]), *a.kwonlyargs, *filter(None, [a.kwarg])]


def _signature(fn: ast.AST, with_names: bool = True) -> tuple:
    """Davranışı belirleyen imza: tür, parametre türleri/adları, varsayılanlar (tür ipuçları hariç)."""
    a = fn.args
    names = lambda params: [p.arg if with_names else "_" for p in params]  # noqa: E731
    return (
        type(fn).__name__,
        names(a.posonlyargs),
        names(a.args),
        a.vararg.arg if a.vararg and with_names else bool(a.vararg),
        names(a.kwonlyargs),
        a.kwarg.arg if a.kwarg and with_names else bool(a.kwarg),
        [ast.dump(d) for d in a.defaults],
        [ast.dump(d) if d else None for d in a.kw_defaults],
    )


def _format_signature(name: str, fn: ast.AST) -> str:
    return f"{name.rsplit('.', 1)[-1]}({', '.join(p.arg for p in _all_params(fn))})"


def _rename_params(source: str, qualname: str, mapping: dict[str, str]) -> str | None:
    """Fonksiyondaki parametre adlarını (ve gövdedeki kullanımlarını) metin üzerinde yeniden adlandırır.

    Yeni adlardan biri fonksiyonda zaten kullanılıyorsa (çakışma) None döner. Tutarlı bir
    yeniden adlandırma davranışı değiştirmez; biçimlendirme ve yorumlar korunur.
    """
    fn = _function_nodes(ast.parse(source))[qualname]
    nodes = list(ast.walk(fn))
    used = {n.id for n in nodes if isinstance(n, ast.Name)} | {n.arg for n in nodes if isinstance(n, ast.arg)}
    if any(new in used for new in mapping.values()):
        return None

    spans = []  # (satır, başlangıç, bitiş, yeni ad) — sütunlar UTF-8 bayt ofsetidir
    for n in nodes:
        if isinstance(n, ast.Name) and n.id in mapping:
            spans.append((n.lineno, n.col_offset, n.end_col_offset, mapping[n.id]))
        elif isinstance(n, ast.arg) and n.arg in mapping:
            spans.append((n.lineno, n.col_offset, n.col_offset + len(n.arg.encode()), mapping[n.arg]))

    lines = source.splitlines(keepends=True)
    for lineno, start, end, new in sorted(spans, reverse=True):
        raw = lines[lineno - 1].encode()
        lines[lineno - 1] = (raw[:start] + new.encode() + raw[end:]).decode()
    return "".join(lines)


def _positional_arity(fn: ast.AST) -> tuple[list[str], int, int | None]:
    """(konumsal parametre adları, en az, en çok — *args varsa None)."""
    params = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]]
    minimum = len(params) - len(fn.args.defaults)
    maximum = None if fn.args.vararg else len(params)
    return params, minimum, maximum


def _top_level_functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _describe_functions(tree: ast.Module) -> str:
    lines = []
    for name, fn in _top_level_functions(tree).items():
        params, minimum, maximum = _positional_arity(fn)
        count = f"{minimum}" if minimum == maximum else f"{minimum}-{maximum if maximum is not None else 'N'}"
        shape = "[" + ", ".join(f"<{p}>" for p in params) + "]"
        lines.append(
            f"- {name}({ast.unparse(fn.args)}) — {count} argüman; "
            f"her test girdisi ve benchmark ifadesinin sonucu {shape} biçiminde olmalı."
        )
    return "\n".join(lines) or "- (üst seviye fonksiyon yok)"


def build_prompt(code: str, findings: list[dict], patterns: list[dict], feedback: str | None = None) -> str:
    tree = ast.parse(code)

    finding_lines = [
        f"- Satır {f.get('line')}: {f.get('pattern_code')} {f.get('title', '')} — {f.get('detail', '')}"
        for f in findings
    ] or ["- (bulgu yok)"]

    pattern_blocks = [
        f"### {p['code']} — {p['title']}\n"
        f"Sorun: {p['anti_pattern']}\n"
        f"Çözüm: {p['solution']}\n"
        f"Önce:\n```python\n{p['example_before'].rstrip()}\n```\n"
        f"Sonra:\n```python\n{p['example_after'].rstrip()}\n```"
        for p in patterns
    ] or ["(desen yok)"]

    parts = [
        "## Onaylı Yeşil Kod Desenleri (yalnızca bunları kullan)",
        "\n\n".join(pattern_blocks),
        "## Statik analiz bulguları",
        "\n".join(finding_lines),
        "## Korunması gereken fonksiyonlar (ad ve imza değişmeyecek)",
        _describe_functions(tree),
        "## Orijinal kod",
        f"```python\n{code.rstrip()}\n```",
    ]
    if feedback:
        parts += [
            "## Önceki denemeden geri bildirim (bu sorunları düzelt)",
            feedback.strip(),
        ]
    parts.append(RESPONSE_FORMAT)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Sağlayıcılar
# --------------------------------------------------------------------------- #

@contextmanager
def _http_client(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
    else:
        with httpx.Client() as own:
            yield own


def _call_ollama(system: str, user: str, client: httpx.Client) -> str:
    url = f"{config.OLLAMA_URL}/api/chat"
    body = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    try:
        resp = client.post(url, json=body, timeout=config.LLM_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise LLMUnavailableError(
            f"Ollama {config.LLM_TIMEOUT:.0f} saniye içinde yanıt vermedi. Model çok yavaş çalışıyor "
            "olabilir; LLM_TIMEOUT değerini artırmayı veya daha küçük bir model kullanmayı deneyin."
        ) from exc
    except httpx.RequestError as exc:
        raise LLMUnavailableError(
            f"Yerel LLM servisine (Ollama) ulaşılamadı: {config.OLLAMA_URL}. "
            "Ollama'nın çalıştığından (`ollama serve`) ve OLLAMA_URL ayarının doğru olduğundan emin olun."
        ) from exc

    if resp.status_code == 404 and "not found" in resp.text.lower():
        raise LLMUnavailableError(
            f"Ollama'da '{config.OLLAMA_MODEL}' modeli bulunamadı. "
            f"Kurmak için: `ollama pull {config.OLLAMA_MODEL}`"
        )
    if resp.is_error:
        raise LLMUnavailableError(f"Ollama hata döndürdü (HTTP {resp.status_code}): {resp.text[:300]}")

    try:
        return resp.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMResponseError("Ollama yanıtı beklenen biçimde değil (message.content yok).") from exc


# Gemini geçici yoğunluk (503) veya istek sınırı (429) döndürürse bu sürelerle (sn) tekrar dener:
# toplam en fazla 1 + 3 istek.
GEMINI_RETRY_STATUSES = (429, 503)
GEMINI_RETRY_DELAYS = (2, 4, 8)
_sleep = time.sleep  # testlerde gerçek bekleme yapılmasın


def _call_gemini(system: str, user: str, client: httpx.Client) -> str:
    if not config.GEMINI_API_KEY:
        raise LLMError("LLM_PROVIDER=gemini seçili ama GEMINI_API_KEY tanımlı değil.")

    url = f"{GEMINI_BASE_URL}/models/{config.GEMINI_MODEL}:generateContent"
    generation_config: dict = {"temperature": 0.2, "responseMimeType": "application/json"}
    if config.GEMINI_THINKING_LEVEL:
        generation_config["thinkingConfig"] = {"thinkingLevel": config.GEMINI_THINKING_LEVEL}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation_config,
    }
    for delay in (*GEMINI_RETRY_DELAYS, None):
        try:
            resp = client.post(
                url,
                json=body,
                headers={"x-goog-api-key": config.GEMINI_API_KEY},
                timeout=config.LLM_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"Gemini API {config.LLM_TIMEOUT:.0f} saniye içinde yanıt vermedi."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                "Gemini API'ye ulaşılamadı. İnternet bağlantısını kontrol edin; kapalı ağda "
                "LLM_PROVIDER=ollama kullanın."
            ) from exc
        if resp.status_code not in GEMINI_RETRY_STATUSES or delay is None:
            break
        _sleep(delay)

    retries = f" ({len(GEMINI_RETRY_DELAYS)} tekrar denemeden sonra)"
    if resp.status_code in (401, 403):
        raise LLMUnavailableError("Gemini API isteği reddetti: API anahtarı geçersiz veya yetkisiz.")
    if resp.status_code == 429:
        raise LLMUnavailableError(
            f"Gemini API kota/istek sınırına ulaşıldı{retries}; biraz sonra tekrar deneyin."
        )
    if resp.status_code == 503:
        raise LLMUnavailableError(
            f"Gemini API şu an yoğun (HTTP 503){retries}; biraz sonra tekrar deneyin."
        )
    if resp.is_error:
        raise LLMUnavailableError(f"Gemini API hata döndürdü (HTTP {resp.status_code}): {resp.text[:300]}")

    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError("Gemini yanıtında içerik yok (yanıt engellenmiş olabilir).") from exc


PROVIDERS = {"ollama": _call_ollama, "gemini": _call_gemini}

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def health_check(client: httpx.Client | None = None, timeout: float = 3.0) -> dict:
    """Seçili sağlayıcıya ve modele erişilebiliyor mu? (Model çağrısı yapmaz.)"""
    provider = config.LLM_PROVIDER
    model = config.OLLAMA_MODEL if provider == "ollama" else config.GEMINI_MODEL
    status = {"provider": provider, "model": model, "reachable": False, "message": ""}
    try:
        with _http_client(client) as http:
            if provider == "ollama":
                resp = http.get(f"{config.OLLAMA_URL}/api/tags", timeout=timeout)
                resp.raise_for_status()
                names = {m.get("name") for m in resp.json().get("models", [])}
                if model in names or f"{model}:latest" in names:
                    status.update(reachable=True, message="Ollama çalışıyor, model hazır.")
                else:
                    status["message"] = f"Ollama çalışıyor ama '{model}' modeli yok: `ollama pull {model}`"
            elif provider == "gemini":
                if not config.GEMINI_API_KEY:
                    status["message"] = "GEMINI_API_KEY tanımlı değil."
                    return status
                resp = http.get(
                    f"{GEMINI_BASE_URL}/models/{model}",
                    headers={"x-goog-api-key": config.GEMINI_API_KEY},
                    timeout=timeout,
                )
                resp.raise_for_status()
                status.update(reachable=True, message="Gemini API erişilebilir.")
            else:
                status["message"] = f"Bilinmeyen sağlayıcı: {provider!r}"
    except (httpx.HTTPError, ValueError) as exc:
        target = config.OLLAMA_URL if provider == "ollama" else "Gemini API"
        status["message"] = f"{target} adresine ulaşılamadı: {type(exc).__name__}"
    return status


# --------------------------------------------------------------------------- #
# Yanıt doğrulama
# --------------------------------------------------------------------------- #

def _load_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            data = None
        if data is None:
            raise LLMResponseError(f"LLM geçerli bir JSON döndürmedi. Yanıtın başı: {text[:200]!r}")
    if not isinstance(data, dict):
        raise LLMResponseError("LLM yanıtı bir JSON nesnesi değil.")
    return data


def _repair_string_newlines(code: str, limit: int = 20) -> tuple[str, int]:
    """JSON'da `\\\\n` yerine `\\n` yazılınca string içindeki kaçış gerçek satır sonuna dönüşür
    ve kod "unterminated string literal" hatası verir. Hatalı satırın sonundaki satır sonunu
    tekrar `\\n` kaçışına çevirerek onarır. (onarılmış kod, onarım sayısı) döndürür."""
    repaired = 0
    while repaired < limit:
        try:
            ast.parse(code)
            break
        except SyntaxError as exc:
            lines = code.split("\n")
            if "unterminated" not in exc.msg or "triple" in exc.msg or not exc.lineno or exc.lineno >= len(lines):
                break
            i = exc.lineno - 1
            code = "\n".join([*lines[:i], lines[i] + "\\n" + lines[i + 1], *lines[i + 2:]])
            repaired += 1
    return code, repaired


def parse_response(text: str, original_code: str) -> dict:
    """LLM yanıtını doğrular ve normalize eder; kurallara uymuyorsa LLMResponseError fırlatır."""
    data = _load_json(text)
    warnings: list[str] = []

    green_code = data.get("green_code")
    if not isinstance(green_code, str) or not green_code.strip():
        keys = ", ".join(map(str, data)) or "hiçbiri"
        raise LLMResponseError(f"LLM yanıtında 'green_code' alanı yok veya boş (dönen alanlar: {keys}).")
    green_code, repaired = _repair_string_newlines(green_code)
    if repaired:
        warnings.append(f"Kodda JSON kaçışı bozuk {repaired} string onarıldı (\\n).")
    try:
        green_tree = ast.parse(green_code)
    except SyntaxError as exc:
        raise LLMResponseError(
            f"LLM'in ürettiği kod sözdizimi hatası içeriyor (satır {exc.lineno}): {exc.msg}"
        ) from exc

    original_fns = _function_nodes(ast.parse(original_code))
    green_fns = _function_nodes(green_tree)
    missing = [name for name in original_fns if name not in green_fns]
    if missing:
        raise LLMResponseError(f"Optimize edilmiş kodda şu fonksiyonlar eksik: {', '.join(missing)}")

    # Küçük modeller sık sık yalnızca parametre adlarını değiştirir (ör. desen örneğindeki
    # `nums`'ı kopyalar). Yapı aynıysa adları orijinaline geri çevir.
    for name, fn in original_fns.items():
        green_fn = green_fns[name]
        if _signature(green_fn) == _signature(fn) or _signature(green_fn, False) != _signature(fn, False):
            continue
        mapping = {
            g.arg: o.arg for g, o in zip(_all_params(green_fn), _all_params(fn)) if g.arg != o.arg
        }
        renamed = _rename_params(green_code, name, mapping)
        if renamed is not None:
            warnings.append(
                f"{name}: parametre adları orijinaline döndürüldü "
                f"({', '.join(f'{g} → {o}' for g, o in mapping.items())})."
            )
            green_code = renamed
            green_fns = _function_nodes(ast.parse(green_code))

    changed = [name for name, fn in original_fns.items() if _signature(green_fns[name]) != _signature(fn)]
    if changed:
        details = "; ".join(
            f"{_format_signature(n, original_fns[n])} olmalı, {_format_signature(n, green_fns[n])} yazılmış"
            for n in changed
        )
        raise LLMResponseError(f"Fonksiyon imzası değiştirilmiş: {details}")

    changes = data.get("changes") or []
    if not isinstance(changes, list):
        raise LLMResponseError("'changes' alanı bir liste olmalı.")
    changes = [
        {"pattern": str(c.get("pattern", "")), "explanation": str(c.get("explanation", ""))}
        for c in changes
        if isinstance(c, dict)
    ]

    test_inputs = data.get("test_inputs") or {}
    if not isinstance(test_inputs, dict):
        raise LLMResponseError("'test_inputs' alanı {fonksiyon_adı: [[argümanlar], ...]} biçiminde olmalı.")
    functions = _top_level_functions(ast.parse(original_code))
    for name in [n for n in test_inputs if n not in functions]:
        warnings.append(f"test_inputs içindeki '{name}' orijinal kodda üst seviye fonksiyon değil, atlandı.")
        del test_inputs[name]
    for name, cases in list(test_inputs.items()):
        if not isinstance(cases, list) or not all(isinstance(c, list) for c in cases):
            raise LLMResponseError(f"'test_inputs.{name}' bir argüman listeleri listesi olmalı.")
        params, minimum, maximum = _positional_arity(functions[name])
        # Küçük modeller sık sık [argümanlar..., beklenen_çıktı] yazar; beklenen çıktıya ihtiyaç yok
        # (orijinal kod çalıştırılarak hesaplanır), fazladan sondaki elemanlar atılır.
        trimmed = sum(1 for c in cases if maximum is not None and len(c) > maximum)
        if trimmed:
            cases = [c[:maximum] if maximum is not None else c for c in cases]
            warnings.append(
                f"{name} için {trimmed} test girdisindeki fazladan eleman (muhtemelen beklenen çıktı) atıldı."
            )
        valid = [c for c in cases if len(c) >= minimum]
        if not valid:
            raise LLMResponseError(
                f"'test_inputs.{name}' girdilerinin hiçbiri imzaya uymuyor: {name}({', '.join(params)}) "
                f"{minimum} argüman alır, her girdi [{', '.join(params)}] biçiminde olmalı."
            )
        if len(valid) < len(cases):
            warnings.append(f"{name} için imzaya uymayan {len(cases) - len(valid)} test girdisi atlandı.")
        test_inputs[name] = cases = valid
        if len(cases) < 4:
            warnings.append(f"{name} için yalnızca {len(cases)} test girdisi üretildi (en az 4 istendi).")
    for name in original_fns:
        if "." not in name and name not in test_inputs:
            warnings.append(f"{name} için test girdisi üretilmedi.")

    benchmark_input: dict[str, str] = {}
    raw_bench = data.get("benchmark_input") or {}
    if isinstance(raw_bench, dict):
        for name, expr in raw_bench.items():
            try:
                ast.parse(expr, mode="eval")
            except (SyntaxError, TypeError, ValueError):
                warnings.append(f"{name} için benchmark ifadesi geçersiz, atlandı.")
                continue
            benchmark_input[name] = expr
    else:
        warnings.append("'benchmark_input' bir sözlük değil, atlandı.")

    notes = data.get("notes")
    return {
        "green_code": green_code,
        "changes": changes,
        "test_inputs": test_inputs,
        "benchmark_input": benchmark_input,
        "notes": notes if isinstance(notes, str) else "",
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Genel API
# --------------------------------------------------------------------------- #

def optimize(
    code: str,
    findings: list[dict],
    patterns: list[dict],
    feedback: str | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict:
    """Kodu verilen desenlere göre LLM ile yeniden yazar.

    Dönüş: green_code, changes, test_inputs, benchmark_input, notes, warnings,
    provider, model alanlarını içeren sözlük.
    Hatalar: LLMUnavailableError (servis), LLMResponseError (geçersiz yanıt), LLMError (ayar).
    """
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise LLMError(f"Orijinal kod sözdizimi hatası içeriyor (satır {exc.lineno}): {exc.msg}") from exc

    provider = config.LLM_PROVIDER
    call = PROVIDERS.get(provider)
    if call is None:
        raise LLMError(f"Bilinmeyen LLM sağlayıcısı: {provider!r} (ollama|gemini olmalı)")

    prompt = build_prompt(code, findings, patterns, feedback)
    with _http_client(client) as http:
        raw = call(SYSTEM_PROMPT, prompt, http)

    result = parse_response(raw, code)
    result["provider"] = provider
    result["model"] = config.OLLAMA_MODEL if provider == "ollama" else config.GEMINI_MODEL
    return result
