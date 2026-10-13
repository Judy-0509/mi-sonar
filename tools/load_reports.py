#!/usr/bin/env python
"""mi-sonar load_reports: broker research PDFs -> staging/ -> sales_team.nasdaq_report_doc (owner only).

Stages: extract (program) -> triage (agent) -> annotate (agent) -> load (program). Run with -h for usage.
Write credentials come only from env vars (MI_DB_REPORTS_WRITE, MI_MINIO_WRITE) and are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "staging"
TABLE = "sales_team.nasdaq_report_doc"
MINIO_ENV = "MI_MINIO_WRITE"
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


class LoaderError(Exception):
    """User-facing error. code: 1 runtime, 2 setup missing (env var, package)."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


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


# ---------- file identity ----------

NAME_RE = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4})_\d{2}-\d{2}-\d{2}-(.+)\.pdf$", re.I)
TICKER_RE = re.compile(r"^[A-Z0-9.]{1,10}$")
MARKET_RE = re.compile(r"^[A-Z]{1,4}$")


def parse_filename(name: str) -> dict:
    """`DD-Mon-YYYY_HH-MM-SS-[TICKER-MARKET-]FIRM[-TITLE].pdf` -> published_on, ticker, market, firm, title."""
    m = NAME_RE.match(name)
    if not m or m.group(2).lower() not in MONTHS:
        raise ValueError(f"파일명 형식 불일치: {name}")
    day, mon, year, rest = m.groups()
    parts = rest.split("-")
    ticker = market = None
    if len(parts) >= 3 and TICKER_RE.match(parts[0]) and MARKET_RE.match(parts[1]):
        ticker, market, parts = parts[0], parts[1], parts[2:]
    if not parts[0]:
        raise ValueError(f"파일명에 증권사 없음: {name}")
    return {
        "published_on": date(int(year), MONTHS[mon.lower()], int(day)).isoformat(),
        "ticker": ticker,
        "market": market,
        "firm": " ".join(parts[0].replace("_", " ").split()),
        "title": " ".join("-".join(parts[1:]).replace("_", " ").split()) or None,
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------- text cleanup (pure functions on page strings) ----------

CUT_RE = re.compile(r"^[ \t]*(analyst certification|important disclosures)\b", re.I | re.M)
PAGE_NO_RE = re.compile(r"^\s*\d{1,4}\s*$")
BULLET_RE = re.compile(r"^([•●▪■◦·*\-–]|\d{1,2}[.)])\s")
PARA_END = (".", ":", "?", "!")
URL_RE = re.compile(r"https?://|www\.", re.I)
SMARTPHONE_WORDS = ("smartphone", "handset", "iphone", "galaxy", "pixel", "snapdragon",
                    "exynos", "dimensity", "mediatek", "shipments", "sell-through", "units")


def _norm(line: str) -> str:
    return " ".join(line.split())


def strip_repeated_lines(pages: list[str], threshold: float = 0.6) -> list[str]:
    """Drop header/footer lines found on >= threshold of the pages (only for 3+ pages)."""
    if len(pages) < 3:
        return pages
    seen = Counter(k for page in pages for k in {_norm(line) for line in page.splitlines()} if k)
    drop = {k for k, n in seen.items() if n >= threshold * len(pages)}
    return ["\n".join(line for line in page.splitlines() if _norm(line) not in drop) for page in pages]


def cut_disclosure(pages: list[str]) -> tuple[list[str], str | None]:
    """Cut everything from the first `Analyst Certification` / `Important Disclosures` line on page 2+."""
    for i, page in enumerate(pages[1:], 1):  # page 1 often says "see important disclosures": never cut there
        m = CUT_RE.search(page)
        if m:
            head = page[:m.start()].strip()
            return pages[:i] + ([head] if head else []), m.group(1)
    return pages, None


def strip_page_numbers(page: str) -> str:
    return "\n".join(line for line in page.splitlines() if not PAGE_NO_RE.match(line))


def join_wraps(text: str) -> str:
    """Re-join hard-wrapped lines: one paragraph per line. A paragraph ends after a line ending in
    . : ? ! and before a bullet line; a line ending in '-' joins the next without a space."""
    paras: list[str] = []
    cur = ""
    for raw in text.splitlines():
        line = _norm(raw)
        if cur and (not line or BULLET_RE.match(line)):
            paras.append(cur)
            cur = ""
        if not line:
            continue
        cur = cur + line if cur.endswith("-") else f"{cur} {line}".strip()
        if cur.endswith(PARA_END):
            paras.append(cur)
            cur = ""
    if cur:
        paras.append(cur)
    return "\n".join(paras)


def render_body(pages: list[str]) -> str:
    """Cleaned pages -> one text with a `[p.N]` line before each non-empty page (N = PDF page number)."""
    out = []
    for n, page in enumerate(pages, 1):
        text = join_wraps(strip_page_numbers(unicodedata.normalize("NFKC", page)))  # NFKC: ligatures like ﬁ -> fi
        if text:
            out.append(f"[p.{n}]\n{text}")
    return "\n".join(out) + "\n" if out else ""


def url_count(text: str) -> int:
    return len(URL_RE.findall(text))


def smartphone_hits(text: str) -> int:
    low = text.lower()
    return sum(low.count(w) for w in SMARTPHONE_WORDS)


# ---------- extract ----------

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else None


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_pages(pdf: Path) -> tuple[list[str], str]:
    """Page texts via pdfplumber, else pypdf (lazy imports). Returns (pages, extractor name)."""
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        with pdfplumber.open(pdf) as doc:
            return [p.extract_text() or "" for p in doc.pages], "pdfplumber"
    try:
        from pypdf import PdfReader
    except ImportError:
        raise LoaderError("PDF 추출 라이브러리가 없습니다: pip install -r requirements-dev.txt", 2) from None
    return [p.extract_text() or "" for p in PdfReader(pdf).pages], "pypdf"


def extract_one(pdf: Path, staging: Path, force: bool) -> str:
    info = parse_filename(pdf.name)
    sha = file_sha256(pdf)
    rid = sha[:12]
    d = staging / rid
    old = read_json(d / "meta.json")
    if old and not force:
        return f"skip {rid} (이미 추출됨) {pdf.name}"
    raw, extractor = read_pages(pdf)
    pages, heading = cut_disclosure(strip_repeated_lines(raw))
    body = render_body(pages)
    meta = {
        "id": rid,
        "file_sha256": sha,
        "source_path": str(pdf.resolve()),
        **info,
        "pages": len(raw),
        "body_pages": len(pages),
        "cut_heading": heading,
        "chars": len(body),
        "url_count": url_count(body),
        "smartphone_hits": smartphone_hits(body),
        "extractor": extractor,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "loaded": (old or {}).get("loaded", {}),
    }
    d.mkdir(parents=True, exist_ok=True)
    (d / "text.txt").write_text(body, encoding="utf-8")
    write_json(d / "meta.json", meta)
    return (f"ok   {rid} {info['published_on']} {info['firm']} pages={len(raw)} body={len(pages)} "
            f"cut={heading or '-'} phone={meta['smartphone_hits']} url={meta['url_count']} {pdf.name}")


def cmd_extract(staging: Path, paths: list[Path], force: bool) -> int:
    pdfs: list[Path] = []
    for p in paths:
        pdfs += sorted(f for f in p.iterdir() if f.suffix.lower() == ".pdf") if p.is_dir() else [p]
    failed = 0
    for pdf in pdfs:
        try:
            print(extract_one(pdf, staging, force))
        except LoaderError:
            raise
        except Exception as e:  # one bad PDF must not stop the batch
            failed += 1
            print(f"FAIL {pdf.name}: {type(e).__name__}: {e}")
    print(f"(PDF {len(pdfs)}개, 실패 {failed}개)")
    return 1 if failed else 0


# ---------- triage / annotate files ----------

KINDS = ("link_digest", "weekly_note", "company_update", "industry_deep_dive", "mgmt_meeting", "other")
RELEVANCE = ("high", "medium", "low")
TOPICS = ("스마트폰", "AP", "메모리", "카메라", "디스플레이", "모뎀", "파운드리", "OEM", "공급망", "거시")
TRIAGE_KEYS = {"kind", "relevance", "reason", "load"}
ANNOTATE_KEYS = {"title", "ticker", "analyst", "summary_ko", "summary_en", "keywords_ko", "keywords_en",
                 "topics", "key_numbers"}


def _line(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and "\n" not in v


def validate_triage(t) -> list[str]:
    if not isinstance(t, dict):
        return ["JSON 객체가 아닙니다"]
    errs = [f"모르는 키: {k}" for k in sorted(set(t) - TRIAGE_KEYS)]
    if t.get("kind") not in KINDS:
        errs.append(f"kind 는 {', '.join(KINDS)} 중 하나")
    if t.get("relevance") not in RELEVANCE:
        errs.append(f"relevance 는 {', '.join(RELEVANCE)} 중 하나")
    if not _line(t.get("reason")):
        errs.append("reason 은 비어 있지 않은 한 줄")
    if "load" in t and not isinstance(t["load"], bool):
        errs.append("load 는 true 또는 false (사용자만 씀)")
    return errs


def decide(t: dict) -> bool:
    """Load rule: relevance high/medium and not a link digest. A user-written `load` overrides it."""
    if isinstance(t.get("load"), bool):
        return t["load"]
    return t["relevance"] in ("high", "medium") and t["kind"] != "link_digest"


def _words(v) -> bool:
    return isinstance(v, list) and 1 <= len(v) <= 10 and all(_line(x) and "," not in x for x in v)


def validate_annotate(a, meta: dict) -> list[str]:
    if not isinstance(a, dict):
        return ["JSON 객체가 아닙니다"]
    errs = [f"모르는 키: {k}" for k in sorted(set(a) - ANNOTATE_KEYS)]
    title = a.get("title") or meta.get("title")
    if not (_line(title) and len(title) <= 300):
        errs.append("title 은 300자 이하 한 줄 (파일명에 제목이 없으면 필수)")
    for key, limit in (("ticker", 20), ("analyst", 100)):
        if key in a and not (_line(a[key]) and len(a[key]) <= limit):
            errs.append(f"{key} 는 {limit}자 이하 한 줄 (모르면 키를 빼세요)")
    ko = a.get("summary_ko")
    if not (isinstance(ko, list) and len(ko) == 3 and all(_line(x) for x in ko)):
        errs.append("summary_ko 는 한 줄짜리 한국어 문장 3개의 목록")
    if not _line(a.get("summary_en")):
        errs.append("summary_en 은 영어 한 줄")
    for key in ("keywords_ko", "keywords_en"):
        if not _words(a.get(key)):
            errs.append(f"{key} 는 쉼표 없는 한 줄 단어 1~10개의 목록")
    kws = [a.get("keywords_ko"), a.get("keywords_en")]
    if all(_words(k) for k in kws) and len(", ".join(kws[0] + kws[1])) > 500:
        errs.append("keywords_ko + keywords_en 합계가 500자를 넘습니다")
    topics = a.get("topics")
    if not (isinstance(topics, list) and topics and len(set(topics)) == len(topics)
            and all(x in TOPICS for x in topics)):
        errs.append(f"topics 는 다음 중 1개 이상 (중복 없이): {', '.join(TOPICS)}")
    if not isinstance(a.get("key_numbers"), str):
        errs.append("key_numbers 는 문자열 (숫자가 없으면 빈 문자열)")
    return errs


def report_state(d: Path) -> dict:
    """Everything known about one staging/<id>/ folder; JSON errors become validation errors."""
    s = {"id": d.name, "dir": d, "meta": read_json(d / "meta.json"), "triage": None, "t_err": [],
         "load": None, "annotate": None, "a_err": []}
    try:
        s["triage"] = read_json(d / "triage.json")
    except ValueError as e:
        s["t_err"] = [f"JSON 오류: {e}"]
    if s["triage"] is not None:
        s["t_err"] = validate_triage(s["triage"])
        if not s["t_err"]:
            s["load"] = decide(s["triage"])
    if s["load"]:
        try:
            s["annotate"] = read_json(d / "annotate.json")
        except ValueError as e:
            s["a_err"] = [f"JSON 오류: {e}"]
        if s["annotate"] is not None:
            s["a_err"] = validate_annotate(s["annotate"], s["meta"])
    return s


def all_states(staging: Path) -> list[dict]:
    dirs = [d for d in staging.iterdir() if (d / "meta.json").exists()] if staging.exists() else []
    return sorted((report_state(d) for d in dirs),
                  key=lambda s: (s["meta"]["published_on"], s["meta"]["firm"], s["id"]))


def _stage(obj, errs: list[str]) -> str:
    return "ERR" if errs else ("-" if obj is None else "ok")


def cmd_status(staging: Path) -> int:
    states = all_states(staging)
    for s in states:
        m = s["meta"]
        decision = "-"
        if s["load"] is not None:
            decision = ("load" if s["load"] else "skip") + ("*" if "load" in s["triage"] else "")
        annotate = _stage(s["annotate"], s["a_err"]) if s["load"] else "n/a"
        loaded = ",".join(m.get("loaded", {})) or "-"
        print(f"{s['id']} {m['published_on']} {m['firm']:<12} triage={_stage(s['triage'], s['t_err'])} "
              f"decision={decision} annotate={annotate} loaded={loaded}  {m['title'] or '(제목 없음)'}")
        for e in s["t_err"]:
            print(f"    ! triage.json: {e}")
        for e in s["a_err"]:
            print(f"    ! annotate.json: {e}")
    todo = [s for s in states if s["load"]]
    ready = [s for s in todo if s["annotate"] is not None and not s["a_err"]]
    print(f"(전체 {len(states)}, 분류됨 {sum(s['load'] is not None for s in states)}, "
          f"적재 대상 {len(todo)}, 주석 완료 {len(ready)})")
    return 0


def _cell(v) -> str:
    return "" if v is None else str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def md_table(cols: list[str], rows: list[tuple]) -> list[str]:
    if not rows:
        return ["(없음)"]
    return ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols),
            *("| " + " | ".join(_cell(v) for v in r) + " |" for r in rows)]


