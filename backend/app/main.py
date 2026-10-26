"""Eco-Code Profiler API."""

from __future__ import annotations

import ast
import logging
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import auth, config, db, energy, llm, rag, report
from .analyzer import analyze
from .patterns import IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM
from .verifier import verify

logger = logging.getLogger("uvicorn.error")

MAX_ATTEMPTS = 2  # ilk deneme + doğrulama başarısızsa 1 tekrar
CLEAN_MESSAGE = "Algoritmik enerji israfı tespit edilmedi"
FRONTEND_DIST = config.BASE_DIR.parent / "frontend" / "dist"
IMPACTS = (IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not auth.enabled():
        logger.warning("ADMIN_PASSWORD tanımlı değil: yönetici girişi ve desen düzenleme uçları KAPALI.")
    db.init_db()  # eksik tablo/sütunları oluştur, tabloda olmayan başlangıç desenlerini ekle (mevcutlara dokunmaz)
    yield


app = FastAPI(title="Eco-Code Profiler", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Şemalar
# --------------------------------------------------------------------------- #

class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100_000, description="Analiz edilecek Python kodu")


class OptimizeResponse(BaseModel):
    id: int | None = None
    status: Literal["clean", "optimized", "failed"]
    message: str
    analysis: dict[str, Any]
    analysis_after: dict[str, Any] | None = None
    green_code: str | None = None
    changes: list[dict[str, Any]] = []
    verification: dict[str, Any] | None = None
    # Ölçülen süre farkından varsayımlara dayalı TAHMİN (ölçüm değil); yalnızca doğrulanmış ve
    # daha hızlı sonuçlarda dolu.
    energy: dict[str, Any] | None = None
    notes: str = ""
    warnings: list[str] = []
    attempts: int = 0
    error: str | None = None


class PatternUpdate(BaseModel):
    anti_pattern: str = Field(max_length=5_000, description="Sorunun açıklaması")
    solution: str = Field(max_length=5_000)
    impact: str
    example_before: str = Field(max_length=10_000)
    example_after: str = Field(max_length=10_000)
    # Örneklerin eşdeğerlik kontrolü için {fonksiyon: [[argümanlar], ...]}; verilmezse kayıtlı girdiler.
    example_inputs: dict[str, list[list[Any]]] | None = None


class EnergyRequest(BaseModel):
    old_seconds: float | None
    new_seconds: float | None
    watts: float = Field(gt=0, le=100_000, description="İşlemci gücü varsayımı (W)")
    runs_per_day: float = Field(gt=0, le=1e12, description="Fonksiyonun günde kaç kez çalıştığı varsayımı")


class AdminLogin(BaseModel):
    password: str = Field(max_length=1_000)


class PatternActive(BaseModel):
    is_active: bool


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    original_code: str
    green_code: str | None
    findings: list[dict[str, Any]]
    old_seconds: float | None
    new_seconds: float | None
    speedup: float | None


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #

def _only_order_differs(old_repr: str | None, new_repr: str | None) -> bool:
    """İki sonuç aynı elemanları içerip yalnızca sırası mı farklı? (repr metinlerinden)"""
    try:
        old, new = ast.literal_eval(old_repr or ""), ast.literal_eval(new_repr or "")
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return False
    if not (isinstance(old, (list, tuple)) and isinstance(new, (list, tuple))) or old == new:
        return False
    try:
        return Counter(map(repr, old)) == Counter(map(repr, new))
    except TypeError:
        return False


def _unresolved_patterns(code: str, analysis: dict, green_code: str, catalog: dict) -> tuple[str, str] | None:
    """Önerilen kod tespit edilen desenlerin HİÇBİRİNİ gidermiyorsa (hata, LLM geri bildirimi).

    Değişmemiş kod kendisiyle doğal olarak eşdeğer olduğundan doğrulamadan geçer; bu kontrol
    olmadan "optimize edildi" sayılırdı. Bir desenin bulgu sayısı azaldıysa ilerleme vardır
    (ör. iki YK-02'den biri giderildi). İlerleme varsa None.
    """
    if report.normalize_code(green_code) == report.normalize_code(code):
        return (
            "Önerilen kod orijinalle aynı (yalnızca boşluk/biçim farkı); hiçbir desen uygulanmadı.",
            "Önceki yanıtında gönderdiğin kod orijinal kodla AYNI; hiçbir değişiklik yapmadın. Orijinal "
            "kodu aynen döndürme. Tespit edilen desenleri onaylı çözümlerine göre uygula:\n"
            + "\n".join(f"- Satır {f['line']}: {f['pattern_code']} {f['title']}" for f in analysis["findings"]),
        )
    before = Counter(f["pattern_code"] for f in analysis["findings"])
    after_findings = analyze(green_code, catalog)["findings"]
    after = Counter(f["pattern_code"] for f in after_findings)
    if any(after[c] < n for c, n in before.items()):
        return None
    lines = green_code.splitlines()
    remaining = [f for f in after_findings if f["pattern_code"] in before]
    details = [
        f"- {f['pattern_code']} {f['title']} — satır {f['line']}: `{lines[f['line'] - 1].strip()}`"
        if 0 < f["line"] <= len(lines) else f"- {f['pattern_code']} {f['title']} — satır {f['line']}"
        for f in remaining
    ]
    codes = ", ".join(sorted(before))
    return (
        f"Önerilen kod tespit edilen desenlerin hiçbirini gidermiyor; hâlâ {codes} içeriyor.",
        "Önceki kodun tespit edilen desenlerin HİÇBİRİNİ gidermedi. Kodun hâlâ şunları içeriyor:\n"
        + "\n".join(details)
        + "\nBu desenleri onaylı çözümlerine göre uygula; davranışı (çıktı ve sırası dahil) koru.",
    )


def _uses(code: str | None) -> set[str]:
    """Önerilen kodda sırayı bozabilecek yapılar: {"set", "heapq"}."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Set, ast.SetComp)) or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("set", "frozenset")
        ):
            found.add("set")
        elif (isinstance(node, ast.Name) and node.id == "heapq") or (
            isinstance(node, ast.ImportFrom) and node.module == "heapq"
        ):
            found.add("heapq")
    return found


def _is_sorted_repr(value: str | None) -> bool:
    try:
        items = ast.literal_eval(value or "")
        return isinstance(items, (list, tuple)) and len(items) > 1 and list(items) == sorted(items)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False


def _literal(value: str | None):
    try:
        return ast.literal_eval(value or "")
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


ORDER_RULES = {  # ad -> bir elemanın girdi listesinde kaçıncı görülüşünün konumu
    "ilk görülme": lambda positions: positions[0],
    "ikinci görülme": lambda positions: positions[1] if len(positions) > 1 else None,
    "son görülme": lambda positions: positions[-1],
}


def _tr_upper(text: str) -> str:
    """Türkçe büyük harf (i → İ, ı → I)."""
    return text.replace("i", "İ").replace("ı", "I").upper()


def _order_rule(examples: list[tuple[list, list]]) -> str | None:
    """Sonuç listesi, elemanları girdideki hangi görülüşlerine göre sıralıyor? Bütün örneklerde
    tutarlı tek bir kural varsa adını döndürür. examples: (girdi listesi, sonuç listesi)."""
    found = None
    for name, pick in ORDER_RULES.items():
        informative = False
        for source, result in examples:
            try:
                positions = {}
                for i, x in enumerate(source):
                    positions.setdefault(repr(x), []).append(i)
                keys = [pick(positions[repr(x)]) if repr(x) in positions else None for x in result]
            except TypeError:
                keys = [None]
            if None in keys or len(set(keys)) != len(keys):
                break
            if keys != sorted(keys):
                break
            # Kurallar bu örnekte farklı sıra veriyorsa örnek ayırt edicidir.
            informative = informative or len(result) > 1
        else:
            if informative:
                if found is not None:
                    return None  # birden çok kural uyuyor: belirsiz
                found = name
    return found


def _order_examples(cases: list[dict], key: str) -> list[tuple[list, list]]:
    """Başarısız durumlardan (ve en küçük karşı örneklerden) (girdi listesi, sonuç) çiftleri."""
    examples = []
    for case in cases:
        for source in (case, case.get("minimal") or {}):
            args, result = _literal(source.get("input")), _literal(source.get(key))
            if not (isinstance(args, (list, tuple)) and isinstance(result, (list, tuple)) and len(result) > 1):
                continue
            lists = [a for a in args if isinstance(a, (list, tuple))]
            if len(lists) == 1:  # tek liste argümanlı fonksiyonlarda sıra kuralı anlamlı
                examples.append((list(lists[0]), list(result)))
    return examples


def _order_hint(failing: list[dict], green_code: str | None) -> str:
    """Yalnızca sırası farklı sonuçlar için ipucu: orijinal ve önerilen kodun sırası veriden tarif edilir,
    önerilen kodda set/heapq varsa onlara özel uyarı eklenir."""
    hint = ["ÖNEMLİ: Sonuçların elemanları doğru ama SIRASI farklı."]
    original = _order_rule(_order_examples(failing, "old"))
    proposed = _order_rule(_order_examples(failing, "new"))
    if original:
        example = next((c["minimal"] for c in failing if c.get("minimal")), None) or failing[0]
        line = (f"Orijinal kod elemanları girdideki {_tr_upper(original)} SIRASINA göre döndürüyor "
                f"(ör. girdi {example['input']} → {example['old']})")
        if proposed and proposed != original:
            line += f"; senin kodun ise {proposed} sırasına göre döndürüyor ({example['new']})"
        hint.append(line + ".")
        if original == "ilk görülme":
            hint.append(
                "Sonucu, girdiyi baştan dolaşarak ve her elemanı ilk görüldüğü yerde ekleyerek üret; bir elemanın "
                "eklenip eklenmeyeceğine önceden hesaplanmış bilgiyle karar ver (ör. önce collections.Counter ile say, "
                "sonra ikinci bir döngüde ilk görülüşte ekle)."
            )
    used = _uses(green_code)
    if "heapq" in used:
        hint.append(
            "heapq listeyi sıralı TUTMAZ; yalnızca en küçük eleman başta durur (heap[0]), geri kalanın sırası "
            "tanımsızdır. Heap'i doğrudan döndürme/dilimleme; sonucu sorted(...) ile döndür. Sıralı veri yalnızca "
            "döngü bittikten sonra gerekiyorsa heap yerine sıralamayı döngüden sonra bir kez yap."
        )
    if "set" in used:
        hint.append(
            "set'in dolaşma sırası tanımsızdır; sonucu set'ten üretme. Orijinalin sırasını (ör. ilk görülme "
            "sırası) korumak için dict, collections.Counter veya ekleme sırasıyla doldurulan bir liste kullan."
        )
    # Yalnızca bütün durumlarda sıralıysa söylenir: küçük bir örneğin tesadüfen sıralı olması
    # ([1, 2]) modeli yanlışlıkla sıralamaya itiyordu.
    olds = [c.get("old") for c in failing if isinstance(_literal(c.get("old")), (list, tuple)) and len(_literal(c.get("old"))) > 1]
    if olds and all(_is_sorted_repr(o) for o in olds) and not original:
        hint.append("Orijinal kodun sonucu ARTAN SIRADA; seninki de aynı sırada olmalı.")
    if len(hint) == 1:
        hint.append("Orijinal kodun çıktı sırasını (ör. ekleme veya ilk görülme sırası) birebir koru.")
    return " ".join(hint)


def _multiplicity_lost(old_repr: str | None, new_repr: str | None) -> bool:
    """Yeni sonuç orijinalle aynı farklı elemanları içeriyor ama bazılarının TEKRAR SAYISI eksik mi?

    (Yeni sonucun eleman sayımı orijinalinkinin alt kümesi.) Tipik neden: her eşleşme için eleman
    ekleyen iç döngünün set/`in`/`if counts[x]` ile yalnızca var/yok kontrolüne çevrilmesi.
    """
    try:
        old, new = ast.literal_eval(old_repr or ""), ast.literal_eval(new_repr or "")
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return False
    if not (isinstance(old, (list, tuple)) and isinstance(new, (list, tuple))):
        return False
    try:
        old_counts, new_counts = Counter(map(repr, old)), Counter(map(repr, new))
    except TypeError:
        return False
    return (
        old_counts != new_counts
        and set(old_counts) == set(new_counts)
        and all(new_counts[k] <= n for k, n in old_counts.items())
    )


def _multiplicity_hint(cases: list[dict]) -> str:
    example = next(
        (c["minimal"] | {"function": c["function"]} for c in cases
         if c.get("minimal") and _multiplicity_lost(c["minimal"]["old"], c["minimal"]["new"])),
        cases[0],
    )
    return (
        "ÖNEMLİ: Sonuçta doğru elemanlar var ama TEKRAR SAYILARI eksik (ör. "
        f"{example['function']}(*{example['input']}) için orijinal {example['old']}, seninki {example['new']}). "
        "Orijinal kod her eşleşme için bir eleman ekliyor (tekrarlar korunuyor); yalnızca var/yok kontrolü "
        "(set, `in`, `if counts[x]`) tekrarları kaybeder. Eşleşme sayısını koru: collections.Counter ile say "
        "ve her eleman için sayısı kadar ekle (ör. result.extend([x] * counts[x]))."
    )


def _slower_than_original(verification: dict) -> tuple[str, str] | None:
    """Doğru ama ölçümde eski koddan YAVAŞ çıkan kod optimizasyon sayılmaz: (hata, geri bildirim).

    Eşdeğerlik testi yalnızca doğruluğu gösterir; "optimize edildi" denebilmesi için ölçülen
    hızlanma en az 1× olmalı. Ölçüm yoksa (None) burada karar verilmez.
    """
    bench = verification.get("benchmark") or {}
    speedup = bench.get("speedup")
    if speedup is None or speedup >= 1.0:
        return None
    old, new = bench.get("old_seconds"), bench.get("new_seconds")
    return (
        f"Önerilen kod doğru ama ölçümde eski koddan yavaş ({speedup:.2f}×); optimizasyon sayılmadı.",
        f"Önceki kodun doğru (eşdeğerlik testini geçti) ama ölçümde eski koddan YAVAŞ: {speedup:.2f}× "
        f"(eski {old:.6f} sn, yeni {new:.6f} sn). Gereksiz dönüşüm/kopya (ör. her çağrıda yeni veri "
        "yapısı kurmak) ek yük getiriyor olabilir. Daha hızlı bir çözüm üret; desen bu kodda kazanç "
        "sağlamıyorsa notes alanında açıkla.",
    )


def _verification_feedback(verification: dict, green_code: str | None = None) -> str:
    """Başarısız doğrulamayı LLM'e geri bildirim olarak özetler."""
    lines = ["Önceki optimize edilmiş kod doğrulamadan GEÇEMEDİ."]
    if verification.get("error"):
        lines.append(f"Hata: {verification['error']}")
    for case in verification.get("cases", []):
        if case.get("minimal"):
            mini = case["minimal"]
            lines.append(
                f"EN KÜÇÜK KARŞI ÖRNEK: {case['function']}(*{mini['input']}) için orijinal kod "
                f"{mini['old']} döndürüyor, senin kodun {mini['new']} döndürüyor. Kodunu bu örnek "
                "üzerinde adım adım izleyerek düzelt."
            )
    side_effects = [c for c in verification.get("cases", []) if c.get("side_effect")]
    for case in side_effects[:2]:
        for change in case["side_effect"]:
            lines.append(
                f"YAN ETKİ FARKI: {case['function']}(*{case['input']}) çağrısından sonra orijinal kod "
                f"`{change['name']}` argümanını {change['old']} hâline getiriyor, senin kodun {change['new']} "
                f"bırakıyor (çağrıdan önce {change['before']}). Dönüş değerin doğru; `{change['name']}` "
                "argümanını da orijinal kodla aynı şekilde değiştir (bu yan etkiyi koru)."
            )
    for case in [c for c in verification.get("cases", []) if not c.get("equal") and not c.get("side_effect")][:5]:
        line = (
            f"- {case['function']}(*{case['input']}): beklenen (orijinal) {case.get('old')}, "
            f"senin kodun {case.get('new')}"
        )
        if case.get("note"):
            line += f" ({case['note']})"
        lines.append(line)
    for entry in ((verification.get("benchmark") or {}).get("functions") or [])[:3]:
        if entry.get("error"):
            lines.append(f"- Benchmark ({entry['function']}): {entry['error']}")
        elif entry.get("outputs_equal") is False:
            lines.append(f"- Benchmark ({entry['function']}): büyük girdide sonuçlar orijinalden farklı.")
    failing = [c for c in verification.get("cases", []) if not c.get("equal")]
    order_only = [c for c in failing if _only_order_differs(c.get("old"), c.get("new"))]
    if order_only:
        lines.append(_order_hint(order_only, green_code))
    fewer_repeats = [c for c in failing if _multiplicity_lost(c.get("old"), c.get("new"))]
    if fewer_repeats:
        lines.append(_multiplicity_hint(fewer_repeats))
    lines.append("Davranışı (çıktı sırası ve hata tipleri dahil) orijinalle birebir aynı tut.")
    return "\n".join(lines)


def _get_pattern(session: Session, code: str) -> db.GreenPattern:
    pattern = session.get(db.GreenPattern, code)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"{code} kodlu desen bulunamadı.")
    return pattern


