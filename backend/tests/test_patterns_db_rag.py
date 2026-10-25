import ast

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.analyzer import analyze
from app.db import AnalysisRun, GreenPattern, init_db, load_catalog
from app.patterns import EXAMPLE_INPUTS, GREEN_PATTERNS, PATTERNS_BY_CODE
from app.rag import retrieve
from app.verifier import verify

EXPECTED_CODES = [f"YK-{i:02d}" for i in range(1, 11)]
FIELDS = {"code", "title", "anti_pattern", "solution", "impact", "example_before", "example_after"}


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# --------------------------------------------------------------------------- #
# patterns.py
# --------------------------------------------------------------------------- #

def test_patterns_cover_all_codes_with_all_fields():
    assert [p["code"] for p in GREEN_PATTERNS] == EXPECTED_CODES
    for p in GREEN_PATTERNS:
        assert set(p) == FIELDS
        assert all(isinstance(v, str) and v.strip() for v in p.values()), p["code"]
        assert p["impact"] in ("yüksek", "orta", "düşük")


@pytest.mark.parametrize("pattern", GREEN_PATTERNS, ids=lambda p: p["code"])
def test_examples_are_valid_python(pattern):
    ast.parse(pattern["example_before"])
    ast.parse(pattern["example_after"])


@pytest.mark.parametrize("pattern", GREEN_PATTERNS, ids=lambda p: p["code"])
def test_analyzer_flags_before_but_not_after(pattern):
    """Örnekler analyzer ile tutarlı: 'önce' deseni içerir, 'sonra' içermez."""
    code = pattern["code"]
    before = {f["pattern_code"] for f in analyze(pattern["example_before"])["findings"]}
    after = {f["pattern_code"] for f in analyze(pattern["example_after"])["findings"]}
    assert code in before
    assert code not in after


def test_example_inputs_cover_all_patterns():
    assert sorted(EXAMPLE_INPUTS) == EXPECTED_CODES


@pytest.mark.parametrize("pattern", GREEN_PATTERNS, ids=lambda p: p["code"])
def test_examples_are_equivalent(pattern):
    """'Sonra' örneği 'önce' ile aynı davranmalı (dönüş değeri, hata tipi ve argüman yan etkileri).

    Modeller onaylı örnekleri birebir kopyalar; eşdeğer olmayan bir örnek LLM'i sistematik olarak
    yanlış koda yönlendirir (ör. YK-07 örneği girdi listesini boşaltmıyordu, YK-01 örneği set
    kullandığı için tekrarları kaybediyordu).
    """
    result = verify(pattern["example_before"], pattern["example_after"], EXAMPLE_INPUTS[pattern["code"]])
    failing = [c for c in result["cases"] if not c["equal"]]
    assert result["passed"], f"{pattern['code']}: {result['error']} {failing[:2]}"


# --------------------------------------------------------------------------- #
# db.py
# --------------------------------------------------------------------------- #

def test_init_db_creates_tables_and_seeds(engine, session):
    assert {"green_patterns", "analysis_runs"} <= set(inspect(engine).get_table_names())
    codes = session.scalars(select(GreenPattern.code).order_by(GreenPattern.code)).all()
    assert codes == EXPECTED_CODES


def test_init_db_adds_missing_but_keeps_edits(engine, session):
    """Veritabanı asıl kaynak: yeniden başlatma (init_db) düzenlemelerin üzerine yazmaz."""
    session.delete(session.get(GreenPattern, "YK-10"))
    edited = session.get(GreenPattern, "YK-05")
    edited.example_after = "def f():\n    return 1\n"
    edited.impact = "orta"
    session.get(GreenPattern, "YK-03").is_active = False
    session.add(GreenPattern(code="YK-99", title="Kuruma özel", anti_pattern="a", solution="s",
                             impact="düşük", example_before="b", example_after="c"))
    session.commit()

    init_db(engine)
    session.expire_all()

    assert session.get(GreenPattern, "YK-10").to_dict() == PATTERNS_BY_CODE["YK-10"]  # eksik olan eklendi
    assert session.get(GreenPattern, "YK-05").example_after == "def f():\n    return 1\n"  # düzenleme kaldı
    assert session.get(GreenPattern, "YK-05").impact == "orta"
    assert session.get(GreenPattern, "YK-03").is_active is False  # pasif durumu kaldı
    assert session.get(GreenPattern, "YK-99") is not None  # katalog dışı kayda dokunulmadı
    assert session.scalar(select(func.count()).select_from(GreenPattern)) == 11


def test_seeded_patterns_are_active_with_timestamp(session):
    rows = session.scalars(select(GreenPattern)).all()
    assert all(r.is_active is True and r.updated_at is not None for r in rows)


def test_updated_at_changes_on_edit(session):
    row = session.get(GreenPattern, "YK-01")
    before = row.updated_at
    row.solution = "Yeni çözüm"
    session.commit()
    assert row.updated_at > before


OLD_SCHEMA = """
CREATE TABLE green_patterns (
    code VARCHAR(16) PRIMARY KEY, title VARCHAR(200), anti_pattern TEXT, solution TEXT,
    impact VARCHAR(16), example_before TEXT, example_after TEXT
)
"""


