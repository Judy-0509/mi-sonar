import re
import sys
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
import psycopg  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db_check  # noqa: E402

FIRMS = ("IDC", "Counterpoint", "Canalys")


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    with pgserver.get_server(tmp_path_factory.mktemp("pgdata")) as s:
        with psycopg.connect(s.get_uri(), autocommit=True) as c:
            c.execute("CREATE TABLE smartphone_market_data"
                      "(firm text, period text, region text, model text, shipments int)")
            c.cursor().executemany(
                "INSERT INTO smartphone_market_data VALUES (%s, %s, %s, %s, %s)",
                [(f, "2026Q2", r, f"M{m}", 100 + m) for f in FIRMS for r in ("KR", "JP") for m in range(5)],
            )
        yield s


def run_report(uri, out, monkeypatch) -> str:
    monkeypatch.setenv("MI_DB_CHECK", uri)
    assert db_check.main(["--table", "smartphone_market_data", "--out", str(out)]) == 0
    return out.read_text(encoding="utf-8")


def test_owner_account_report_and_nothing_persists(srv, tmp_path, monkeypatch):
    rep = run_report(srv.get_uri(), tmp_path / "r.md", monkeypatch)
    assert "## 10. 판정" in rep
    assert "스키마 분리 가능: 예" in rep
    assert "같은 스키마에 테이블 추가 가능: 예" in rep
    ilike = [line for line in rep.splitlines() if line.startswith("- ILIKE")]
    assert len(ilike) == 2 and all(line.endswith(" OK") for line in ilike), ilike
    assert re.search(r"^\| firm \| 3 \|", rep, re.M), "firm should be a candidate column with 3 distinct values"
    assert "CREATE EXTENSION IF NOT EXISTS vector: OK" in rep  # so the check below proves the rollback
    with psycopg.connect(srv.get_uri(), autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'mi_probe_schema'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM pg_class WHERE relname LIKE 'mi\\_probe%'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM pg_extension WHERE extname = 'vector'").fetchone()[0] == 0


def test_readonly_role_cannot_create(srv, tmp_path, monkeypatch):
    with psycopg.connect(srv.get_uri(), autocommit=True) as c:
        c.execute("CREATE ROLE mi_ro LOGIN PASSWORD 'x'")
        c.execute("GRANT CONNECT ON DATABASE postgres TO mi_ro")
        c.execute("GRANT SELECT ON smartphone_market_data TO mi_ro")
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        c.execute("REVOKE CREATE ON DATABASE postgres FROM PUBLIC")
    uri = srv.get_postmaster_info().get_uri(user="mi_ro", database="postgres")  # same host/port, trust auth
    try:
        psycopg.connect(uri, connect_timeout=10).close()
    except psycopg.OperationalError as e:
        pytest.skip(f"pgserver auth does not allow a second role: {e}")
    rep = run_report(uri, tmp_path / "ro.md", monkeypatch)
    assert "rolsuper" in rep and "| 아니오 |" in rep
    assert "스키마 분리 가능: 아니오" in rep
    assert "같은 스키마에 테이블 추가 가능: 아니오" in rep
    assert "스키마 생성 권한 또는 전용 스키마 1개" in rep