def cmd_triage_report(staging: Path) -> int:
    states = all_states(staging)
    groups: dict[str, list[dict]] = {"load": [], "skip": [], "todo": []}
    for s in states:
        groups["todo" if s["load"] is None else ("load" if s["load"] else "skip")].append(s)
    n = {k: len(v) for k, v in groups.items()}
    lines = [
        "# 레포트 분류 결과 (triage)",
        "",
        f"생성: {datetime.now():%Y-%m-%d %H:%M} / 전체 {len(states)}건: 적재 {n['load']}, 제외 {n['skip']}, "
        f"미분류·오류 {n['todo']}",
        "",
        "규칙: relevance 가 high 또는 medium 이고 kind 가 link_digest 가 아니면 적재합니다.",
        "결정을 바꾸려면 `staging/<id>/triage.json` 에 `\"load\": true` 또는 `\"load\": false` 를 넣고 "
        "`triage-report` 를 다시 실행하세요 (결정 칸에 `(수동)` 표시).",
        "제외된 레포트는 DB와 MinIO 어디에도 올라가지 않고 이 파일에만 기록됩니다.",
    ]
    cols = ["id", "발행일", "증권사", "티커", "제목", "종류", "관련도", "결정", "이유", "폰 단어/URL"]
    for key, label in (("load", "적재"), ("skip", "제외")):
        rows = [(s["id"], s["meta"]["published_on"], s["meta"]["firm"], s["meta"]["ticker"], s["meta"]["title"],
                 s["triage"]["kind"], s["triage"]["relevance"], label + (" (수동)" if "load" in s["triage"] else ""),
                 s["triage"]["reason"], f"{s['meta']['smartphone_hits']}/{s['meta']['url_count']}")
                for s in groups[key]]
        lines += ["", f"## {label} ({len(rows)})", "", *md_table(cols, rows)]
    rows = [(s["id"], s["meta"]["published_on"], s["meta"]["firm"], s["meta"]["title"],
             "; ".join(s["t_err"]) or "triage.json 없음") for s in groups["todo"]]
    lines += ["", f"## 미분류·오류 ({len(rows)})", "", *md_table(["id", "발행일", "증권사", "제목", "문제"], rows)]
    staging.mkdir(parents=True, exist_ok=True)
    out = staging / "triage.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"저장: {out} (적재 {n['load']}, 제외 {n['skip']}, 미분류·오류 {n['todo']})")
    return 0


