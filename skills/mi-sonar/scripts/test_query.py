import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import query as q  # noqa: E402


def test_parse_front_matter_scalars_and_list():
    text = "---\nname: smartphone\nkind: postgres\nenv: MI_DB_SMARTPHONE\ntables: [a, b]\nsummary: 한글 요약\n---\n# body\n"
    fm = q.parse_front_matter(text)
    assert fm == {
        "name": "smartphone",
        "kind": "postgres",
        "env": "MI_DB_SMARTPHONE",
        "tables": ["a", "b"],
        "summary": "한글 요약",
    }


def test_parse_front_matter_missing_returns_empty():
    assert q.parse_front_matter("no header here") == {}


def test_load_sources_reads_dir(tmp_path):
    (tmp_path / "x.md").write_text("---\nname: x\nkind: postgres\nenv: X_ENV\n---\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    src = q.load_sources(tmp_path)
    assert list(src) == ["x"]
    assert src["x"]["env"] == "X_ENV"
    assert src["x"]["path"] == tmp_path / "x.md"


def test_parse_front_matter_inline_comment_and_bom(tmp_path):
    (tmp_path / "x.md").write_text("---\nname: x\nenv: X_ENV   # note\n---\n", encoding="utf-8-sig")
    assert (tmp_path / "x.md").read_bytes().startswith(b"\xef\xbb\xbf---")
    assert q.load_sources(tmp_path)["x"]["env"] == "X_ENV"


def test_get_source_requires_env(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("---\nname: x\nkind: postgres\nenv: X_ENV\n---\n", encoding="utf-8")
    monkeypatch.delenv("X_ENV", raising=False)
    with pytest.raises(q.SonarError) as e:
        q.get_source("x", q.load_sources(tmp_path))
    assert e.value.code == 2
    monkeypatch.setenv("X_ENV", "postgresql://u:p@h/db")
    s = q.get_source("x", q.load_sources(tmp_path))
    assert s["conn"] == "postgresql://u:p@h/db"


def test_get_source_rejects_unencoded_at_in_password(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("---\nname: x\nkind: postgres\nenv: X_ENV\n---\n", encoding="utf-8")
    monkeypatch.setenv("X_ENV", "postgresql://u:p@ss@h/db")
    with pytest.raises(q.SonarError) as e:
        q.get_source("x", q.load_sources(tmp_path))
    assert e.value.code == 2
    monkeypatch.setenv("X_ENV", "postgresql://u:p%40ss@h/db")
    assert q.get_source("x", q.load_sources(tmp_path))["conn"] == "postgresql://u:p%40ss@h/db"


def test_get_source_unknown_name(tmp_path):
    with pytest.raises(q.SonarError) as e:
        q.get_source("nope", q.load_sources(tmp_path))
    assert e.value.code == 1


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from t where x = 1;",
    "  WITH a AS (SELECT 1) SELECT * FROM a  ;\n",
    "-- comment\nSELECT /* inline */ 1",
    "SELECT created_at, updated_by FROM t",  # 'created'/'updated' are not whole-word matches
])
def test_check_sql_allows(sql):
    assert q.check_sql(sql).upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize("sql,word", [
    ("DELETE FROM t", None),
    ("SELECT 1; DROP TABLE t", None),
    ("SELECT 1; SELECT 2", None),
    ("UPDATE t SET a=1", None),
    ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "DELETE"),
    ("SELECT * FROM t WHERE note = 'drop'", "DROP"),  # known false positive, see SKILL.md
    ("", None),
    ("-- only a comment", None),
])
def test_check_sql_rejects(sql, word):
    with pytest.raises(q.SonarError) as e:
        q.check_sql(sql)
    assert e.value.code == 3
    if word:
        assert word in str(e.value)


def test_format_table_escapes_and_none():
    out = q.format_table(["모델", "비고"], [("갤럭시|S25", None), ("x\ny", 3)])
    lines = out.splitlines()
    assert lines[0] == "| 모델 | 비고 |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 갤럭시\\|S25 |  |"
    assert lines[3] == "| x y | 3 |"


def test_format_table_empty():
    assert q.format_table(["a"], []) == "| a |\n| --- |\n(0 rows)"


class _FakeCursor:
    def __init__(self, rows, cols):
        self._rows = rows
        self.description = [type("D", (), {"name": c})() for c in cols]
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append(str(sql))

    def fetchmany(self, n):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out

    def fetchall(self):
        out, self._rows = self._rows, []
        return out


class _FakeConn:
    def __init__(self, rows, cols):
        self.rows, self.cols, self.read_only, self.closed = rows, cols, None, False

    def cursor(self, name=None):
        return _FakeCursor(list(self.rows), self.cols)

    def execute(self, sql, params=None):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


