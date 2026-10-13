#!/usr/bin/env python
"""mi-sonar load_smartwatch: smartwatch market CSVs -> sales_team.smartwatch_market_data (owner only).

Subcommands: check (validate only), load (validate, then insert), latest (newest published_month per key).
Write credentials come only from an env var (e.g. MI_DB_REPORTS_WRITE) and are never printed. Run with -h for usage.
"""
from __future__ import annotations

import argparse
import csv
import importlib
import os
import re
import sys
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "staging"
TABLE = "sales_team.smartwatch_market_data"
LATEST_LIMIT = 200
HEADER = ["dataset", "firm", "period", "country", "vendor", "sell_in_mu", "revenue_musd", "asp_usd",
          "published_month", "note"]
DATASETS = ("actual", "forecast", "our_tam")
VENDORS = ("Apple", "Samsung", "Huawei", "Garmin", "Fitbit", "Others")
KEY = ("dataset", "firm", "period", "country", "vendor", "published_month")


class LoaderError(Exception):
    """User-facing error. code: 1 validation/runtime, 2 setup missing (env var, package)."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def need(module: str):
    """Lazy import of a dev-only package; a missing one is a setup error (exit 2)."""
    try:
        return importlib.import_module(module)
    except ImportError:
        raise LoaderError(f"{module} 패키지가 없습니다: pip install -r requirements-dev.txt", 2) from None


def redact(text: str, conn: str | None) -> str:
    """Mask the conn string and its password (raw and URL-decoded) in an error message."""
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


# ---------- CSV validation ----------

def _num(v: str) -> Decimal | None:
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def validate_row(r: dict) -> tuple[dict | None, list[str]]:
    """One CSV row (already trimmed) -> (normalized row, errors). Row is None when there are errors."""
    errs: list[str] = []
    ds = r["dataset"]
    if ds not in DATASETS:
        return None, [f"dataset 은 {'/'.join(DATASETS)} 중 하나여야 합니다: '{ds}'"]
    firm = r["firm"] or ("MI" if ds == "our_tam" else "TechInsights")
    period, country, vendor = r["period"], r["country"], r["vendor"]
    if not re.fullmatch(r"\d{4}" if ds == "forecast" else r"\d{4}Q[1-4]", period):
        errs.append(f"period 형식 오류 ('{period}'): {'YYYY' if ds == 'forecast' else 'YYYYQn'} 이어야 합니다")
    if not country:
        errs.append("country 가 비어 있습니다")
    elif ds == "our_tam" and country != "Worldwide":
        errs.append(f"our_tam 의 country 는 Worldwide 여야 합니다: '{country}'")
    if vendor not in VENDORS:
        errs.append(f"vendor 는 {'/'.join(VENDORS)} 중 하나여야 합니다: '{vendor}'")
    sell = rev = asp = None
    if ds == "forecast":
        rev, asp = _num(r["revenue_musd"]), _num(r["asp_usd"])
        ok = True
        if rev is None or rev <= 0:
            ok = False
            errs.append(f"forecast 는 revenue_musd 가 0 보다 큰 숫자여야 합니다: '{r['revenue_musd']}'")
        if asp is None or asp <= 0:
            ok = False
            errs.append(f"forecast 는 asp_usd 가 0 보다 큰 숫자여야 합니다: '{r['asp_usd']}'")
        if ok:
            sell = round(rev / asp, 3)
            if r["sell_in_mu"]:
                given = _num(r["sell_in_mu"])
                if given is None or abs(given - sell) > sell / 100:
                    errs.append(f"sell_in_mu '{r['sell_in_mu']}' 가 revenue_musd/asp_usd = {sell} 와 1% 넘게 다릅니다")
                else:
                    sell = given
    else:
        sell = _num(r["sell_in_mu"])
        if sell is None or sell < 0:
            errs.append(f"{ds} 는 sell_in_mu 가 0 이상 숫자여야 합니다: '{r['sell_in_mu']}'")
        if r["revenue_musd"] or r["asp_usd"]:
            errs.append(f"{ds} 는 revenue_musd/asp_usd 를 비워야 합니다")
    pm = None
    try:
        pm = date.fromisoformat(r["published_month"])
        if pm.day != 1:
            errs.append(f"published_month 는 매월 1일이어야 합니다: '{r['published_month']}'")
    except ValueError:
        errs.append(f"published_month 가 ISO 날짜(YYYY-MM-01)가 아닙니다: '{r['published_month']}'")
    if errs:
        return None, errs
    return {"dataset": ds, "firm": firm, "period": period, "country": country, "vendor": vendor,
            "sell_in_mu": sell, "revenue_musd": rev, "asp_usd": asp, "published_month": pm,
            "note": r["note"] or None}, []


def read_csv(path: Path) -> tuple[list[dict], list[str]]:
    """Validate a whole file. Returns (rows, errors); errors name the file and row number."""
    try:
        f = open(path, newline="", encoding="utf-8-sig")
    except OSError as e:
        raise LoaderError(f"파일을 열 수 없습니다: {path} ({e.strerror})") from None
    with f:
        try:
            rd = csv.reader(f)
            head = [h.strip() for h in next(rd, [])]
            if head != HEADER:
                return [], [f"{path.name}: 헤더가 다릅니다. 기대: {','.join(HEADER)}"]
            rows, errs, seen = [], [], {}
            for n, cells in enumerate(rd, 2):
                if not any(c.strip() for c in cells):
                    continue
                if len(cells) != len(HEADER):
                    errs.append(f"{path.name} 행 {n}: 열 수가 {len(cells)} 개입니다 (기대 {len(HEADER)})")
                    continue
                row, e = validate_row(dict(zip(HEADER, (c.strip() for c in cells))))
                errs += [f"{path.name} 행 {n}: {m}" for m in e]
                if row:
                    k = tuple(row[c] for c in KEY)
                    if k in seen:
                        errs.append(f"{path.name} 행 {n}: 행 {seen[k]} 와 중복 키 {tuple(map(str, k))}")
                    else:
                        seen[k] = n
                        rows.append(row)
        except (csv.Error, UnicodeDecodeError) as e:
            return [], [f"{path.name}: CSV 를 읽을 수 없습니다 ({type(e).__name__}: {e})"]
    return rows, errs


def read_all(paths: list[Path]) -> list[tuple[Path, list[dict]]]:
    """Validate every file; any error anywhere -> print all of them and raise (nothing is written)."""
    out, errs = [], []
    for p in paths:
        rows, e = read_csv(p)
        out.append((p, rows))
        errs += e
    if errs:
        for e in errs:
            print(f"ERR {e}", file=sys.stderr)
        raise LoaderError(f"검증 실패: 오류 {len(errs)} 건. 아무것도 적재하지 않았습니다.")
    return out


def _cell(v) -> str:
    return "" if v is None else str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def md_table(cols: list[str], rows: list[tuple]) -> list[str]:
    if not rows:
        return ["(없음)"]
    return ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols),
            *("| " + " | ".join(_cell(v) for v in r) + " |" for r in rows)]


def cmd_check(paths: list[Path]) -> int:
    files = read_all(paths)
    cnt = Counter((r["dataset"], r["period"], r["published_month"]) for _, rows in files for r in rows)
    print("\n".join(md_table(["dataset", "period", "published_month", "rows"],
                             [(*k, n) for k, n in sorted(cnt.items())])))
    print(f"(파일 {len(files)}, 행 {sum(cnt.values())}, 검증 통과)")
    return 0


# ---------- DB ----------

DDL = f"""
CREATE SCHEMA IF NOT EXISTS sales_team;
CREATE TABLE IF NOT EXISTS {TABLE} (
  id              SERIAL PRIMARY KEY,
  dataset         VARCHAR(20)  NOT NULL DEFAULT 'actual',
  firm            VARCHAR(50)  NOT NULL DEFAULT 'TechInsights',
  period          VARCHAR(6)   NOT NULL,
  country         VARCHAR(50)  NOT NULL,
  vendor          VARCHAR(20)  NOT NULL,
  sell_in_mu      NUMERIC(8,3),
  revenue_musd    NUMERIC(12,3),
  asp_usd         NUMERIC(8,2),
  published_month DATE         NOT NULL,
  note            TEXT,
  loaded_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (dataset, firm, period, country, vendor, published_month)
);
"""
INSERT = (f"INSERT INTO {TABLE} ({', '.join(HEADER)}) VALUES ({', '.join(f'%({c})s' for c in HEADER)}) "
          f"ON CONFLICT ({', '.join(KEY)}) DO NOTHING")


def connect(dsn: str, create: bool):
    """Open the connection (autocommit); in local mode create the schema/table, else require the table."""
    psycopg = need("psycopg")
    conn = psycopg.connect(dsn, connect_timeout=10, autocommit=True,
                           prepare_threshold=None)  # no server-side prepare: safe behind PgBouncer transaction pooling
    try:
        if create:
            conn.execute(DDL)
        elif conn.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
            raise LoaderError(f"{TABLE} 테이블이 아직 없습니다 (DBaaS 팀 생성 대기). 그동안은 --local 로 쌓으세요.", 1)
    except BaseException:
        conn.close()
        raise
    return conn


def with_db(staging: Path, local: bool, dsn_env: str | None, fn) -> int:
    """Call fn(connection, target name) against the local pgserver or the company DB named by dsn_env."""
    if local:
        pgserver = need("pgserver")
        pgdata = staging / "localpg"
        staging.mkdir(parents=True, exist_ok=True)  # pgserver needs the parent dir to exist
        try:
            srv = pgserver.get_server(pgdata)
        except UnicodeDecodeError:  # ponytail: pgserver 0.1.4 decodes initdb output as cp949; initdb already succeeded
            # pgserver registered the half-built instance before failing: drop it or the retry returns it unstarted
            pgserver.postgres_server.PostgresServer._instances.pop(pgdata.resolve(), None)
            srv = pgserver.get_server(pgdata)
        with srv:  # stops on exit, data stays in staging/localpg
            return fn(connect(srv.get_uri(), True), "local")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dsn_env or ""):  # never echo the value: it may be a pasted DSN
        raise LoaderError("--dsn-env 에는 환경변수 이름을 주세요", 2)
    dsn = os.environ.get(dsn_env, "")
    if not dsn:
        raise LoaderError(f"환경변수 {dsn_env} 가 설정되지 않았습니다 (이 터미널에서만 설정하세요).", 2)
    if dsn.startswith(("postgres://", "postgresql://")) and "@" in dsn.rsplit("@", 1)[0]:
        raise LoaderError(f"환경변수 {dsn_env} 의 비밀번호에 '@' 가 있습니다. URL 인코딩(%40)해서 다시 등록하세요.", 2)
    return fn(connect(dsn, False), dsn_env)


def cmd_load(staging: Path, local: bool, dsn_env: str | None, paths: list[Path]) -> int:
    files = read_all(paths)  # validate everything before touching any DB

    def run(conn, target):
        ins = skip = fail = 0
        with conn:
            for p, rows in files:
                try:
                    with conn.transaction():  # one file = one transaction
                        n = sum(conn.execute(INSERT, r).rowcount for r in rows)
                except Exception as e:
                    fail += len(rows)
                    print(f"FAIL {p.name}: {type(e).__name__}: {redact(str(e), os.environ.get(dsn_env or ''))}")
                    continue
                ins, skip = ins + n, skip + len(rows) - n
                print(f"{p.name}: 적재 {n}, 건너뜀 {len(rows) - n}")
        print(f"({target}: 적재 {ins}, 건너뜀 {skip}, 실패 {fail})")
        return 1 if fail else 0

    return with_db(staging, local, dsn_env, run)


def cmd_latest(staging: Path, local: bool, dsn_env: str | None, dataset: str | None) -> int:
    sql = (f"SELECT DISTINCT ON (dataset, period, country, vendor) dataset, firm, period, country, vendor, "
           f"sell_in_mu, revenue_musd, asp_usd, published_month FROM {TABLE} "
           f"WHERE (%(d)s::text IS NULL OR dataset = %(d)s) "
           f"ORDER BY dataset, period, country, vendor, published_month DESC")

    def run(conn, target):
        with conn:
            rows = conn.execute(sql, {"d": dataset}).fetchall()
        print("\n".join(md_table(["dataset", "firm", "period", "country", "vendor", "sell_in_mu",
                                  "revenue_musd", "asp_usd", "published_month"], rows[:LATEST_LIMIT])))
        omitted = len(rows) - LATEST_LIMIT
        print(f"(총 {len(rows)} 행" + (f", {omitted} 행 생략" if omitted > 0 else "") + ")")
        return 0

    return with_db(staging, local, dsn_env, run)


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="load_smartwatch.py", description=__doc__)
    p.add_argument("--staging", type=Path, default=STAGING, help="--local 용 작업 폴더 (기본: 저장소의 staging/)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check", help="CSV 검증만 하고 요약 표 출력")
    s.add_argument("csv", nargs="+", type=Path)
    s_load = sub.add_parser("load", help="검증 후 DB에 적재 (이미 있는 키는 건너뜀)")
    s_load.add_argument("csv", nargs="+", type=Path)
    s_latest = sub.add_parser("latest", help="(dataset, period, country, vendor) 별 최신 발행월 행 출력")
    s_latest.add_argument("--dataset", choices=DATASETS)
    for s in (s_load, s_latest):
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--local", action="store_true", help="staging/localpg 내장 PostgreSQL")
        g.add_argument("--dsn-env", help="DSN이 든 환경변수 이름 (예: MI_DB_REPORTS_WRITE)")
    a = p.parse_args(argv)
    try:
        if a.cmd == "check":
            return cmd_check(a.csv)
        if a.cmd == "load":
            return cmd_load(a.staging, a.local, a.dsn_env, a.csv)
        return cmd_latest(a.staging, a.local, a.dsn_env, a.dataset)
    except LoaderError as e:
        print(f"[load_smartwatch] {e}", file=sys.stderr)
        return e.code
    except Exception as e:  # driver/network errors: class + masked message, never a DSN or secret
        env = getattr(a, "dsn_env", None)
        print(f"[load_smartwatch] {type(e).__name__}: {redact(str(e), os.environ.get(env) if env else None)}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