# ---------- load ----------

DDL = """
CREATE SCHEMA IF NOT EXISTS sales_team;
CREATE TABLE IF NOT EXISTS sales_team.nasdaq_report_doc (
  id SERIAL PRIMARY KEY,
  firm VARCHAR(100) NOT NULL,
  published_on DATE NOT NULL,
  title VARCHAR(300) NOT NULL,
  report_type VARCHAR(50),
  topics VARCHAR(300),
  analyst VARCHAR(100),
  pages INTEGER,
  minio_key VARCHAR(500) NOT NULL,
  file_sha256 VARCHAR(64) NOT NULL UNIQUE,
  summary TEXT,
  keywords VARCHAR(500),
  key_numbers TEXT,
  body TEXT,
  body_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ticker VARCHAR(20),
  market VARCHAR(10)
);
"""
COLUMNS = ("firm", "published_on", "title", "report_type", "topics", "analyst", "pages", "minio_key",
           "file_sha256", "summary", "keywords", "key_numbers", "body", "body_loaded", "ticker", "market")
INSERT = (f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) "
          f"VALUES ({', '.join(f'%({c})s' for c in COLUMNS)})")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def build_row(meta: dict, triage: dict, ann: dict, body: str) -> dict:
    title = ann.get("title") or meta["title"]
    name = "_".join(x for x in (meta["published_on"], slug(title)[:60].strip("_"), meta["id"][:6]) if x)
    return {
        "firm": meta["firm"],
        "published_on": date.fromisoformat(meta["published_on"]),
        "title": title,
        "report_type": triage["kind"],
        "topics": ", ".join(ann["topics"]),
        "analyst": ann.get("analyst"),
        "pages": meta["pages"],
        "minio_key": f"reports/{slug(meta['firm'])}/{name}.pdf",
        "file_sha256": meta["file_sha256"],
        "summary": "\n".join(ann["summary_ko"]) + "\n" + ann["summary_en"],
        "keywords": ", ".join(ann["keywords_ko"] + ann["keywords_en"]),
        "key_numbers": ann["key_numbers"] or None,
        "body": body,
        "body_loaded": True,
        "ticker": ann.get("ticker") or meta["ticker"],
        "market": meta["market"],
    }