def test_init_db_migrates_old_table_without_data_loss():
    """is_active/updated_at olmadan oluşturulmuş eski tablo: sütunlar eklenir, veri korunur."""
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as conn:
        conn.execute(text(OLD_SCHEMA))
        conn.execute(text(
            "INSERT INTO green_patterns VALUES "
            "('YK-01', 'İç içe döngü', 'kurum açıklaması', 'kurum çözümü', 'orta', 'x = 1', 'y = 2')"
        ))

    init_db(eng)
    init_db(eng)  # ikinci açılış: sütunlar zaten var, hata vermemeli

    columns = {c["name"] for c in inspect(eng).get_columns("green_patterns")}
    assert {"is_active", "updated_at", "example_inputs"} <= columns
    with Session(eng) as s:
        row = s.get(GreenPattern, "YK-01")
        assert (row.solution, row.impact, row.is_active, row.updated_at) == ("kurum çözümü", "orta", True, None)
        assert row.example_inputs == EXAMPLE_INPUTS["YK-01"]  # eski kayda varsayılan test girdileri
        assert s.scalar(select(func.count()).select_from(GreenPattern)) == 10  # eksikler eklendi
    eng.dispose()


def test_load_catalog(session):
    session.get(GreenPattern, "YK-02").is_active = False
    session.get(GreenPattern, "YK-01").title = "Kurum başlığı"
    session.commit()

    catalog = load_catalog(session)
    assert set(catalog) == set(EXPECTED_CODES)
    assert catalog["YK-02"]["is_active"] is False
    assert catalog["YK-01"] == {"title": "Kurum başlığı", "impact": "yüksek", "is_active": True}


# --------------------------------------------------------------------------- #
# analyzer + katalog
# --------------------------------------------------------------------------- #

NESTED_MEMBERSHIP = """\
def f(items):
    seen = []
    for x in items:
        for y in items:
            if x not in seen:
                seen.append(x)
    return seen
"""


def test_analyzer_uses_catalog_title_and_impact(session):
    row = session.get(GreenPattern, "YK-01")
    row.title, row.impact = "Kurum başlığı", "düşük"
    session.commit()

    findings = analyze(NESTED_MEMBERSHIP, load_catalog(session))["findings"]
    yk01 = next(f for f in findings if f["pattern_code"] == "YK-01")
    assert (yk01["title"], yk01["impact"]) == ("Kurum başlığı", "düşük")


def test_analyzer_skips_inactive_patterns(session):
    session.get(GreenPattern, "YK-02").is_active = False
    session.commit()

    result = analyze(NESTED_MEMBERSHIP, load_catalog(session))
    assert {f["pattern_code"] for f in result["findings"]} == {"YK-01"}
    assert result["functions"][0]["complexity"] == "O(N²)"  # karmaşıklık yine raporlanır


def test_analyzer_without_catalog_uses_defaults():
    assert {f["pattern_code"] for f in analyze(NESTED_MEMBERSHIP)["findings"]} == {"YK-01", "YK-02"}


def test_analysis_run_roundtrip(session):
    findings = [{"line": 3, "pattern_code": "YK-01", "impact": "yüksek"}]
    run = AnalysisRun(original_code="x = 1", findings=findings)
    session.add(run)
    session.commit()
    session.expire_all()

    loaded = session.get(AnalysisRun, run.id)
    assert loaded.findings == findings
    assert loaded.status == "pending"
    assert loaded.created_at is not None
    assert loaded.green_code is None and loaded.speedup is None


# --------------------------------------------------------------------------- #
# rag.py
# --------------------------------------------------------------------------- #

def test_retrieve_returns_requested_patterns_in_order(session):
    result = retrieve(["YK-05", "YK-01"], session=session)
    assert [r["code"] for r in result] == ["YK-05", "YK-01"]
    assert result[0] == PATTERNS_BY_CODE["YK-05"]


def test_retrieve_deduplicates_and_skips_unknown(session):
    result = retrieve(["YK-02", "YK-99", "YK-02"], session=session)
    assert [r["code"] for r in result] == ["YK-02"]


def test_retrieve_empty(session):
    assert retrieve([], session=session) == []


def test_retrieve_skips_inactive(session):
    session.get(GreenPattern, "YK-02").is_active = False
    session.commit()
    assert [r["code"] for r in retrieve(["YK-01", "YK-02"], session=session)] == ["YK-01"]


def test_seeded_patterns_have_example_inputs(session):
    rows = session.scalars(select(GreenPattern)).all()
    assert {r.code: r.example_inputs for r in rows} == EXAMPLE_INPUTS


def test_backfill_keeps_custom_inputs_and_updated_at(engine, session):
    custom = {"common": [[[9], [9]]]}
    session.get(GreenPattern, "YK-01").example_inputs = custom
    session.get(GreenPattern, "YK-02").example_inputs = None
    session.commit()
    stamp = session.get(GreenPattern, "YK-02").updated_at

    init_db(engine)  # yeniden başlatma
    session.expire_all()

    assert session.get(GreenPattern, "YK-01").example_inputs == custom      # kurumun girdisine dokunulmadı
    assert session.get(GreenPattern, "YK-02").example_inputs == EXAMPLE_INPUTS["YK-02"]  # boş olan dolduruldu
    assert session.get(GreenPattern, "YK-02").updated_at == stamp          # düzenleme sayılmadı
