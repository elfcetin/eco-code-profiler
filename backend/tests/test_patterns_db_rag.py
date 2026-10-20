import ast

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.analyzer import analyze
from app.db import AnalysisRun, GreenPattern, init_db
from app.patterns import GREEN_PATTERNS, PATTERNS_BY_CODE
from app.rag import retrieve

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


# --------------------------------------------------------------------------- #
# db.py
# --------------------------------------------------------------------------- #

def test_init_db_creates_tables_and_seeds(engine, session):
    assert {"green_patterns", "analysis_runs"} <= set(inspect(engine).get_table_names())
    codes = session.scalars(select(GreenPattern.code).order_by(GreenPattern.code)).all()
    assert codes == EXPECTED_CODES


def test_init_db_syncs_patterns_with_catalog(engine, session):
    session.delete(session.get(GreenPattern, "YK-10"))
    session.get(GreenPattern, "YK-05").example_after = "eski, hatalı örnek"
    session.add(GreenPattern(code="YK-99", title="Kuruma özel", anti_pattern="a", solution="s",
                             impact="düşük", example_before="b", example_after="c"))
    session.commit()

    init_db(engine)
    session.expire_all()

    assert session.get(GreenPattern, "YK-10") is not None  # eksik olan eklendi
    assert session.get(GreenPattern, "YK-05").to_dict() == PATTERNS_BY_CODE["YK-05"]  # güncellendi
    assert session.get(GreenPattern, "YK-99") is not None  # katalog dışı kayda dokunulmadı
    assert session.scalar(select(func.count()).select_from(GreenPattern)) == 11


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