@pytest.mark.parametrize("n,expect,notice", [
    (50, 50, ""),
    (5000, 5000, ""),
    (99999, 5000, "5000"),
])
def test_clamp_limit(n, expect, notice):
    lim, msg = q.clamp_limit(n)
    assert lim == expect and notice in msg


@pytest.mark.parametrize("n", [0, -5])
def test_clamp_limit_rejects_nonpositive(n):
    with pytest.raises(q.SonarError):
        q.clamp_limit(n)


def test_run_sql_truncates(monkeypatch):
    rows = [(i,) for i in range(10)]
    monkeypatch.setattr(q, "connect_pg", lambda dsn: _FakeConn(rows, ["n"]))
    cols, got, truncated = q.run_sql({"conn": "x"}, "SELECT n FROM t", limit=3)
    assert cols == ["n"] and got == [(0,), (1,), (2,)] and truncated is True
    cols, got, truncated = q.run_sql({"conn": "x"}, "SELECT n FROM t", limit=50)
    assert len(got) == 10 and truncated is False


def test_run_sql_rejects_before_connecting(monkeypatch):
    called = []
    monkeypatch.setattr(q, "connect_pg", lambda dsn: called.append(dsn))
    with pytest.raises(q.SonarError) as e:
        q.run_sql({"conn": "x"}, "DROP TABLE t", limit=5)
    assert e.value.code == 3 and called == []


def test_cmd_sql_writes_csv_and_notes_truncation(monkeypatch, tmp_path):
    rows = [(i, "가") for i in range(5)]
    monkeypatch.setattr(q, "connect_pg", lambda dsn: _FakeConn(rows, ["n", "s"]))
    out = q.cmd_sql({"conn": "x"}, "SELECT 1", limit=2, csv_path=tmp_path / "o.csv")
    assert "| n | s |" in out and "잘렸습니다" in out and "o.csv" in out
    text = (tmp_path / "o.csv").read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "n,s" and len(text.splitlines()) == 3


def test_cmd_sql_csv_prints_head_only(monkeypatch, tmp_path):
    rows = [(i,) for i in range(50)]
    monkeypatch.setattr(q, "connect_pg", lambda dsn: _FakeConn(rows, ["n"]))
    out = q.cmd_sql({"conn": "x"}, "SELECT 1", limit=100, csv_path=tmp_path / "o.csv")
    data_rows = [l for l in out.splitlines() if l.startswith("| ") and l not in ("| n |", "| --- |")]
    assert len(data_rows) == 20 and "50행 저장" in out
    assert len((tmp_path / "o.csv").read_text(encoding="utf-8-sig").splitlines()) == 51


def test_truncation_notice_before_table(monkeypatch):
    monkeypatch.setattr(q, "connect_pg", lambda dsn: _FakeConn([(i,) for i in range(5)], ["n"]))
    lines = q.cmd_sql({"conn": "x"}, "SELECT 1", limit=2, csv_path=None).splitlines()
    notice = next(i for i, l in enumerate(lines) if "잘렸습니다" in l)
    assert notice < lines.index("| n |")


def test_redact_masks_conn_and_password():
    out = q.redact('bad "http://AK:p%40ss@h/b" and p@ss', "http://AK:p%40ss@h/b")
    assert "p%40ss" not in out and "p@ss" not in out


def test_connect_pg_kwargs():
    src = Path(q.__file__).read_text(encoding="utf-8")
    assert "connect_timeout=10" in src and "options=" not in src


def test_parse_minio_url_decodes_secret():
    cfg = q.parse_minio_url("https://AK:p%40ss%2Fw%25rd@minio.corp:9000/mi-bucket")
    assert cfg == {
        "endpoint": "minio.corp:9000",
        "access": "AK",
        "secret": "p@ss/w%rd",
        "bucket": "mi-bucket",
        "secure": True,
    }


def test_parse_minio_url_http_insecure():
    assert q.parse_minio_url("http://a:b@h:9000/b")["secure"] is False


@pytest.mark.parametrize("bad", ["http://h:9000/b", "http://a:b@h:9000", "minio.corp:9000"])
def test_parse_minio_url_rejects(bad):
    with pytest.raises(q.SonarError):
        q.parse_minio_url(bad)


class _Obj:
    def __init__(self, name, size):
        self.object_name, self.size, self.last_modified = name, size, "2026-01-01"


