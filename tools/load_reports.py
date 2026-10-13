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
    a = p.parse_args(argv)
    try:
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