def minio_client(url: str):
    """(client, bucket) from http(s)://ACCESS:SECRET@host:port/bucket, the same format as MI_MINIO."""
    from minio import Minio

    u = urlparse(url)
    bucket = u.path.strip("/")
    if u.scheme not in ("http", "https") or not (u.username and u.password and u.hostname and bucket):
        raise LoaderError(f"{MINIO_ENV} 형식은 http(s)://ACCESS:SECRET@host:port/bucket 이어야 합니다.", 2)
    endpoint = u.hostname + (f":{u.port}" if u.port else "")
    client = Minio(endpoint, access_key=unquote(u.username), secret_key=unquote(u.password),
                   secure=u.scheme == "https")
    return client, bucket


def load_all(staging: Path, dsn: str, target: str, create: bool, minio_url: str) -> int:
    import psycopg

    mc = minio_client(minio_url) if minio_url else None
    counts = Counter()
    with psycopg.connect(dsn, connect_timeout=10, autocommit=True) as conn:
        if create:
            conn.execute(DDL)
        elif conn.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
            raise LoaderError(f"{TABLE} 테이블이 아직 없습니다 (DBaaS 팀 생성 대기). 그동안은 --local 로 쌓으세요.", 1)
        for s in all_states(staging):
            if not s["load"]:
                continue
            if s["annotate"] is None or s["a_err"]:
                counts["wait"] += 1
                print(f"wait {s['id']} annotate.json {'오류' if s['a_err'] else '없음'} (status 로 확인)")
                continue
            m = s["meta"]
            try:
                row = build_row(m, s["triage"], s["annotate"], (s["dir"] / "text.txt").read_text(encoding="utf-8"))
                with conn.transaction():  # one report = one transaction
                    if conn.execute(f"SELECT 1 FROM {TABLE} WHERE file_sha256 = %s", (m["file_sha256"],)).fetchone():
                        result = "exists"
                    else:
                        if mc:
                            mc[0].fput_object(mc[1], row["minio_key"], m["source_path"], content_type="application/pdf")
                        conn.execute(INSERT, row)
                        result = "loaded"
            except Exception as e:  # report the failure, keep going with the next report
                counts["fail"] += 1
                print(f"FAIL {s['id']}: {type(e).__name__}: {redact(redact(str(e), dsn), minio_url)}")
                continue
            counts[result] += 1
            m.setdefault("loaded", {})[target] = datetime.now().isoformat(timespec="seconds")
            write_json(s["dir"] / "meta.json", m)
            print(f"{result:<6} {s['id']} {row['minio_key']}")
    print(f"({target}: 적재 {counts['loaded']}, 이미 있음 {counts['exists']}, 주석 대기 {counts['wait']}, "
          f"실패 {counts['fail']}, MinIO {'업로드' if mc else '건너뜀'})")
    return 1 if counts["wait"] or counts["fail"] else 0


