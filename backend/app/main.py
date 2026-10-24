"""Eco-Code Profiler API."""

from __future__ import annotations

import ast
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import config, db, energy, llm, rag, report
from .analyzer import analyze
from .patterns import IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM
from .verifier import verify

MAX_ATTEMPTS = 2  # ilk deneme + doğrulama başarısızsa 1 tekrar
CLEAN_MESSAGE = "Algoritmik enerji israfı tespit edilmedi"
FRONTEND_DIST = config.BASE_DIR.parent / "frontend" / "dist"
IMPACTS = (IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW)


@asynccontextmanager
async def lifespan(app: FastAPI):
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


class EnergyRequest(BaseModel):
    old_seconds: float | None
    new_seconds: float | None
    watts: float = Field(gt=0, le=100_000, description="İşlemci gücü varsayımı (W)")
    runs_per_day: float = Field(gt=0, le=1e12, description="Fonksiyonun günde kaç kez çalıştığı varsayımı")


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


def _verification_feedback(verification: dict) -> str:
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
    for case in [c for c in verification.get("cases", []) if not c.get("equal")][:5]:
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
    if any(_only_order_differs(c.get("old"), c.get("new")) for c in failing):
        lines.append(
            "ÖNEMLİ: Sonuçların elemanları doğru ama SIRASI farklı. set'in dolaşma sırası tanımsızdır; "
            "sonucu set'ten üretme. Orijinalin sırasını (ör. ilk görülme sırası) korumak için dict, "
            "collections.Counter veya ekleme sırasıyla doldurulan bir liste kullan."
        )
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


@app.put("/api/patterns/{code}")
def update_pattern(code: str, req: PatternUpdate, session: Session = Depends(db.get_session)) -> dict:
    pattern = _get_pattern(session, code)
    _validate_pattern_update(req)
    pattern.anti_pattern = req.anti_pattern.strip()
    pattern.solution = req.solution.strip()
    pattern.impact = req.impact
    pattern.example_before = req.example_before
    pattern.example_after = req.example_after
    session.commit()
    return pattern.to_api_dict()


@app.patch("/api/patterns/{code}/active")
def set_pattern_active(code: str, req: PatternActive, session: Session = Depends(db.get_session)) -> dict:
    pattern = _get_pattern(session, code)
    pattern.is_active = req.is_active
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
        verification = verify(code, candidate["green_code"], candidate["test_inputs"], candidate["benchmark_input"])
        if verification["passed"]:
            error = None
            break
        error = verification.get("error") or "Optimize edilmiş kod orijinalle aynı sonuçları vermedi."
        feedback = _verification_feedback(verification)

    passed = bool(verification and verification["passed"])
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
