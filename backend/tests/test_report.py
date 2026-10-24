import itertools
import textwrap
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import db
from app.db import AnalysisRun, GreenPattern, init_db
from app.main import app
from app.report import build_report, code_hash, normalize_code

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
_ids = itertools.count()


def finding(code: str, line: int = 1, title: str = "Kayıttaki başlık") -> dict:
    return {"line": line, "pattern_code": code, "title": title, "detail": "", "impact": "yüksek"}


def run(status: str, findings=(), old=None, new=None, minutes=0, code=None) -> AnalysisRun:
    """Kod verilmezse her kayda benzersiz bir kod atanır (tekrar sayılmasın)."""
    speedup = old / new if old is not None and new else None
    return AnalysisRun(
        created_at=T0 + timedelta(minutes=minutes),
        original_code=code if code is not None else f"def f{next(_ids)}(a):\n    return a\n",
        green_code=None if status == "clean" else "def f(a):\n    return list(a)\n",
        findings=list(findings),
        status=status,
        old_seconds=old,
        new_seconds=new,
        speedup=speedup,
    )


@pytest.fixture
def session():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    init_db(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


def test_empty_database_returns_zeros(session):
    assert build_report(session) == {
        "total_runs": 0,
        "unique_codes": 0,
        "status_counts": {"optimized": 0, "clean": 0, "failed": 0},
        "success_rate": 0.0,
        "patterns": [],
        "savings": {
            "measured_runs": 0, "total_seconds": 0, "median_seconds": 0.0,
            "speedup_groups": {
                "high": {"codes": ["YK-01", "YK-02", "YK-05", "YK-06", "YK-07", "YK-08"], "runs": 0,
                         "median_speedup": 0.0, "items": []},
                "low": {"codes": ["YK-03", "YK-04", "YK-09", "YK-10"], "runs": 0, "median_speedup": 0.0, "items": []},
            },
            "energy": {"estimated_runs": 0, "total_kwh_per_year": 0, "watts": 65.0, "runs_per_day": 10000.0},
        },
        "top_runs": [],
    }


def test_report_with_sample_runs(session):
    session.add_all([
        run("optimized", [finding("YK-01"), finding("YK-02", 5)], old=1.0, new=0.5, minutes=1),    # +0.5, 2×
        run("optimized", [finding("YK-01")], old=0.4, new=0.1, minutes=2),                         # +0.3, 4×
        run("optimized", [finding("YK-02"), finding("YK-02", 9)], old=0.2, new=0.25, minutes=3),  # −0.05, 0.8×
        run("optimized", [finding("YK-03")], minutes=4),                                           # süre ölçülmedi
        run("failed", [finding("YK-01")], old=9.0, new=0.1, minutes=5),                            # sayılmaz
        run("clean", minutes=6),
    ])
    session.commit()

    report = build_report(session)

    assert report["total_runs"] == 6 and report["unique_codes"] == 6
    assert report["status_counts"] == {"optimized": 4, "clean": 1, "failed": 1}
    assert report["success_rate"] == pytest.approx(4 / 5)

    # YK-01: 3 tespit / 3 analiz; YK-02: 3 tespit / 2 analiz -> eşitlikte koda göre sıralı.
    assert [(p["code"], p["count"], p["runs"]) for p in report["patterns"]] == [
        ("YK-01", 3, 3), ("YK-02", 3, 2), ("YK-03", 1, 1),
    ]
    assert report["patterns"][0]["title"] == "İç içe döngü"  # başlık güncel katalogdan

    savings = report["savings"]
    assert savings["measured_runs"] == 3
    assert savings["total_seconds"] == pytest.approx(0.5 + 0.3 - 0.05)
    assert savings["median_seconds"] == pytest.approx(0.3)
    # Üç ölçümlü analizin hepsi yüksek etkili desen içeriyor: 2×, 4×, 0,8× -> medyan 2×.
    assert savings["speedup_groups"]["high"]["runs"] == 3
    assert savings["speedup_groups"]["high"]["median_speedup"] == pytest.approx(2.0)
    assert savings["speedup_groups"]["low"]["runs"] == 0
    # Tahmini enerji: yalnızca hızlanan iki doğrulanmış analiz (0,5 s + 0,3 s), 65 W, günde 10.000 kez.
    assert savings["energy"]["estimated_runs"] == 2
    assert savings["energy"]["total_kwh_per_year"] == pytest.approx((0.5 + 0.3) * 65 * 10_000 * 365 / 3_600_000)

    # Yalnızca kazanç sağlayan doğrulanmış analizler, kazanca göre azalan.
    top = report["top_runs"]
    assert [r["gain_seconds"] for r in top] == pytest.approx([0.5, 0.3])
    assert top[0]["status"] == "optimized"
    assert top[0]["created_at"].startswith("2026-10-01T00:01:00") and top[0]["created_at"].endswith("+00:00")
    assert [f["pattern_code"] for f in top[0]["findings"]] == ["YK-01", "YK-02"]
    assert {"original_code", "green_code", "old_seconds", "new_seconds", "speedup"} <= set(top[0])


def test_top_runs_limited_to_five(session):
    session.add_all(run("optimized", [finding("YK-01")], old=1.0 + i, new=0.5, minutes=i) for i in range(8))
    session.commit()
    top = build_report(session)["top_runs"]
    assert len(top) == 5
    assert [r["old_seconds"] for r in top] == [8.0, 7.0, 6.0, 5.0, 4.0]


def test_only_clean_runs_have_zero_success_rate(session):
    session.add_all([run("clean"), run("clean")])
    session.commit()
    report = build_report(session)
    assert report["total_runs"] == 2 and report["success_rate"] == 0.0


def test_unknown_pattern_uses_stored_title(session):
    session.delete(session.get(GreenPattern, "YK-07"))
    session.add(run("failed", [finding("YK-07", title="Eski başlık"), finding("YK-77", title=None)]))
    session.commit()
    titles = {p["code"]: p["title"] for p in build_report(session)["patterns"]}
    assert titles == {"YK-07": "Eski başlık", "YK-77": "YK-77"}


def test_report_endpoint_on_empty_database():
    db.configure_engine("sqlite://")
    with TestClient(app) as client:
        resp = client.get("/api/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 0 and body["patterns"] == [] and body["top_runs"] == []


# --------------------------------------------------------------------------- #
# Tekrarlanan kodlar
# --------------------------------------------------------------------------- #

CODE = "def f(items):\n    out = []\n    for x in items:\n        out.append(x)\n    return out\n"


def test_normalization_ignores_whitespace_and_line_endings():
    variants = [
        CODE,
        CODE.replace("\n", "\r\n"),                      # Windows satır sonları
        "\n\n" + CODE + "\n\n   \n",                     # baştaki/sondaki boş satırlar
        CODE.replace("\n", "   \n"),                      # satır sonu boşlukları
        CODE.replace("    ", "\t"),                        # sekme girintisi
        textwrap.indent(CODE, "        "),                 # tamamı girintili yapıştırılmış
        CODE.replace("out = []", "out  =   []"),           # satır içi fazla boşluk
    ]
    assert len({code_hash(v) for v in variants}) == 1


def test_normalization_keeps_meaningful_indentation():
    inside = "def f(a):\n    t = 0\n    for x in a:\n        t += x\n        return t\n"
    outside = "def f(a):\n    t = 0\n    for x in a:\n        t += x\n    return t\n"
    assert code_hash(inside) != code_hash(outside)
    assert normalize_code(outside).splitlines()[-1] == "    return t"


def test_repeated_code_counts_only_latest_success(session):
    session.add_all([
        run("optimized", [finding("YK-01")], old=1.0, new=0.001, minutes=1, code=CODE),           # eski başarı
        run("optimized", [finding("YK-01")], old=1.0, new=0.002, minutes=5, code=CODE + "\n\n"),  # EN SON başarı
        run("failed", [finding("YK-01")], old=1.0, new=0.0001, minutes=9, code=CODE.replace("\n", "\r\n")),
        run("optimized", [finding("YK-04")], old=0.012, new=0.010, minutes=2),                    # başka kod
    ])
    session.commit()

    report = build_report(session)
    # Toplam analiz ve başarı oranı tüm çalıştırmaları sayar.
    assert report["total_runs"] == 4
    assert report["success_rate"] == pytest.approx(3 / 4)
    assert report["unique_codes"] == 2

    savings = report["savings"]
    assert savings["measured_runs"] == 2
    assert savings["total_seconds"] == pytest.approx((1.0 - 0.002) + (0.012 - 0.010))
    assert savings["speedup_groups"]["high"]["runs"] == 1
    assert savings["speedup_groups"]["high"]["median_speedup"] == pytest.approx(500)   # 1,0 / 0,002
    assert savings["speedup_groups"]["low"]["median_speedup"] == pytest.approx(1.2)    # 0,012 / 0,010
    expected_kwh = ((1.0 - 0.002) + (0.012 - 0.010)) * 65 * 10_000 * 365 / 3_600_000
    assert savings["energy"]["estimated_runs"] == 2
    assert savings["energy"]["total_kwh_per_year"] == pytest.approx(expected_kwh)

    # Desen sıklığı ve en çok kazanç tablosu da kod başına bir kez.
    assert [(p["code"], p["count"], p["runs"]) for p in report["patterns"]] == [("YK-01", 1, 1), ("YK-04", 1, 1)]
    assert [r["new_seconds"] for r in report["top_runs"]] == [0.002, 0.010]


def test_code_without_success_still_counts_in_pattern_frequency(session):
    session.add_all([
        run("failed", [finding("YK-07")], minutes=1, code=CODE),
        run("failed", [finding("YK-07"), finding("YK-07", 3)], minutes=2, code=CODE),  # en son analiz
    ])
    session.commit()
    report = build_report(session)
    assert report["unique_codes"] == 1
    assert [(p["code"], p["count"], p["runs"]) for p in report["patterns"]] == [("YK-07", 2, 1)]
    assert report["savings"]["measured_runs"] == 0 and report["top_runs"] == []


# --------------------------------------------------------------------------- #
# Hızlanma grupları
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("codes, group", [
    (["YK-01"], "high"),
    (["YK-04", "YK-05"], "high"),          # bir yüksek etkili desen yeterli
    (["YK-03", "YK-04", "YK-09", "YK-10"], "low"),
    (["YK-04"], "low"),
])
def test_speedup_groups(session, codes, group):
    session.add(run("optimized", [finding(c) for c in codes], old=1.0, new=0.5))
    session.commit()
    groups = build_report(session)["savings"]["speedup_groups"]
    other = "low" if group == "high" else "high"
    assert groups[group]["runs"] == 1 and groups[group]["median_speedup"] == pytest.approx(2.0)
    assert groups[other]["runs"] == 0 and groups[other]["median_speedup"] == 0.0


def test_speedup_groups_separate_bimodal_speedups(session):
    session.add_all([
        run("optimized", [finding("YK-04")], old=0.012, new=0.010),     # 1,2×
        run("optimized", [finding("YK-03")], old=0.013, new=0.010),     # 1,3×
        run("optimized", [finding("YK-01")], old=0.6, new=0.001),       # 600×
        run("optimized", [finding("YK-05")], old=0.7, new=0.001),       # 700×
        run("optimized", [finding("YK-02")], old=0.8, new=0.001),       # 800×
        run("optimized", [finding("YK-06")], old=0.9, new=0.001),       # 900×
    ])
    session.commit()
    groups = build_report(session)["savings"]["speedup_groups"]
    assert groups["low"]["median_speedup"] == pytest.approx(1.25)
    assert groups["high"]["median_speedup"] == pytest.approx(750)
    assert groups["high"]["items"] == []  # 4 kod: medyan gösterilir


def test_few_codes_are_listed_individually_with_function_names(session):
    session.add_all([
        run("optimized", [finding("YK-01")], old=0.4255, new=0.0002, code="def find_duplicates(items):\n    return items\n"),
        run("optimized", [finding("YK-05")], old=0.21, new=0.0002, code="def find_pair(numbers, target):\n    return None\n"),
        run("optimized", [finding("YK-04")], old=0.012, new=0.010, code="class Report:\n    pass\n\ndef build(a):\n    return a\n"),
        run("optimized", [finding("YK-03")], old=0.013, new=0.010, code="x = 1\n"),
    ])
    session.commit()
    groups = build_report(session)["savings"]["speedup_groups"]
    assert [(i["label"], round(i["speedup"])) for i in groups["high"]["items"]] == [
        ("find_duplicates", 2128), ("find_pair", 1050),
    ]
    low = groups["low"]["items"]
    assert [i["label"] for i in low] == ["analiz #4", "Report, build"]  # en yüksek hızlanma önce (1,3× > 1,2×)
