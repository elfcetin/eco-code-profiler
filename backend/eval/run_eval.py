"""Değerlendirme setini gerçek LLM ile çalıştırır ve sonuç tablosu üretir.

Kullanım (backend klasöründen, Ollama çalışırken):
    .venv/bin/python eval/run_eval.py --runs 3
    .venv/bin/python eval/run_eval.py --runs 1 --only normalize,rotate_left

- Uygulamanın gerçek /api/optimize akışı kullanılır (analiz, RAG, LLM, tekrar, doğrulama).
- AYRI ve geçici bir SQLite veritabanı kullanılır; kullanıcının geçmişi/raporu etkilenmez.
  Desenler patterns.py'deki başlangıç hâlinden gelir.
- Her "optimized" sonucu gizli testlerle (cases.py) bağımsız olarak denetlenir:
  doğrulayıcının geçirdiği ama gizli testlerin yakaladığı sonuç = YANLIŞ ONAY.
- Sonuçlar eval/results/ altına JSON (her çalıştırma) ve Markdown (özet) olarak yazılır.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # backend/

# Uygulama modülleri içe aktarılmadan ÖNCE geçici veritabanına yönlendir.
_TMP = tempfile.mkdtemp(prefix="eco_eval_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/eval.db"

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402
from app.verifier import verify  # noqa: E402
from cases import CASES  # noqa: E402

HIDDEN_TIMEOUT = 120


def hidden_check(case: dict, green_code: str) -> tuple[bool, str | None]:
    result = verify(case["code"], green_code, case["hidden"], measure=False, timeout=HIDDEN_TIMEOUT)
    if result["passed"]:
        return True, None
    bad = next((c for c in result["cases"] if not c.get("equal")), None)
    if bad is None:
        return False, result.get("error")
    detail = f"{bad['function']}(*{bad['input'][:120]}): önce {str(bad.get('old'))[:80]}, sonra {str(bad.get('new'))[:80]}"
    return False, (bad.get("note") + " " if bad.get("note") else "") + detail


def run_one(client: TestClient, case: dict) -> dict:
    started = time.perf_counter()
    resp = client.post("/api/optimize", json={"code": case["code"]})
    seconds = time.perf_counter() - started
    body = resp.json()
    found = sorted({f["pattern_code"] for f in body.get("analysis", {}).get("findings", [])})
    record = {
        "id": case["id"],
        "expected": case["expected"],
        "detected": found,
        "detected_expected": all(p in found for p in case["expected"]),
        "status": body.get("status"),
        "attempts": body.get("attempts"),
        "seconds": round(seconds, 1),
        "speedup": ((body.get("verification") or {}).get("benchmark") or {}).get("speedup"),
        "error": body.get("error"),
        "green_code": body.get("green_code"),
        "hidden_ok": None,
        "hidden_error": None,
    }
    if record["status"] == "optimized":
        record["hidden_ok"], record["hidden_error"] = hidden_check(case, body["green_code"])
    return record


def summarize(records: list[dict], runs: int) -> str:
    by_case = defaultdict(list)
    for r in records:
        by_case[r["id"]].append(r)
    by_pattern = defaultdict(list)
    for case in CASES:
        if case["id"] in by_case:
            by_pattern[case["expected"][0]].extend(by_case[case["id"]])

    def ok(r):  # doğru ve doğrulanmış optimizasyon
        return r["status"] == "optimized" and r["hidden_ok"]

    total = len(records)
    good = sum(ok(r) for r in records)
    false_ok = sum(r["status"] == "optimized" and r["hidden_ok"] is False for r in records)
    lines = [
        f"# Değerlendirme sonucu — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Model: `{config.OLLAMA_MODEL}` · {len(by_case)} kod × {runs} çalıştırma = {total} optimizasyon",
        "",
        f"- **Doğru optimizasyon:** {good}/{total} (%{100 * good / total:.0f})",
        f"- **Yanlış onay** (doğrulandı dendi, gizli testler kaldı): **{false_ok}**",
        f"- **Medyan süre:** {median(r['seconds'] for r in records):.0f} sn"
        f" · ilk denemede başarı: {sum(ok(r) and r['attempts'] == 1 for r in records)}/{total}",
        f"- **Desen tespiti:** beklenen desen {sum(r['detected_expected'] for r in records)}/{total} çalıştırmada bulundu",
        "",
        "## Desen başına",
        "",
        "| Desen | Doğru | Yanlış onay | Medyan süre |",
        "|---|---|---|---|",
    ]
    for pattern in sorted(by_pattern):
        rs = by_pattern[pattern]
        lines.append(
            f"| {pattern} | {sum(ok(r) for r in rs)}/{len(rs)} | "
            f"{sum(r['status'] == 'optimized' and r['hidden_ok'] is False for r in rs)} | "
            f"{median(r['seconds'] for r in rs):.0f} sn |"
        )
    lines += ["", "## Kod başına", "", "| Kod | Beklenen / bulunan | Sonuçlar | Hızlanma (medyan) | Not |", "|---|---|---|---|---|"]
    for case in CASES:
        rs = by_case.get(case["id"])
        if not rs:
            continue
        marks = " ".join(
            "✅" if ok(r) else ("⚠️" if r["status"] == "optimized" else ("➖" if r["status"] == "clean" else "❌"))
            for r in rs
        )
        speedups = [r["speedup"] for r in rs if ok(r) and r["speedup"]]
        note = next((r["hidden_error"] for r in rs if r["hidden_error"]), None) or next(
            (r["error"] for r in rs if r["error"]), "")
        lines.append(
            f"| `{case['id']}` | {', '.join(case['expected'])} / {', '.join(rs[0]['detected']) or '—'} | {marks} | "
            f"{f'{median(speedups):,.1f}×' if speedups else '—'} | {str(note).replace('|', '/')[:140]} |"
        )
    lines += ["", "✅ doğru optimizasyon · ⚠️ yanlış onay · ❌ başarısız (güvenli) · ➖ desen bulunamadı (temiz)"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", default="", help="virgülle ayrılmış kod id'leri")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.only or c["id"] in args.only.split(",")]
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    jsonl = out_dir / f"{stamp}.jsonl"

    records = []
    with TestClient(app) as client, jsonl.open("w", encoding="utf-8") as fh:
        health = client.get("/api/health").json()
        if not health["llm"]["reachable"]:
            sys.exit(f"LLM'e ulaşılamıyor: {health['llm']['message']}")
        total = len(cases) * args.runs
        for run in range(args.runs):
            for case in cases:
                record = run_one(client, case) | {"run": run + 1}
                records.append(record)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                mark = {"optimized": "✅" if record["hidden_ok"] else "⚠️", "failed": "❌", "clean": "➖"}.get(record["status"], "?")
                print(f"[{len(records)}/{total}] {case['id']:<28} {mark} {record['status']:<9} "
                      f"{record['attempts']} deneme · {record['seconds']:.0f} sn", flush=True)

    summary = summarize(records, args.runs)
    (out_dir / f"{stamp}.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    main()