def _validate_pattern_update(req: PatternUpdate) -> None:
    """Geçersiz düzenlemede 400 döndürür (LLM'e bozuk desen gönderilmesin)."""
    if req.impact not in IMPACTS:
        raise HTTPException(status_code=400, detail=f"Geçersiz etki düzeyi: {req.impact!r} ({' | '.join(IMPACTS)} olmalı).")
    labels = {"anti_pattern": "Sorun açıklaması", "solution": "Çözüm",
              "example_before": "Önce örneği", "example_after": "Sonra örneği"}
    for field, label in labels.items():
        if not getattr(req, field).strip():
            raise HTTPException(status_code=400, detail=f"{label} boş olamaz.")
    for field in ("example_before", "example_after"):
        try:
            ast.parse(getattr(req, field))
        except SyntaxError as exc:
            raise HTTPException(
                status_code=400, detail=f"{labels[field]} geçerli Python değil (satır {exc.lineno}): {exc.msg}"
            ) from exc


EXAMPLE_CHECK_TIMEOUT = 20


def _check_examples_equivalent(before: str, after: str, inputs: dict | None) -> None:
    """'Sonra' örneği 'önce' ile aynı davranmıyorsa 400 (dönüş değeri, hata tipi, argüman yan etkisi).

    Modeller onaylı örnekleri birebir kopyaladığı için eşdeğer olmayan bir örnek LLM'i sistematik
    olarak yanlış koda yönlendirir. patterns.py'deki örnekleri aynı kontrolle test eden:
    tests/test_patterns_db_rag.py::test_examples_are_equivalent.
    """
    if not inputs:
        raise HTTPException(status_code=400, detail=(
            "Örneklerin eşdeğerliğini doğrulamak için test girdileri gerekli: "
            '{"fonksiyon_adı": [[argümanlar], ...]}'))
    functions = {n.name for n in ast.parse(before).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    unknown = sorted(set(inputs) - functions)
    if unknown:
        raise HTTPException(status_code=400, detail=(
            f"Test girdilerindeki fonksiyon(lar) 'önce' örneğinde yok: {', '.join(unknown)} "
            f"(örnekteki fonksiyonlar: {', '.join(sorted(functions)) or 'yok'})."))
    if not any(inputs.values()):
        raise HTTPException(status_code=400, detail="En az bir test girdisi gerekli.")

    result = verify(before, after, inputs, measure=False, timeout=EXAMPLE_CHECK_TIMEOUT)
    if result["passed"]:
        return
    failing = [c for c in result["cases"] if not c.get("equal")]
    case = failing[0] if failing else None
    if case is None or case.get("side_effect"):
        reason = result.get("error") or "doğrulama tamamlanamadı."
    elif case.get("old") is None:
        reason = case.get("note") or result.get("error") or "test girdisi çalıştırılamadı."
    else:
        derived = f" (sistemin türettiği {case['derived']} girdi)" if case.get("derived") else ""
        reason = f"{case['function']}(*{case['input']}){derived} için önce {case['old']}, sonra {case['new']}."
    raise HTTPException(status_code=400, detail=f"'Sonra' örneği 'önce' örneğiyle eşdeğer değil: {reason}")


def _save_run(session: Session, code: str, response: OptimizeResponse) -> OptimizeResponse:
    bench = (response.verification or {}).get("benchmark") or {}
    run = db.AnalysisRun(
        original_code=code,
        green_code=response.green_code,
        findings=response.analysis.get("findings", []),
        status=response.status,
        old_seconds=bench.get("old_seconds"),
        new_seconds=bench.get("new_seconds"),
        speedup=bench.get("speedup"),
    )
    session.add(run)
    session.commit()
    response.id = run.id
    return response


# --------------------------------------------------------------------------- #
# Uç noktalar
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health(session: Session = Depends(db.get_session)) -> dict:
    try:
        session.execute(text("SELECT 1"))
        database = {"ok": True, "dialect": session.get_bind().dialect.name, "message": "Bağlantı başarılı."}
    except Exception as exc:  # sağlık kontrolü asla 500 dönmemeli
        database = {"ok": False, "dialect": None, "message": f"{type(exc).__name__}: {exc}"[:300]}
    llm_status = llm.health_check()
    return {
        "status": "ok" if database["ok"] and llm_status["reachable"] else "degraded",
        "database": database,
        "llm": llm_status,
    }


@app.get("/api/patterns")
def patterns(session: Session = Depends(db.get_session)) -> list[dict]:
    rows = session.scalars(select(db.GreenPattern).order_by(db.GreenPattern.code)).all()
    return [row.to_api_dict() for row in rows]


@app.get("/api/admin/status")
def admin_status() -> dict:
    return {"enabled": auth.enabled()}


@app.post("/api/admin/login")
def admin_login(req: AdminLogin) -> dict:
    return auth.login(req.password)


@app.post("/api/admin/logout", status_code=204)
def admin_logout(authorization: str | None = Header(default=None)) -> None:
    auth.logout(auth.bearer_token(authorization))


@app.put("/api/patterns/{code}")
def update_pattern(
    code: str,
    req: PatternUpdate,
    session: Session = Depends(db.get_session),
    user: str = Depends(auth.require_admin),
) -> dict:
    pattern = _get_pattern(session, code)
    _validate_pattern_update(req)
    inputs = req.example_inputs if req.example_inputs is not None else pattern.example_inputs
    examples_changed = (
        req.example_before != pattern.example_before
        or req.example_after != pattern.example_after
        or inputs != pattern.example_inputs
    )
    if examples_changed:  # yalnızca metin/etki düzenlemelerinde alt süreç çalıştırılmaz
        _check_examples_equivalent(req.example_before, req.example_after, inputs)
    pattern.example_inputs = inputs
    pattern.updated_by = user
    pattern.anti_pattern = req.anti_pattern.strip()
    pattern.solution = req.solution.strip()
    pattern.impact = req.impact
    pattern.example_before = req.example_before
    pattern.example_after = req.example_after
    session.commit()
    return pattern.to_api_dict()


@app.patch("/api/patterns/{code}/active")
def set_pattern_active(
    code: str,
    req: PatternActive,
    session: Session = Depends(db.get_session),
    user: str = Depends(auth.require_admin),
) -> dict:
    pattern = _get_pattern(session, code)
    pattern.is_active = req.is_active
    pattern.updated_by = user
    session.commit()
    return pattern.to_api_dict()


@app.post("/api/analyze")
def analyze_code(req: CodeRequest, session: Session = Depends(db.get_session)) -> dict:
    return analyze(req.code, db.load_catalog(session))


@app.post("/api/optimize", response_model=OptimizeResponse)
def optimize_code(req: CodeRequest, session: Session = Depends(db.get_session)) -> OptimizeResponse:
    code = req.code
    catalog = db.load_catalog(session)
    analysis = analyze(code, catalog)

    if analysis["syntax_error"]:
        err = analysis["syntax_error"]
        return OptimizeResponse(
            status="failed",
            message="Kod sözdizimi hatası içeriyor; optimizasyon yapılmadı.",
            analysis=analysis,
            error=f"Satır {err['line']}: {err['message']}",
        )

    findings = analysis["findings"]
    if not findings:
        return _save_run(session, code, OptimizeResponse(status="clean", message=CLEAN_MESSAGE, analysis=analysis))

    patterns = rag.retrieve([f["pattern_code"] for f in findings], session=session)

    result: dict | None = None
    verification: dict | None = None
    feedback: str | None = None
    error: str | None = None
    attempts = 0

    accepted = False  # doğrulandı VE (ölçüldüyse) eski koddan yavaş değil
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        try:
            candidate = llm.optimize(code, findings, patterns, feedback)
        except llm.LLMResponseError as exc:
            error = str(exc)
            feedback = f"Önceki yanıtın geçersizdi: {exc}. Kurallara uyan geçerli JSON döndür."
            continue
        except llm.LLMError as exc:  # servise ulaşılamıyor / ayar hatası: tekrar denemek anlamsız
            error = str(exc)
            break

        result = candidate
        unresolved = _unresolved_patterns(code, analysis, candidate["green_code"], catalog)
        if unresolved:  # değişmemiş kod doğrulamadan geçer ama optimizasyon değildir: alt süreç çalıştırılmaz
            error, feedback = unresolved
            verification = None
            continue
        verification = verify(code, candidate["green_code"], candidate["test_inputs"], candidate["benchmark_input"])
        if verification["passed"]:
            slower = _slower_than_original(verification)
            if slower is None:
                accepted, error = True, None
                break
            error, feedback = slower
            continue
        error = verification.get("error") or "Optimize edilmiş kod orijinalle aynı sonuçları vermedi."
        feedback = _verification_feedback(verification, candidate["green_code"])

    passed = accepted
    green_code = result["green_code"] if result else None
    bench = (verification or {}).get("benchmark") or {}
    response = OptimizeResponse(
        status="optimized" if passed else "failed",
        message=(
            "Kod optimize edildi ve davranışın korunduğu doğrulandı."
            if passed
            else "Doğrulanmış bir optimizasyon üretilemedi; orijinal kodu kullanmaya devam edin."
        ),
        analysis=analysis,
        analysis_after=analyze(green_code, catalog) if green_code else None,
        green_code=green_code,
        changes=result["changes"] if result else [],
        verification=verification,
        energy=energy.estimate(bench.get("old_seconds"), bench.get("new_seconds")) if passed else None,
        notes=result["notes"] if result else "",
        warnings=result["warnings"] if result else [],
        attempts=attempts,
        error=error,
    )
    return _save_run(session, code, response)


@app.post("/api/energy/estimate")
def energy_estimate(req: EnergyRequest) -> dict:
    """Arayüzde varsayımlar değiştirildiğinde tahmini yeniden hesaplar (formül tek yerde: energy.py)."""
    return {"estimate": energy.estimate(req.old_seconds, req.new_seconds, req.watts, req.runs_per_day)}


@app.get("/api/report")
def get_report(session: Session = Depends(db.get_session)) -> dict:
    return report.build_report(session)


@app.get("/api/history", response_model=list[HistoryItem])
def history(session: Session = Depends(db.get_session)) -> list[db.AnalysisRun]:
    stmt = select(db.AnalysisRun).order_by(db.AnalysisRun.created_at.desc(), db.AnalysisRun.id.desc()).limit(20)
    return list(session.scalars(stmt))


# Derlenmiş frontend varsa kökten sun (API rotalarından SONRA bağlanmalı).
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
