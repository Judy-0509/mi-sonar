#!/usr/bin/env python
"""mi-sonar db_check: what can this DBaaS account do? One transaction, everything rolled back.

Usage: python tools/db_check.py [--table smartphone_market_data] [--out db_check_report.md]
DSN comes from env MI_DB_CHECK, else MI_DB_SMARTPHONE. The DSN is never printed.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg
from psycopg import sql

ENV_VARS = ("MI_DB_CHECK", "MI_DB_SMARTPHONE")
EXTS = ("pg_bigm", "pg_trgm", "pgroonga", "vector")
MAX_TABLES = 200
SAMPLE = 20_000
DIM_MAX = 50
CHUNKS = [
    "갤럭시 S25 시리즈 출하량은 2026년 2분기에 전년 대비 12% 증가했다.",
    "아이폰 17 판매량은 일본에서 강세를 보였으며 점유율 55%를 기록했다.",
    "중국 시장에서는 화웨이와 샤오미가 갤럭시의 점유율을 잠식하고 있다.",
    "메모리 가격 상승으로 스마트폰 BOM 원가가 분기 대비 8% 올랐다.",
    "삼성전자 시스템LSI는 엑시노스 2600 양산을 2026년 하반기에 시작한다.",
]


def redact(text: str, conn: str | None) -> str:
    """Mask the conn string and its password (raw and URL-decoded)."""
    secrets = [conn] if conn else []
    try:
        pw = urlparse(conn).password if conn else None
    except ValueError:  # malformed URL: the whole conn is still masked
        pw = None
    if pw:
        secrets += [pw, unquote(pw)]
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [""])[0]


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "예" if v else "아니오"
    return str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def table(cols: list[str], rows: list) -> list[str]:
    if not rows:
        return ["(없음)"]
    return [
        "| " + " | ".join(cols) + " |",
        "|" + " --- |" * len(cols),
        *("| " + " | ".join(_cell(v) for v in r) + " |" for r in rows),
    ]


def q(cur, query, params=None) -> list[tuple]:
    cur.execute(query, params)
    return cur.fetchall()


def probe(cur, st: dict, stmt, keep: bool = False) -> str:
    """Run one statement in its own savepoint; roll it back unless keep."""
    cur.execute("SAVEPOINT p")
    try:
        cur.execute(stmt)
    except psycopg.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT p")
        return f"실패: {e.sqlstate or '-'} {redact(first_line(e), st['dsn'])}"
    if not keep:
        cur.execute("ROLLBACK TO SAVEPOINT p")
    return "OK"


# ---------- sections: each appends lines to out and facts to st ----------

def s_server(cur, out, st):
    row = q(cur, "SELECT version(), current_database(), current_user, current_schema(), "
                 "current_setting('search_path'), current_setting('server_encoding')")[0]
    names = ("version()", "current_database()", "current_user", "current_schema()", "search_path", "server_encoding")
    out += [f"- {n}: {_cell(v) if v is not None else '(없음)'}" for n, v in zip(names, row)]


def s_role(cur, out, st):
    rows = q(cur, "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolcanlogin "
                  "FROM pg_roles WHERE rolname = current_user")
    out += table([d.name for d in cur.description], rows)
    roles = [r[0] for r in q(cur, "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
                                  "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user) ORDER BY 1")]
    out += ["", "소속 역할: " + (", ".join(roles) or "(없음)")]


def s_db_priv(cur, out, st):
    rows = q(cur, "SELECT p, has_database_privilege(current_database(), p) "
                  "FROM unnest(ARRAY['CREATE', 'TEMP', 'CONNECT']) p")
    st["db_create"] = dict(rows)["CREATE"]
    out += table(["권한", "가능"], rows)


def s_schemas(cur, out, st):
    rows = q(cur, r"SELECT nspname, has_schema_privilege(oid, 'USAGE'), has_schema_privilege(oid, 'CREATE'), "
                  r"pg_get_userbyid(nspowner) FROM pg_namespace "
                  r"WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' ORDER BY 1")
    out += table(["schema", "USAGE", "CREATE", "owner"], rows)


def s_tables(cur, out, st):
    # tables are addressed by oid, so no identifier is ever built from a name
    rows = q(cur, r"""
        SELECT t.table_schema, t.table_name, t.table_type,
               has_table_privilege(c.oid, 'SELECT'), has_table_privilege(c.oid, 'INSERT'),
               has_table_privilege(c.oid, 'UPDATE'), has_table_privilege(c.oid, 'DELETE'),
               c.reltuples::bigint, pg_size_pretty(pg_total_relation_size(c.oid)), count(*) OVER ()
        FROM information_schema.tables t
        JOIN pg_namespace n ON n.nspname = t.table_schema
        JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = t.table_name
        WHERE t.table_type IN ('BASE TABLE', 'VIEW')
          AND t.table_schema NOT LIKE 'pg\_%' AND t.table_schema <> 'information_schema'
        ORDER BY 1, 2 LIMIT 200""")
    shown = [(*r[:7], r[7] if r[7] >= 0 else "?", r[8]) for r in rows]
    out += table(["schema", "table", "type", "SELECT", "INSERT", "UPDATE", "DELETE", "rows(추정)", "size"], shown)
    if rows:
        out.append("rows(추정)는 통계값입니다 (?: 아직 ANALYZE 전).")
    if rows and rows[0][-1] > MAX_TABLES:
        out.append(f"(테이블 {rows[0][-1]}개 중 처음 {MAX_TABLES}개만 표시)")


def s_create(cur, out, st):
    has_public, cs = q(cur, "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'public'), current_schema()")[0]
    st["schema"] = probe(cur, st, "CREATE SCHEMA mi_probe_schema")
    out.append(f"- CREATE SCHEMA mi_probe_schema: {st['schema']}")
    if has_public:
        st["tbl_public"] = probe(cur, st, "CREATE TABLE public.mi_probe_tbl (id int)")
        out.append(f"- CREATE TABLE public.mi_probe_tbl: {st['tbl_public']}")
    else:
        out.append("- CREATE TABLE public.mi_probe_tbl: 건너뜀 (public 스키마 없음)")
    if cs is None:
        out.append("- CREATE TABLE <current_schema>.mi_probe_tbl2: 건너뜀 (current_schema() 없음)")
    elif cs != "public":
        st["tbl_cur"] = probe(cur, st, sql.SQL("CREATE TABLE {}.mi_probe_tbl2 (id int)").format(sql.Identifier(cs)))
        out.append(f"- CREATE TABLE {cs}.mi_probe_tbl2: {st['tbl_cur']}")
    cur.execute("SAVEPOINT p_tmp")
    st["temp"] = probe(cur, st, "CREATE TEMP TABLE mi_probe_tmp (id int)", keep=True)
    out.append(f"- CREATE TEMP TABLE mi_probe_tmp: {st['temp']}")
    if st["temp"] == "OK":
        out.append(f"- CREATE INDEX ON mi_probe_tmp (id): {probe(cur, st, 'CREATE INDEX ON mi_probe_tmp (id)')}")
    else:
        out.append("- CREATE INDEX ON mi_probe_tmp (id): 건너뜀 (임시 테이블 없음)")
    cur.execute("ROLLBACK TO SAVEPOINT p_tmp")


def s_ext(cur, out, st):
    rows = {r[0]: r for r in q(cur, "SELECT name, default_version, installed_version FROM pg_available_extensions "
                                     "WHERE name IN ('pg_trgm', 'pg_bigm', 'pgroonga', 'vector') ORDER BY 1")}
    st["ext"] = {n: r[2] for n, r in rows.items()}
    out += table(["name", "default_version", "installed_version"], [rows.get(n, (n, "없음", "")) for n in EXTS])
    out.append("")
    st["create_vector"] = probe(cur, st, "CREATE EXTENSION IF NOT EXISTS vector")
    out.append(f"- CREATE EXTENSION IF NOT EXISTS vector: {st['create_vector']}")
    # last statement on purpose: kept alive (no rollback) until §8 finishes
    st["create_pg_trgm"] = probe(cur, st, "CREATE EXTENSION IF NOT EXISTS pg_trgm", keep=True)
    out.append(f"- CREATE EXTENSION IF NOT EXISTS pg_trgm: {st['create_pg_trgm']}")


def s_korean(cur, out, st):
    cur.execute("CREATE TEMP TABLE mi_probe_chunk (id int, body text)")
    cur.executemany("INSERT INTO mi_probe_chunk VALUES (%s, %s)", list(enumerate(CHUNKS, 1)))
    for word, want in (("갤럭시", [1, 3]), ("점유율", [2, 3])):
        got = [r[0] for r in q(cur, "SELECT id FROM mi_probe_chunk WHERE body ILIKE %s ORDER BY 1", (f"%{word}%",))]
        verdict = "OK" if got == want else f"불일치 (기대 {want})"
        out.append(f"- ILIKE '%{word}%': {len(got)}건 {got} {verdict}")
    ext = st.get("ext", {})
    if not (ext.get("pg_trgm") or st.get("create_pg_trgm") == "OK"):
        out.append("- pg_trgm 사용 불가: ILIKE 순차검색만 가능")
        return
    top = q(cur, "SELECT id, similarity(body, '갤럭시 점유율') FROM mi_probe_chunk ORDER BY 2 DESC LIMIT 1")[0]
    out.append(f"- similarity(body, '갤럭시 점유율') 최고: id={top[0]}, {top[1]:.3f}")
    cur.execute("CREATE INDEX ON mi_probe_chunk USING gin (body gin_trgm_ops)")
    cur.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(r[0] for r in q(cur, "EXPLAIN SELECT * FROM mi_probe_chunk WHERE body ILIKE '%갤럭시%'"))
    used = "인덱스 사용 (Bitmap)" if "Bitmap" in plan else "인덱스 미사용"
    out.append(f"- GIN(gin_trgm_ops) 인덱스 + ILIKE '%갤럭시%' 실행계획: {used} / {plan.splitlines()[0].strip()}")


def s_profile(cur, out, st):
    name = st["table"]
    if not name:
        out.append("(--table 미지정: 건너뜀)")
        return
    found = q(cur, "SELECT n.nspname, c.relname, c.reltuples::bigint, pg_size_pretty(pg_total_relation_size(c.oid)) "
                   "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = to_regclass(%s)", (name,))
    if not found:
        out.append(f"테이블 없음: {name} (건너뜀)")
        return
    schema, rel, n, size = found[0]
    out.append(f"- 위치: {schema}.{rel} / 대략 행 수: {n if n >= 0 else '? (ANALYZE 전)'} / 크기: {size}")
    cols = q(cur, "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                  "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, rel))
    out += ["", *table(["column", "type", "nullable"], cols)]
    cands = []
    for col, typ, _ in cols:
        if typ not in ("text", "character varying", "character"):
            continue
        top = q(cur, sql.SQL(
            "SELECT v, n, count(*) OVER () FROM (SELECT {c} AS v, count(*) AS n "
            "FROM (SELECT {c} FROM {t} LIMIT {lim}) s GROUP BY 1) g ORDER BY n DESC, v LIMIT 8"
        ).format(c=sql.Identifier(col), t=sql.Identifier(schema, rel), lim=sql.Literal(SAMPLE)))
        if top and top[0][2] <= DIM_MAX:
            cands.append((col, top[0][2], ", ".join(f"{v} ({k})" for v, k, _ in top)))
    out += ["", f"후보 차원 컬럼 (앞 {SAMPLE}행 표본에서 고유값 {DIM_MAX}개 이하, 기관/주기/지역/제조사 후보):", ""]
    out += table(["column", "표본 고유값", "상위 값 (건수)"], cands)


def ext_state(st: dict, name: str) -> str:
    if "ext" not in st:
        return "확인 실패 (§7 오류)"
    if name not in st["ext"]:
        return "서버에 없음 → ILIKE만" if name == "pg_trgm" else "서버에 없음"
    if st["ext"][name]:
        return "설치됨"
    return "이 계정으로 설치 가능" if st.get(f"create_{name}") == "OK" else "DBaaS 팀 요청 필요"


def s_verdict(cur, out, st):
    schema_ok = bool(st.get("db_create")) and st.get("schema") == "OK"
    table_ok = "OK" in (st.get("tbl_public"), st.get("tbl_cur"))
    trgm, vec = ext_state(st, "pg_trgm"), ext_state(st, "vector")
    yn = {True: "예", False: "아니오"}
    out += [
        f"- 스키마 분리 가능: {yn[schema_ok]}",
        f"- 같은 스키마에 테이블 추가 가능: {yn[table_ok]}",
        f"- 임시 테이블 가능: {yn[st.get('temp') == 'OK']}",
        f"- 부분일치 검색 인덱스(pg_trgm): {trgm}",
        f"- 의미 검색(pgvector): {vec}",
        "- DBaaS 팀에 물어볼 것:",
    ]
    asks = []
    if not schema_ok:
        asks.append("스키마 생성 권한 또는 전용 스키마 1개")
    if not table_ok:
        asks.append("테이블 생성 권한 (없으면 테이블별로 생성 요청: reports_report, reports_chunk, firm_narrative)")
    for state, label in ((trgm, "pg_trgm 확장 활성화"), (vec, "pgvector 확장 활성화")):
        if state == "DBaaS 팀 요청 필요":
            asks.append(label)
        elif state.startswith("서버에 없음"):
            asks.append(f"{label} (서버에 설치 파일 없음: 설치 가능 여부)")
    out += [f"  - {a}" for a in asks] or ["  - 없음"]


SECTIONS = [
    ("## 1. 서버", s_server),
    ("## 2. 역할", s_role),
    ("## 3. 데이터베이스 권한", s_db_priv),
    ("## 4. 스키마 권한", s_schemas),
    ("## 5. 보이는 테이블", s_tables),
    ("## 6. 생성 테스트 (모두 롤백됨)", s_create),
    ("## 7. 확장", s_ext),
    ("## 8. 한국어 검색 테스트", s_korean),
    ("## 9. 대상 테이블 프로필", s_profile),
    ("## 10. 판정", s_verdict),
]


def run(conn, table_name: str, env: str, dsn: str) -> list[str]:
    st: dict = {"dsn": dsn, "table": table_name}
    out = ["# DB 상황 확인 보고서", "", f"- 접속 환경변수: {env}", "- 이 보고서를 만들며 실행한 모든 변경은 롤백됨"]
    cur = conn.cursor()
    cur.execute("SET LOCAL statement_timeout = 60000")
    for n, (title, fn) in enumerate(SECTIONS, 1):
        out += ["", title, ""]
        cur.execute(f"SAVEPOINT s{n}")
        try:
            fn(cur, out, st)
        except Exception as e:
            out.append(f"오류: {type(e).__name__}: {redact(first_line(e), dsn)}")
            cur.execute(f"ROLLBACK TO SAVEPOINT s{n}")
        else:
            if n != 7:  # §7 keeps pg_trgm alive for §8
                cur.execute(f"ROLLBACK TO SAVEPOINT s{n}")
        if n == 8:
            cur.execute("ROLLBACK TO SAVEPOINT s7")
    return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="db_check.py", description=__doc__)
    p.add_argument("--table", default="smartphone_market_data")
    p.add_argument("--out", type=Path, default=Path("db_check_report.md"))
    a = p.parse_args(argv)
    env = next((e for e in ENV_VARS if os.environ.get(e)), None)
    if not env:
        print("[db_check] 환경변수 MI_DB_CHECK (또는 MI_DB_SMARTPHONE) 가 설정되지 않았습니다. "
              "docs/handoff/db-capability-check.md 안내대로 이 터미널에서만 설정한 뒤 다시 실행하세요.", file=sys.stderr)
        return 2
    dsn = os.environ[env]
    if dsn.startswith(("postgres://", "postgresql://")) and "@" in dsn.rsplit("@", 1)[0]:
        print(f"[db_check] 환경변수 {env} 의 비밀번호에 '@' 가 있습니다. URL 인코딩(%40)해서 다시 설정하세요.", file=sys.stderr)
        return 2
    try:
        conn = psycopg.connect(dsn, connect_timeout=10, autocommit=False)
    except Exception as e:
        print(f"[db_check] {type(e).__name__}: {redact(str(e), dsn)}", file=sys.stderr)
        return 1
    try:
        out = run(conn, a.table, env, dsn)
    except Exception as e:  # e.g. connection lost mid-run: class + masked message only
        print(f"[db_check] {type(e).__name__}: {redact(str(e), dsn)}", file=sys.stderr)
        return 1
    finally:
        with contextlib.suppress(Exception):  # a dead connection is rolled back by the server
            conn.rollback()  # nothing persists
        conn.close()
    text = "\n".join(out) + "\n"
    print(text, end="")
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"[db_check] 보고서 저장: {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