class _FakeMinio:
    def __init__(self, n=300):
        self.fetched, self.n = [], n

    def list_objects(self, bucket, prefix="", recursive=True):
        for i in range(self.n):
            yield _Obj(f"{prefix}f{i}.pdf", i)

    def fget_object(self, bucket, key, path):
        self.fetched.append((bucket, key, path))
        Path(path).write_bytes(b"x")


def test_cmd_ls_caps_at_200(monkeypatch):
    monkeypatch.setattr(q, "connect_minio", lambda url: (_FakeMinio(), "b"))
    out = q.cmd_ls({"conn": "x"}, "2026/")
    assert "2026/f199.pdf" in out and "2026/f200.pdf" not in out
    assert "200" in out.splitlines()[-1]


def test_cmd_ls_exactly_200_has_no_cap_notice(monkeypatch):
    monkeypatch.setattr(q, "connect_minio", lambda url: (_FakeMinio(200), "b"))
    assert "최대" not in q.cmd_ls({"conn": "x"}, "")
    monkeypatch.setattr(q, "connect_minio", lambda url: (_FakeMinio(201), "b"))
    out = q.cmd_ls({"conn": "x"}, "")
    assert "최대" in out and "f200.pdf" not in out


def test_cmd_fetch_default_out_is_basename(monkeypatch, tmp_path):
    fake = _FakeMinio()
    monkeypatch.setattr(q, "connect_minio", lambda url: (fake, "b"))
    monkeypatch.chdir(tmp_path)
    out = q.cmd_fetch({"conn": "x"}, "2026/report 1.pdf", None)
    assert fake.fetched[0][1] == "2026/report 1.pdf"
    assert (tmp_path / "report 1.pdf").exists() and "report 1.pdf" in out


import subprocess

SCRIPT = Path(__file__).resolve().parent / "query.py"


def _run(*args, env_extra=None):
    env = {**os.environ, "PYTHONIOENCODING": "cp949", **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def test_cmd_sources_masks_values(monkeypatch, tmp_path):
    (tmp_path / "x.md").write_text(
        "---\nname: x\nkind: postgres\nenv: X_ENV\nsummary: 테스트\n---\n", encoding="utf-8"
    )
    monkeypatch.setenv("X_ENV", "postgresql://u:SECRET@h/db")
    out = q.cmd_sources(q.load_sources(tmp_path))
    assert "x" in out and "설정됨" in out and "SECRET" not in out
    monkeypatch.delenv("X_ENV")
    assert "미설정" in q.cmd_sources(q.load_sources(tmp_path))


def test_cli_sources_runs_on_cp949_console():
    r = _run("sources")
    assert r.returncode == 0, r.stderr
    assert "smartphone" in r.stdout and "minio" in r.stdout


def test_cli_exit_codes():
    r = _run("sql", "smartphone", "SELECT 1", env_extra={"MI_DB_SMARTPHONE": ""})
    assert r.returncode == 2 and "MI_DB_SMARTPHONE" in r.stderr
    r = _run("sql", "smartphone", "DROP TABLE t",
             env_extra={"MI_DB_SMARTPHONE": "postgresql://u:p@localhost:1/db"})
    assert r.returncode == 3 and "p@localhost" not in r.stderr
    r = _run("schema", "nope")
    assert r.returncode == 1


def test_cli_kind_mismatch_exit_1():
    r = _run("sql", "minio", "SELECT 1", env_extra={"MI_MINIO": "http://AK:TopSecret99@h:9000/b"})
    assert r.returncode == 1 and "kind=postgres" in r.stderr and "TopSecret99" not in r.stderr


@pytest.fixture(scope="module")
def pg_dsn(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    import psycopg
    with pgserver.get_server(tmp_path_factory.mktemp("pgdata")) as s:
        with psycopg.connect(s.get_uri(), autocommit=True) as c:
            c.execute("CREATE TABLE with_c(a int, b text)")
            c.execute("INSERT INTO with_c VALUES (1, 'x')")
            c.execute("COMMENT ON TABLE with_c IS '출하량 테이블'")
            c.execute("COMMENT ON COLUMN with_c.a IS '출하 대수'")
            c.execute("CREATE TABLE no_c(a int)")
            c.execute("INSERT INTO no_c VALUES (1)")
        yield s.get_uri()


def test_cmd_schema_shows_comments(pg_dsn):
    out = q.cmd_schema({"conn": pg_dsn, "tables": ["with_c"]})
    assert "설명: 출하량 테이블" in out
    assert "| column | type | nullable | comment |" in out
    assert "출하 대수" in out


def test_cmd_schema_without_comments_unchanged(pg_dsn):
    out = q.cmd_schema({"conn": pg_dsn, "tables": ["no_c"]})
    assert "comment" not in out and "설명:" not in out
    assert "| column | type | nullable |" in out
