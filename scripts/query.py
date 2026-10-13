#!/usr/bin/env python
"""mi-sonar: read-only access to registered data sources for Claude/OpenCode agents.

Commands: sources | schema | sql | ls | fetch   (run with -h for usage)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"
DEFAULT_LIMIT = 200
MAX_LIMIT = 5000
TIMEOUT_MS = 30_000
LS_MAX = 200


class SonarError(Exception):
    """User-facing error. code: 1 runtime, 2 env missing, 3 SQL rejected."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


# ---------- sources ----------

def parse_front_matter(text: str) -> dict:
    """Minimal YAML header parser: `key: value` and `key: [a, b]` only."""
    m = re.match(r"\s*---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            out[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = val
    return out


def load_sources(dir: Path = SOURCES_DIR) -> dict[str, dict]:
    sources: dict[str, dict] = {}
    for p in sorted(Path(dir).glob("*.md")):
        fm = parse_front_matter(p.read_text(encoding="utf-8"))
        name = fm.get("name") or p.stem
        fm["name"] = name
        fm["path"] = p
        sources[name] = fm
    return sources


def get_source(name: str, sources: dict | None = None) -> dict:
    sources = sources if sources is not None else load_sources()
    if name not in sources:
        raise SonarError(f"알 수 없는 소스: {name}. 사용 가능: {', '.join(sources) or '(없음)'}", 1)
    src = dict(sources[name])
    env = src.get("env", "")
    conn = os.environ.get(env, "")
    if not conn:
        raise SonarError(
            f"환경변수 {env} 가 설정되지 않았습니다. README의 설치 한 줄을 다시 실행하고 새 터미널을 여세요.",
            2,
        )
    src["conn"] = conn
    return src


# ---------- SQL guard / output ----------

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|COPY)\b", re.I
)


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def check_sql(sql: str) -> str:
    """Return a cleaned single read-only statement or raise SonarError(code=3)."""
    s = strip_comments(sql)
    if s.endswith(";"):
        s = s[:-1].rstrip()
    if not s:
        raise SonarError("SQL이 비어 있습니다.", 3)
    if ";" in s:
        raise SonarError("SQL 문장은 하나만 허용됩니다 (세미콜론은 끝에 하나만).", 3)
    if not re.match(r"(?is)^(SELECT|WITH)\b", s):
        raise SonarError("SELECT 또는 WITH로 시작하는 조회만 허용됩니다.", 3)
    m = FORBIDDEN.search(s)  # ponytail: also hits words inside string literals; agent rewrites the literal
    if m:
        raise SonarError(
            f"허용되지 않는 키워드: {m.group(1).upper()} (문자열 안에 있다면 다른 표현으로 바꾸세요)", 3
        )
    return s


def _cell(v) -> str:
    if v is None:
        return ""
    return str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def format_table(cols: list[str], rows: list[tuple]) -> str:
    head = "| " + " | ".join(_cell(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(_cell(v) for v in r) + " |" for r in rows]
    if not body:
        body = ["(0 rows)"]
    return "\n".join([head, sep, *body])


# ---------- postgres ----------

def connect_pg(dsn: str):
    import psycopg  # lazy: `sources` and unit tests run without the driver

    conn = psycopg.connect(dsn, options=f"-c statement_timeout={TIMEOUT_MS}", autocommit=False)
    conn.read_only = True
    return conn


def clamp_limit(n: int) -> tuple[int, str]:
    if n <= 0:
        raise SonarError("--limit 은 1 이상이어야 합니다.", 3)
    if n > MAX_LIMIT:
        return MAX_LIMIT, f"(--limit 이 최대값 {MAX_LIMIT} 으로 조정됨)"
    return n, ""


def run_sql(src: dict, sql: str, limit: int) -> tuple[list[str], list[tuple], bool]:
    stmt = check_sql(sql)
    with connect_pg(src["conn"]) as conn:
        with conn.cursor(name="mi_sonar") as cur:  # server-side cursor: never pulls the whole table
            cur.execute(stmt)
            rows = cur.fetchmany(limit + 1)
            cols = [d.name for d in cur.description]
    truncated = len(rows) > limit
    return cols, rows[:limit], truncated


def cmd_sql(src: dict, sql: str, limit: int, csv_path: Path | None) -> str:
    limit, notice = clamp_limit(limit)
    cols, rows, truncated = run_sql(src, sql, limit)
    parts = [format_table(cols, rows), f"({len(rows)} rows)"]
    if notice:
        parts.append(notice)
    if truncated:
        parts.append(
            f"결과가 {limit}행에서 잘렸습니다. SQL에서 집계(GROUP BY)하거나 --limit/--csv 를 사용하세요."
        )
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        parts.append(f"CSV 저장: {csv_path}")
    return "\n".join(parts)


def cmd_schema(src: dict) -> str:
    from psycopg import sql as pgsql

    tables = src.get("tables") or []
    out = []
    with connect_pg(src["conn"]) as conn:
        with conn.cursor() as cur:
            if not tables:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' ORDER BY 1"
                )
                tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name=%s ORDER BY ordinal_position",
                    (t,),
                )
                cols = cur.fetchall()
                out.append(f"## {t}\n" + format_table(["column", "type", "nullable"], cols))
                cur.execute(pgsql.SQL("SELECT * FROM {} LIMIT 3").format(pgsql.Identifier(t)))
                sample = cur.fetchall()
                out.append("샘플 3행:\n" + format_table([d.name for d in cur.description], sample))
    return "\n\n".join(out)


