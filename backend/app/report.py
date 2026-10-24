"""Kurum geneli rapor: analysis_runs tablosundaki gerçek kayıtlardan özet istatistikler.

Durumlar, bulgular ve süreler kaydedilmiş gerçek verilerdir. Tek istisna `savings.energy`:
ölçülen süre farklarından varsayımlara dayalı TAHMİNİ yıllık enerji tasarrufudur (energy.py).

Tekrarlanan kodlar: aynı orijinal kod (boşluk/satır sonu farkları normalize edilerek) birden
çok kez analiz edildiyse, toplamlarda (süre kazancı, enerji, hızlanma, desen sıklığı, en çok
kazanç tablosu) yalnızca o kodun EN SON başarılı (optimized) analizi sayılır. Toplam analiz
sayısı ve doğrulama başarı oranı tüm çalıştırmaları sayar.
"""

from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from collections import Counter
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, energy
from .db import AnalysisRun, iso_utc, load_catalog

STATUSES = ("optimized", "clean", "failed")
TOP_RUNS = 5
# Hızlanma grupları desen KODUNA göre sabittir (arayüzden düzenlenen etki düzeyinden bağımsız).
HIGH_IMPACT_CODES = ("YK-01", "YK-02", "YK-05", "YK-06", "YK-07", "YK-08")
LOW_IMPACT_CODES = ("YK-03", "YK-04", "YK-09", "YK-10")
# Bir grupta bu kadar veya daha az benzersiz kod varsa medyan yerine değerler tek tek verilir
# (2 değerin medyanı ortalamadır ve hiçbir analizi temsil etmeyebilir).
MAX_LISTED = 3

_INNER_WHITESPACE = re.compile(r"[ \t]+")