def cmd_load(staging: Path, local: bool, dsn_env: str | None, no_minio: bool) -> int:
    minio_url = "" if local or no_minio else os.environ.get(MINIO_ENV, "")
    if not (local or no_minio or minio_url):
        raise LoaderError(f"환경변수 {MINIO_ENV} 가 없습니다 (MinIO 없이 적재하려면 --no-minio).", 2)
    if local:
        import pgserver

        with pgserver.get_server(staging / "localpg") as srv:  # stops on exit, data stays in staging/localpg
            return load_all(staging, srv.get_uri(), "local", True, "")
    dsn = os.environ.get(dsn_env, "")
    if not dsn:
        raise LoaderError(f"환경변수 {dsn_env} 가 설정되지 않았습니다 (이 터미널에서만 설정하세요).", 2)
    return load_all(staging, dsn, dsn_env, False, minio_url)


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="load_reports.py", description=__doc__)
    p.add_argument("--staging", type=Path, default=STAGING, help="작업 폴더 (기본: 저장소의 staging/)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("extract", help="PDF -> staging/<id>/text.txt + meta.json")
    s.add_argument("paths", nargs="+", type=Path, help="PDF 파일 또는 PDF가 든 폴더")
    s.add_argument("--force", action="store_true", help="이미 추출된 것도 다시 추출")
    sub.add_parser("status", help="레포트별 단계 상태 한 줄씩")
    sub.add_parser("triage-report", help="staging/triage.md 생성")
    s = sub.add_parser("load", help="적재 대상을 DB(+MinIO)에 넣기")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--local", action="store_true", help="staging/localpg 내장 PostgreSQL (MinIO 안 씀)")
    g.add_argument("--dsn-env", help="쓰기 DSN이 든 환경변수 이름 (예: MI_DB_REPORTS_WRITE)")
    s.add_argument("--no-minio", action="store_true", help="MinIO 업로드 건너뛰기")
    a = p.parse_args(argv)
    try:
        if a.cmd == "status":
            return cmd_status(a.staging)
        if a.cmd == "triage-report":
            return cmd_triage_report(a.staging)
        if a.cmd == "load":
            return cmd_load(a.staging, a.local, a.dsn_env, a.no_minio)
        return cmd_extract(a.staging, a.paths, a.force)
    except LoaderError as e:
        print(f"[load_reports] {e}", file=sys.stderr)
        return e.code
    except Exception as e:  # driver/network errors: class + masked message, never a DSN or secret
        msg = str(e)
        for env in (getattr(a, "dsn_env", None), MINIO_ENV):
            msg = redact(msg, os.environ.get(env) if env else None)
        print(f"[load_reports] {type(e).__name__}: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