# ---------- minio ----------

def parse_minio_url(url: str) -> dict:
    u = urlparse(url)
    bucket = u.path.strip("/")
    if u.scheme not in ("http", "https") or not u.username or not u.password or not u.hostname or not bucket:
        raise SonarError("MI_MINIO 형식은 http(s)://ACCESS:SECRET@host:port/bucket 이어야 합니다.", 2)
    endpoint = u.hostname + (f":{u.port}" if u.port else "")
    return {
        "endpoint": endpoint,
        "access": unquote(u.username),
        "secret": unquote(u.password),
        "bucket": bucket,
        "secure": u.scheme == "https",
    }


def connect_minio(url: str):
    from minio import Minio

    c = parse_minio_url(url)
    client = Minio(c["endpoint"], access_key=c["access"], secret_key=c["secret"], secure=c["secure"])
    return client, c["bucket"]


def cmd_ls(src: dict, prefix: str) -> str:
    client, bucket = connect_minio(src["conn"])
    rows = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        rows.append((obj.object_name, obj.size, str(obj.last_modified)[:19]))
        if len(rows) >= LS_MAX:
            break
    if len(rows) >= LS_MAX:
        tail = f"({len(rows)} objects, 최대 {LS_MAX}개까지만 표시. 접두어를 좁히세요)"
    else:
        tail = f"({len(rows)} objects)"
    return format_table(["key", "size", "modified"], rows) + "\n" + tail


def cmd_fetch(src: dict, key: str, out: Path | None) -> str:
    client, bucket = connect_minio(src["conn"])
    dest = Path(out) if out else Path.cwd() / Path(key).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.fget_object(bucket, key, str(dest))
    return f"다운로드 완료: {dest}"


# ---------- CLI ----------

def cmd_sources(sources: dict) -> str:
    rows = []
    for s in sources.values():
        env = s.get("env", "")
        state = "설정됨" if os.environ.get(env) else "미설정"
        rows.append((s["name"], s.get("kind", "?"), env, state, s.get("summary", "")))
    return format_table(["source", "kind", "env", "status", "summary"], rows)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="query.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources", help="등록된 소스와 환경변수 상태")
    s = sub.add_parser("schema", help="테이블/컬럼/샘플 3행")
    s.add_argument("source")
    s = sub.add_parser("sql", help="읽기전용 SQL 실행")
    s.add_argument("source")
    s.add_argument("sql")
    s.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    s.add_argument("--csv", type=Path)
    s = sub.add_parser("ls", help="MinIO 객체 목록")
    s.add_argument("source")
    s.add_argument("prefix", nargs="?", default="")
    s = sub.add_parser("fetch", help="MinIO 객체 다운로드")
    s.add_argument("source")
    s.add_argument("key")
    s.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    try:
        if a.cmd == "sources":
            print(cmd_sources(load_sources()))
            return 0
        src = get_source(a.source)
        if a.cmd == "schema":
            print(cmd_schema(src))
        elif a.cmd == "sql":
            print(cmd_sql(src, a.sql, a.limit, a.csv))
        elif a.cmd == "ls":
            print(cmd_ls(src, a.prefix))
        elif a.cmd == "fetch":
            print(cmd_fetch(src, a.key, a.out))
        return 0
    except SonarError as e:
        print(f"[mi-sonar] {e}", file=sys.stderr)
        return e.code
    except Exception as e:  # driver/network errors: class + message only, never the DSN
        print(f"[mi-sonar] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