def normalize_code(code: str) -> str:
    """Boşluk/satır sonu farklarını yok sayan karşılaştırma biçimi.

    Satır sonları birleştirilir, sekmeler 4 boşluğa açılır, satır sonu boşlukları ve boş
    satırlar atılır, ortak girinti kaldırılır, satır içindeki boşluk dizileri teke indirilir.
    Satır başı girintisi KORUNUR (Python'da girinti anlamı değiştirir).
    """
    lines = [line.expandtabs(4).rstrip() for line in code.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = textwrap.dedent("\n".join(line for line in lines if line))
    out = []
    for line in text.split("\n"):
        body = line.lstrip(" ")
        out.append(line[: len(line) - len(body)] + _INNER_WHITESPACE.sub(" ", body))
    return "\n".join(out)


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def _latest(runs: list[AnalysisRun]) -> AnalysisRun:
    return max(runs, key=lambda r: (r.created_at, r.id))


def _pattern_codes(run: AnalysisRun) -> set[str]:
    return {f.get("pattern_code") for f in run.findings or [] if f.get("pattern_code")}


def code_label(run: AnalysisRun) -> str:
    """Kodun üst seviye fonksiyon/sınıf adları (ör. "find_pair"); bulunamazsa "analiz #id"."""
    try:
        tree = ast.parse(run.original_code)
    except (SyntaxError, ValueError):
        return f"analiz #{run.id}"
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return ", ".join(names) if names else f"analiz #{run.id}"


def _speedup_group_summary(codes: tuple[str, ...], runs: list[AnalysisRun]) -> dict:
    speedups = [run.speedup for run in runs]
    listed = len(runs) <= MAX_LISTED
    return {
        "codes": list(codes),
        "runs": len(runs),
        "median_speedup": median(speedups) if speedups else 0.0,
        # Az kayıtta medyan yerine tek tek değerler (en yüksekten), arayüz bunları gösterir.
        "items": sorted(
            ({"label": code_label(run), "speedup": run.speedup} for run in runs),
            key=lambda item: -item["speedup"],
        ) if listed else [],
    }


def speedup_group(run: AnalysisRun) -> str | None:
    """'high': en az bir yüksek etkili desen içerir; 'low': yalnızca düşük etkili desenler."""
    codes = _pattern_codes(run)
    if codes & set(HIGH_IMPACT_CODES):
        return "high"
    if codes and codes <= set(LOW_IMPACT_CODES):
        return "low"
    return None


def _run_summary(run: AnalysisRun, gain: float) -> dict:
    """Geçmiş kaydıyla aynı alanlar (arayüz "Editöre yükle" için) + süre kazancı."""
    return {
        "id": run.id,
        "created_at": iso_utc(run.created_at),
        "status": run.status,
        "original_code": run.original_code,
        "green_code": run.green_code,
        "findings": run.findings or [],
        "old_seconds": run.old_seconds,
        "new_seconds": run.new_seconds,
        "speedup": run.speedup,
        "gain_seconds": gain,
    }


def build_report(session: Session) -> dict:
    runs = session.scalars(select(AnalysisRun)).all()

    # Tüm çalıştırmalar: toplam analiz ve başarı oranı.
    status_counts = Counter(run.status for run in runs)
    counts = {status: status_counts.get(status, 0) for status in STATUSES}
    attempted = counts["optimized"] + counts["failed"]

    # Kod başına tek temsilci: en son başarılı analiz; hiç başarılı analizi olmayan kodlar için
    # (yalnızca desen sıklığında) en son analiz.
    by_code: dict[str, list[AnalysisRun]] = {}
    for run in runs:
        by_code.setdefault(code_hash(run.original_code), []).append(run)
    representative: list[AnalysisRun] = []
    successes: list[AnalysisRun] = []
    for code_runs in by_code.values():
        optimized = [r for r in code_runs if r.status == "optimized"]
        chosen = _latest(optimized or code_runs)
        representative.append(chosen)
        if optimized:
            successes.append(chosen)

    # Desen sıklığı: temsilci analizlerdeki tespit sayısı ve desenin görüldüğü benzersiz kod sayısı.
    occurrences: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    stored_titles: dict[str, str] = {}
    for run in representative:
        found = [f.get("pattern_code") for f in run.findings or [] if f.get("pattern_code")]
        occurrences.update(found)
        code_counts.update(set(found))
        for f in run.findings or []:
            stored_titles.setdefault(f.get("pattern_code"), f.get("title"))
    catalog = load_catalog(session)
    patterns = [
        {
            "code": code,
            "title": (catalog.get(code) or {}).get("title") or stored_titles.get(code) or code,
            "count": count,
            "runs": code_counts[code],
        }
        for code, count in sorted(occurrences.items(), key=lambda item: (-item[1], item[0]))
    ]

    # Süre kazancı: her kodun en son başarılı analizi, iki süresi de ölçülmüşse.
    measured = [run for run in successes if run.old_seconds is not None and run.new_seconds is not None]
    gains = [(run, run.old_seconds - run.new_seconds) for run in measured]
    estimates = [e for run in measured if (e := energy.estimate(run.old_seconds, run.new_seconds))]
    top = sorted((g for g in gains if g[1] > 0), key=lambda g: g[1], reverse=True)[:TOP_RUNS]

    groups: dict[str, list[AnalysisRun]] = {"high": [], "low": []}
    for run in measured:
        group = speedup_group(run)
        if group and run.speedup is not None:
            groups[group].append(run)

    return {
        "total_runs": len(runs),
        "unique_codes": len(by_code),
        "status_counts": counts,
        "success_rate": counts["optimized"] / attempted if attempted else 0.0,
        "patterns": patterns,
        "savings": {
            "measured_runs": len(measured),
            "total_seconds": sum(gain for _, gain in gains),
            "median_seconds": median(gain for _, gain in gains) if gains else 0.0,
            # Hızlanmalar iki kümeye ayrıldığından tek medyan yerine grup başına medyan.
            "speedup_groups": {
                "high": _speedup_group_summary(HIGH_IMPACT_CODES, groups["high"]),
                "low": _speedup_group_summary(LOW_IMPACT_CODES, groups["low"]),
            },
            # TAHMİN: her benzersiz kodun en son başarılı ve hızlanmış optimizasyonu için hesaplanıp toplanır.
            "energy": {
                "estimated_runs": len(estimates),
                "total_kwh_per_year": sum(e["kwh_per_year"] for e in estimates),
                "watts": config.CPU_POWER_WATTS,
                "runs_per_day": config.RUNS_PER_DAY,
            },
        },
        "top_runs": [_run_summary(run, gain) for run, gain in top],
    }
