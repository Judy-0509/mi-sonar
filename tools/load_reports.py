#!/usr/bin/env python
"""mi-sonar load_reports: broker research PDFs -> staging/ -> sales_team.nasdaq_report_doc (owner only).

Stages: extract (program) -> triage (agent) -> annotate (agent) -> load (program). Run with -h for usage.
Write credentials come only from env vars (MI_DB_REPORTS_WRITE, MI_MINIO_WRITE) and are never printed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "staging"
TABLE = "sales_team.nasdaq_report_doc"
PARA_TABLE = "sales_team.nasdaq_report_para"
MINIO_ENV = "MI_MINIO_WRITE"
DICT_DIR = Path(__file__).resolve().parent / "dict"
DOC_SHARE = 0.2  # a tag is document-level when it is in >= 20% of the paragraphs (or in the title)
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


class LoaderError(Exception):
    """User-facing error. code: 1 runtime, 2 setup missing (env var, package)."""

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


# ---------- file identity ----------

NAME_RE = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4})_\d{2}-\d{2}-\d{2}-(.+)\.(?:pdf|md|txt)$", re.I)
TICKER_RE = re.compile(r"^[A-Z0-9.]{1,10}$")
MARKET_RE = re.compile(r"^[A-Z]{1,4}$")


def parse_filename(name: str) -> dict:
    """`DD-Mon-YYYY_HH-MM-SS-[TICKER-MARKET-]FIRM[-TITLE].pdf|md|txt` -> published_on, ticker, market, firm, title."""
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

HEADING_MAX = 60  # a cutoff line longer than this is a body sentence, not a heading
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


def cut_disclosure(pages: list[str], phrases: list[str]) -> tuple[list[str], str | None]:
    """Cut everything from the first heading on page 2+: a line of <= HEADING_MAX characters starting with a
    `tools/dict/cutoff.csv` phrase (any case). Returns (kept pages, the heading as written in the PDF)."""
    if not phrases:
        return pages, None
    head_re = re.compile(r"[ \t]*(" + "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
                         + r")(?![A-Za-z0-9])", re.I)
    for i, page in enumerate(pages[1:], 1):  # page 1 often says "see important disclosures": never cut there
        lines = page.splitlines()
        for j, line in enumerate(lines):
            m = head_re.match(line)
            if m and len(line.strip()) <= HEADING_MAX:
                head = "\n".join(lines[:j]).strip()
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


def render_body(pages: list[str], page_numbers: bool = True) -> str:
    """Cleaned pages -> one text with a `[p.N]` line before each non-empty page (N = PDF page number)."""
    out = []
    for n, page in enumerate(pages, 1):
        text = join_wraps((strip_page_numbers if page_numbers else str)(unicodedata.normalize("NFKC", page)))  # NFKC: ligatures like ﬁ -> fi
        if text:
            out.append(f"[p.{n}]\n{text}")
    return "\n".join(out) + "\n" if out else ""


def url_count(text: str) -> int:
    return len(URL_RE.findall(text))


def smartphone_hits(text: str) -> int:
    low = text.lower()
    return sum(low.count(w) for w in SMARTPHONE_WORDS)


# ---------- dictionaries, paragraphs, tagging (pure; recomputed from text.txt on every run) ----------

@dataclass
class Dicts:
    """`tools/dict/*.csv`: tickers [(ticker, name, [aliases])], topics [(topic, [keywords])], cutoff [phrase]."""
    tickers: list
    topics: list
    cutoff: list

    def __post_init__(self):
        self.ticker_tags = _tagger([(t, aliases) for t, _, aliases in self.tickers])
        self.topic_tags = _tagger(self.topics)


def _read_csv(path: Path, cols: tuple[str, ...]) -> list[tuple[int, list[str]]]:
    """(line number, cells) for each row after the header; blank and `#` comment lines are skipped."""
    if not path.exists():
        raise LoaderError(f"사전 파일이 없습니다: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:  # -sig: Excel's "CSV UTF-8" starts with a BOM
        r = csv.reader(f)
        rows = [(r.line_num, [c.strip() for c in row]) for row in r]
    rows = [(n, row) for n, row in rows if any(row) and not row[0].startswith("#")]
    if not rows or tuple(rows[0][1]) != cols:
        raise LoaderError(f"{path.name}: 첫 줄(주석 제외)은 {','.join(cols)} 이어야 합니다")
    for n, row in rows[1:]:
        if len(row) != len(cols):
            raise LoaderError(f"{path.name} {n}행: 칸이 {len(cols)}개({','.join(cols)})여야 합니다")
    return rows[1:]


def load_dicts(dict_dir: Path = DICT_DIR) -> Dicts:
    """Read and check the three dictionaries; an error names the file and line."""
    parsed = {}
    for name, cols, what in (("tickers.csv", ("ticker", "name", "aliases"), "별칭"),
                             ("topics.csv", ("topic", "keywords"), "키워드")):
        seen, out = set(), []
        for n, row in _read_csv(dict_dir / name, cols):
            terms = [x.strip() for x in row[-1].split("|")]
            err = (f"{cols[0]} 칸이 비어 있습니다" if not row[0] else f"{cols[0]} 중복 ({row[0]})" if row[0] in seen
                   else f"{what}에 빈 값이 있습니다 (| 앞뒤 확인)" if not all(terms) else None)
            if err:
                raise LoaderError(f"{name} {n}행: {err}")
            seen.add(row[0])
            out.append((*row[:-1], terms))
        parsed[name] = out
    return Dicts(parsed["tickers.csv"], parsed["topics.csv"],
                 [row[0] for _, row in _read_csv(dict_dir / "cutoff.csv", ("phrase",))])


PAGE_MARK_RE = re.compile(r"^\[p\.(\d+)\]$")
MERGE_MAX = 40
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")


def split_paragraphs(body: str) -> list[dict]:
    """text.txt -> [{page, para_no, text}], para_no counting from 1 across pages. A line under MERGE_MAX characters
    not ending in . ? ! (table fragment, caption) joins the paragraph before it, unless it opens a page."""
    paras, page, first = [], 1, True
    for line in body.splitlines():
        line = line.strip()
        m = PAGE_MARK_RE.match(line)
        if m:
            page, first = int(m.group(1)), True
        elif line:
            if not first and len(line) < MERGE_MAX and not line.endswith((".", "?", "!")):
                paras[-1]["text"] += " " + line
            else:
                paras.append({"page": page, "para_no": len(paras) + 1, "text": line})
            first = False
    return paras


def compile_matcher(terms: list[str]) -> re.Pattern:
    """One pattern for all terms, longest first. English terms match whole words only (no letter or digit on
    either side); Korean terms match anywhere. Terms of 4+ characters ignore case, shorter ones (SEC, AI) do not."""
    def alt(t: str) -> str:  # [Aa] classes, not (?i:): they keep re's skip-on-first-character fast path (9x here)
        return re.escape(t) if len(t) < 4 else "".join(
            f"[{c.upper()}{c.lower()}]" if c.upper() != c.lower() else re.escape(c) for c in t)
    terms = sorted(set(terms), key=lambda t: (-len(t), t))
    en = "|".join(alt(t) for t in terms if not HANGUL_RE.search(t))
    ko = "|".join(alt(t) for t in terms if HANGUL_RE.search(t))
    parts = ([rf"(?<![A-Za-z0-9])(?:{en})(?![A-Za-z0-9])"] if en else []) + ([ko] if ko else [])
    return re.compile("|".join(parts) or r"(?!)")


def _key(term: str) -> str:
    return term.lower() if len(term) >= 4 else term  # compile_matcher's case rule


def _tagger(pairs: list) -> tuple[re.Pattern, dict]:
    """[(tag, terms)] -> (one pattern over every term, term key -> tags)."""
    index: dict[str, set] = {}
    for tag, terms in pairs:
        for t in terms:
            index.setdefault(_key(t), set()).add(tag)
    return compile_matcher([t for _, terms in pairs for t in terms]), index


def tag_text(text: str, dicts: Dicts) -> tuple[list[str], list[str]]:
    """(tickers, topics) whose terms occur in text, sorted and unique. Where terms overlap the longest one wins
    (`Samsung SDI` tags Samsung SDI only, not also Samsung Electronics)."""
    def tags(tagger) -> list[str]:
        pattern, index = tagger
        return sorted({tag for m in pattern.finditer(text) for tag in index[_key(m.group())]})
    return tags(dicts.ticker_tags), tags(dicts.topic_tags)


def tag_paragraphs(paras: list[dict], dicts: Dicts) -> list[dict]:
    out = []
    for p in paras:
        tickers, topics = tag_text(p["text"], dicts)
        out.append({**p, "tickers": tickers, "topics": topics})
    return out


def derive(paras: list[dict], title: str | None, dicts: Dicts) -> dict:
    """Paragraph counts per ticker/topic and the document-level tags: those in >= DOC_SHARE of the paragraphs or
    in the title, most paragraphs first."""
    need = max(1, math.ceil(round(DOC_SHARE * len(paras), 9)))  # round: 0.2 * 15 is 3.0000000000000004
    out: dict = {"paragraphs": len(paras)}
    for key, in_title in zip(("tickers", "topics"), tag_text(title or "", dicts)):
        counts = Counter(t for p in paras for t in p[key])
        order = sorted(set(counts) | set(in_title), key=lambda t: (-counts[t], t))
        out[key] = {t: counts[t] for t in order if counts[t]}
        out["doc_" + key] = [t for t in order if counts[t] >= need or t in in_title]
    return out


RELEVANCE = ("high", "medium", "low")


def relevance(derived: dict) -> str:
    """high: an application topic is document-level; medium: only some paragraph has a topic tag; else low."""
    return RELEVANCE[0] if derived["doc_topics"] else RELEVANCE[1] if derived["topics"] else RELEVANCE[2]


# ---------- extract ----------

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else None


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_pages(pdf: Path) -> tuple[list[str], str]:
    """Page texts via pymupdf, else pdfplumber, else pypdf (lazy imports). Returns (pages, extractor name)."""
    for name in ("pymupdf", "fitz"):  # fitz: pymupdf's import name before 1.24
        try:
            mupdf = importlib.import_module(name)
        except ImportError:
            continue
        with mupdf.open(str(pdf)) as doc:
            return [p.get_text("text") for p in doc], "pymupdf"
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


TEXT_EXTS = (".md", ".txt")
SOURCE_EXTS = (".pdf",) + TEXT_EXTS
CONTENT_TYPES = {".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain"}


def read_text_source(path: Path, info: dict) -> tuple[list[str], str]:
    """Pasted article (.md/.txt): the whole file is page 1. A first line `# Title` overrides the filename title."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        info["title"] = " ".join(lines[0][2:].split()) or info["title"]
        text = "\n".join(lines[1:])
    return [text], "text"


def extract_one(pdf: Path, staging: Path, force: bool, cutoff: list[str]) -> str:
    info = parse_filename(pdf.name)
    sha = file_sha256(pdf)
    rid = sha[:12]
    d = staging / rid
    old = read_json(d / "meta.json")
    if old and not force:
        return f"skip {rid} (이미 추출됨) {pdf.name}"
    is_text = pdf.suffix.lower() in TEXT_EXTS
    raw, extractor = read_text_source(pdf, info) if is_text else read_pages(pdf)
    raw = [unicodedata.normalize("NFKC", p) for p in raw]  # before the cut: ligatures/NBSP would defeat the match
    pages, heading = (raw, None) if is_text else cut_disclosure(strip_repeated_lines(raw), cutoff)  # articles: none
    body = render_body(pages, not is_text)  # articles keep lone-number lines
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


def unzip_to_inbox(zp: Path, staging: Path) -> Path:
    """Unpack a .zip into staging/inbox/<zip stem>/ (overwriting); members escaping that folder are skipped."""
    dest = staging / "inbox" / zp.stem
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zp) as z:
        for m in z.infolist():
            target = (root / m.filename).resolve()
            if root != target and root not in target.parents:
                print(f"SKIP {m.filename} (path outside folder)")
            elif not m.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(m))
    return dest


def cmd_extract(staging: Path, paths: list[Path], force: bool) -> int:
    cutoff = load_dicts().cutoff
    pdfs: list[Path] = []
    for p in paths:
        if p.suffix.lower() == ".zip" and p.is_file():
            p = unzip_to_inbox(p, staging)
        pdfs += sorted(f for f in p.iterdir() if f.suffix.lower() in SOURCE_EXTS) if p.is_dir() else [p]
    failed = 0
    for pdf in pdfs:
        try:
            print(extract_one(pdf, staging, force, cutoff))
        except LoaderError:
            raise
        except Exception as e:  # one bad PDF must not stop the batch
            failed += 1
            print(f"FAIL {pdf.name}: {type(e).__name__}: {e}")
    print(f"(파일 {len(pdfs)}개, 실패 {failed}개)")
    return 1 if failed else 0


# ---------- triage / annotate files ----------

KINDS = ("link_digest", "weekly_note", "company_update", "industry_deep_dive", "mgmt_meeting", "firm_analysis",
         "other")
TRIAGE_KEYS = {"kind", "reason", "load"}
ANNOTATE_KEYS = {"title", "ticker", "analyst", "thesis", "summary_ko", "summary_en", "keywords_ko", "keywords_en",
                 "key_numbers"}  # scope (tickers) and topics are derived from tools/dict, not written by the agent


def _line(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and "\n" not in v


def validate_triage(t) -> list[str]:
    if not isinstance(t, dict):
        return ["JSON 객체가 아닙니다"]
    errs = [f"모르는 키: {k}" + (" (프로그램이 주제 사전으로 산출)" if k == "relevance" else "")
            for k in sorted(set(t) - TRIAGE_KEYS)]
    if t.get("kind") not in KINDS:
        errs.append(f"kind 는 {', '.join(KINDS)} 중 하나")
    if not _line(t.get("reason")):
        errs.append("reason 은 비어 있지 않은 한 줄")
    if "load" in t and not isinstance(t["load"], bool):
        errs.append("load 는 true 또는 false (사용자만 씀)")
    return errs


def decide(t: dict, rel: str) -> bool:
    """Load rule: derived relevance high/medium and not a link digest. A user-written `load` overrides it."""
    if isinstance(t.get("load"), bool):
        return t["load"]
    return rel in ("high", "medium") and t["kind"] != "link_digest"


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
    thesis = a.get("thesis")
    if not (_line(thesis) and 10 <= len(thesis) <= 300):
        errs.append("thesis 는 레포트의 주장을 담은 10~300자 한 줄 한국어 문장 (필수)")
    ko = a.get("summary_ko")
    if not (isinstance(ko, list) and 3 <= len(ko) <= 6 and all(_line(x) for x in ko)):
        errs.append("summary_ko 는 한 줄짜리 한국어 문장 3~6개의 목록")
    elif not all("[p." in x for x in ko[1:]):
        errs.append("summary_ko 2번째 줄부터는 근거이며 [p.N] 을 포함")
    if not _line(a.get("summary_en")):
        errs.append("summary_en 은 영어 한 줄")
    for key in ("keywords_ko", "keywords_en"):
        if not _words(a.get(key)):
            errs.append(f"{key} 는 쉼표 없는 한 줄 단어 1~10개의 목록")
    kws = [a.get("keywords_ko"), a.get("keywords_en")]
    if all(_words(k) for k in kws) and len(", ".join(kws[0] + kws[1])) > 500:
        errs.append("keywords_ko + keywords_en 합계가 500자를 넘습니다")
    if not isinstance(a.get("key_numbers"), str):
        errs.append("key_numbers 는 문자열 (숫자가 없으면 빈 문자열)")
    return errs


def report_state(d: Path, dicts: Dicts) -> dict:
    """Everything known about one staging/<id>/ folder; JSON errors become validation errors. Paragraph tags are
    recomputed from text.txt with the current dictionaries, so a dictionary edit applies without re-extracting."""
    s = {"id": d.name, "dir": d, "meta": read_json(d / "meta.json"), "triage": None, "t_err": [],
         "load": None, "annotate": None, "a_err": []}
    text = d / "text.txt"
    s["paras"] = tag_paragraphs(split_paragraphs(text.read_text(encoding="utf-8") if text.exists() else ""), dicts)
    s["title"] = s["meta"]["title"]
    s["derived"] = derive(s["paras"], s["title"], dicts)
    s["relevance"] = relevance(s["derived"])  # from the file-name title; annotate may later replace the title
    try:
        s["triage"] = read_json(d / "triage.json")
    except ValueError as e:
        s["t_err"] = [f"JSON 오류: {e}"]
    if s["triage"] is not None:
        s["t_err"] = validate_triage(s["triage"])
        if not s["t_err"]:
            s["load"] = decide(s["triage"], s["relevance"])
    if s["load"]:
        try:
            s["annotate"] = read_json(d / "annotate.json")
        except ValueError as e:
            s["a_err"] = [f"JSON 오류: {e}"]
        if s["annotate"] is not None:
            s["a_err"] = validate_annotate(s["annotate"], s["meta"])
    ann = s["annotate"] if isinstance(s["annotate"], dict) else {}
    s["title"] = (ann.get("title") if isinstance(ann.get("title"), str) else None) or s["meta"]["title"]  # as build_row
    s["derived"] = derive(s["paras"], s["title"], dicts)
    return s


def all_states(staging: Path) -> list[dict]:
    dicts = load_dicts()
    dirs = [d for d in staging.iterdir() if (d / "meta.json").exists()] if staging.exists() else []
    return sorted((report_state(d, dicts) for d in dirs),
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
        dv = s["derived"]
        print(f"{s['id']} {m['published_on']} {m['firm']:<12} triage={_stage(s['triage'], s['t_err'])} "
              f"rel={s['relevance']} decision={decision} annotate={annotate} loaded={loaded} tickers={','.join(dv['doc_tickers']) or '-'} "
              f"topics={','.join(dv['doc_topics']) or '-'} paras={dv['paragraphs']}  {m['title'] or '(제목 없음)'}")
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


def cmd_paragraphs(staging: Path, rid: str) -> int:
    """Verification view of one report: every paragraph with its tags, then the counts and document-level tags."""
    ids = sorted(d.name for d in staging.iterdir()
                 if d.name.startswith(rid) and (d / "meta.json").exists()) if staging.exists() else []
    if len(ids) != 1:
        raise LoaderError(f"id '{rid}' 로 시작하는 레포트가 " + (f"여러 개입니다: {', '.join(ids)}" if ids else "없습니다"))
    s = report_state(staging / ids[0], load_dicts())
    m, dv = s["meta"], s["derived"]

    def counts(c: dict) -> str:
        return ", ".join(f"{k} {v}" for k, v in c.items()) or "-"

    rows = [(p["para_no"], p["page"], ", ".join(p["tickers"]), ", ".join(p["topics"]), p["text"][:100])
            for p in s["paras"]]
    print("\n".join([
        f"# 문단 확인: {m['id']} {m['published_on']} {m['firm']} {s['title'] or '(제목 없음)'}", "",
        *md_table(["#", "p.", "tickers", "topics", "text"], rows), "",
        f"## 집계 (문단 {dv['paragraphs']}개)", "",
        f"- 티커별 문단 수: {counts(dv['tickers'])}",
        f"- 주제별 문단 수: {counts(dv['topics'])}",
        f"- 문서 티커 (문단 {DOC_SHARE:.0%} 이상 또는 제목): {', '.join(dv['doc_tickers']) or '-'}",
        f"- 문서 주제 (같은 기준): {', '.join(dv['doc_topics']) or '-'}",
        f"- 꼬리 자른 제목: {m['cut_heading'] or '-'} / 남은 쪽: {m['body_pages']}/{m['pages']}",
    ]))
    return 0


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
        "규칙: 관련도(주제 사전으로 자동 산출)가 high 또는 medium 이고 kind 가 link_digest 가 아니면 적재합니다.",
        "결정을 바꾸려면 `staging/<id>/triage.json` 에 `\"load\": true` 또는 `\"load\": false` 를 넣고 "
        "`triage-report` 를 다시 실행하세요 (결정 칸에 `(수동)` 표시).",
        "제외된 레포트는 DB와 MinIO 어디에도 올라가지 않고 이 파일에만 기록됩니다.",
    ]
    cols = ["id", "발행일", "증권사", "티커", "제목", "티커(자동)", "주제(자동)", "종류", "관련도(자동)", "결정", "이유",
            "폰 단어/URL"]
    for key, label in (("load", "적재"), ("skip", "제외")):
        rows = [(s["id"], s["meta"]["published_on"], s["meta"]["firm"], s["meta"]["ticker"], s["meta"]["title"],
                 ", ".join(s["derived"]["doc_tickers"]), ", ".join(s["derived"]["doc_topics"]),
                 s["triage"]["kind"], s["relevance"], label + (" (수동)" if "load" in s["triage"] else ""),
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
  thesis VARCHAR(300),
  scope VARCHAR(300),
  body TEXT,
  body_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ticker VARCHAR(20),
  market VARCHAR(10)
);
CREATE TABLE IF NOT EXISTS sales_team.nasdaq_report_para (
  id SERIAL PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES sales_team.nasdaq_report_doc(id) ON DELETE CASCADE,
  page INTEGER NOT NULL,
  para_no INTEGER NOT NULL,
  tickers VARCHAR(300),
  topics VARCHAR(100),
  text TEXT NOT NULL,
  UNIQUE (doc_id, para_no)
);
"""
COLUMNS = ("firm", "published_on", "title", "report_type", "topics", "analyst", "pages", "minio_key",
           "file_sha256", "summary", "keywords", "key_numbers", "thesis", "scope", "body", "body_loaded", "ticker",
           "market")
INSERT = (f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) "
          f"VALUES ({', '.join(f'%({c})s' for c in COLUMNS)}) RETURNING id")
PARA_INSERT = f"INSERT INTO {PARA_TABLE} (doc_id, page, para_no, tickers, topics, text) VALUES (%s, %s, %s, %s, %s, %s)"


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def join_fit(tags: list[str], limit: int) -> str | None:
    """Comma-joined tags within a VARCHAR(limit); no tags -> NULL."""
    # ponytail: tags past the column width are dropped (a comps table can name 30+ tickers); widen to TEXT if needed
    out = ""
    for t in tags:
        if len(out) + 2 * bool(out) + len(t) > limit:
            break
        out += (", " if out else "") + t
    return out or None


def build_row(meta: dict, triage: dict, ann: dict, body: str, derived: dict) -> dict:
    title = ann.get("title") or meta["title"]
    name = "_".join(x for x in (meta["published_on"], slug(title)[:60].strip("_"), meta["id"][:6]) if x)
    return {
        "firm": meta["firm"],
        "published_on": date.fromisoformat(meta["published_on"]),
        "title": title,
        "report_type": triage["kind"],
        "topics": join_fit(derived["doc_topics"], 300),
        "analyst": ann.get("analyst"),
        "pages": meta["pages"],
        "minio_key": f"reports/{slug(meta['firm'])}/{name}{Path(meta['source_path']).suffix.lower()}",
        "file_sha256": meta["file_sha256"],
        "summary": "\n".join(ann["summary_ko"]) + "\n" + ann["summary_en"],
        "keywords": ", ".join(ann["keywords_ko"] + ann["keywords_en"]),
        "key_numbers": ann["key_numbers"] or None,
        "thesis": ann["thesis"],
        "scope": join_fit(derived["doc_tickers"], 300),
        "body": body,
        "body_loaded": True,
        "ticker": ann.get("ticker") or meta["ticker"],
        "market": meta["market"],
    }


def minio_client(url: str):
    """(client, bucket) from http(s)://ACCESS:SECRET@host:port/bucket, the same format as MI_MINIO."""
    Minio = need("minio").Minio
    urllib3 = need("urllib3")

    u = urlparse(url)
    bucket = u.path.strip("/")
    if u.scheme not in ("http", "https") or not (u.username and u.password and u.hostname and bucket):
        raise LoaderError(f"{MINIO_ENV} 형식은 http(s)://ACCESS:SECRET@host:port/bucket 이어야 합니다.", 2)
    endpoint = u.hostname + (f":{u.port}" if u.port else "")
    client = Minio(endpoint, access_key=unquote(u.username), secret_key=unquote(u.password),
                   secure=u.scheme == "https",
                   http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=10, read=120),
                                                   retries=urllib3.Retry(total=2)))
    return client, bucket


def load_all(staging: Path, dsn: str, target: str, create: bool, minio_url: str) -> int:
    psycopg = need("psycopg")

    mc = minio_client(minio_url) if minio_url else None
    counts = Counter()
    with psycopg.connect(dsn, connect_timeout=10, autocommit=True,
                      prepare_threshold=None) as conn:  # no server-side prepare: safe behind PgBouncer transaction pooling
        if create:
            conn.execute(DDL)
        else:
            for t in (TABLE, PARA_TABLE):
                if conn.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is None:
                    raise LoaderError(f"{t} 테이블이 아직 없습니다 (DBaaS 팀 생성 대기). 그동안은 --local 로 쌓으세요.", 1)
        for s in all_states(staging):
            if not s["load"]:
                continue
            if s["annotate"] is None or s["a_err"]:
                counts["wait"] += 1
                print(f"wait {s['id']} annotate.json {'오류' if s['a_err'] else '없음'} (status 로 확인)")
                continue
            m = s["meta"]
            try:
                row = build_row(m, s["triage"], s["annotate"], (s["dir"] / "text.txt").read_text(encoding="utf-8"),
                                s["derived"])
                with conn.transaction():  # one report = one transaction
                    if conn.execute(f"SELECT 1 FROM {TABLE} WHERE file_sha256 = %s", (m["file_sha256"],)).fetchone():
                        result = "exists"
                    else:
                        doc_id = conn.execute(INSERT, row).fetchone()[0]  # rows first: a failed upload rolls them back
                        with conn.cursor() as cur:
                            cur.executemany(PARA_INSERT, [(doc_id, p["page"], p["para_no"], join_fit(p["tickers"], 300),
                                                           join_fit(p["topics"], 100), p["text"]) for p in s["paras"]])
                        if mc:
                            mc[0].fput_object(mc[1], row["minio_key"], m["source_path"], content_type=CONTENT_TYPES[Path(row["minio_key"]).suffix])
                        result = "loaded"
            except Exception as e:  # report the failure, keep going with the next report
                counts["fail"] += 1
                print(f"FAIL {s['id']}: {type(e).__name__}: {redact(redact(str(e), dsn), minio_url)}")
                continue
            counts[result] += 1
            m.setdefault("loaded", {})[target] = datetime.now().isoformat(timespec="seconds")
            write_json(s["dir"] / "meta.json", m)
            print(f"{result:<6} {s['id']} {row['minio_key']} paras={len(s['paras'])}")
    print(f"({target}: 적재 {counts['loaded']}, 이미 있음 {counts['exists']}, 주석 대기 {counts['wait']}, "
          f"실패 {counts['fail']}, MinIO {'업로드' if mc else '건너뜀'})")
    return 1 if counts["wait"] or counts["fail"] else 0


def cmd_load(staging: Path, local: bool, dsn_env: str | None, no_minio: bool) -> int:
    minio_url = "" if local or no_minio else os.environ.get(MINIO_ENV, "")
    if not (local or no_minio or minio_url):
        raise LoaderError(f"환경변수 {MINIO_ENV} 가 없습니다 (MinIO 없이 적재하려면 --no-minio).", 2)
    if local:
        pgserver = need("pgserver")
        pgdata = staging / "localpg"
        try:
            srv = pgserver.get_server(pgdata)
        except UnicodeDecodeError:  # ponytail: pgserver 0.1.4 decodes initdb output as cp949; initdb already succeeded
            # pgserver registered the half-built instance before failing: drop it or the retry returns it unstarted
            pgserver.postgres_server.PostgresServer._instances.pop(pgdata.resolve(), None)
            srv = pgserver.get_server(pgdata)
        with srv:  # stops on exit, data stays in staging/localpg
            return load_all(staging, srv.get_uri(), "local", True, "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dsn_env):  # never echo the value: it may be a pasted DSN
        raise LoaderError("--dsn-env 에는 환경변수 이름을 주세요", 2)
    dsn = os.environ.get(dsn_env, "")
    if not dsn:
        raise LoaderError(f"환경변수 {dsn_env} 가 설정되지 않았습니다 (이 터미널에서만 설정하세요).", 2)
    if dsn.startswith(("postgres://", "postgresql://")) and "@" in dsn.rsplit("@", 1)[0]:
        raise LoaderError(f"환경변수 {dsn_env} 의 비밀번호에 '@' 가 있습니다. URL 인코딩(%40)해서 다시 등록하세요.", 2)
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
    s = sub.add_parser("extract", help="PDF/.md/.txt -> staging/<id>/text.txt + meta.json")
    s.add_argument("paths", nargs="+", type=Path, help="PDF·.md·.txt 파일 또는 그것들이 든 폴더")
    s.add_argument("--force", action="store_true", help="이미 추출된 것도 다시 추출")
    sub.add_parser("status", help="레포트별 단계 상태 한 줄씩")
    sub.add_parser("triage-report", help="staging/triage.md 생성")
    s = sub.add_parser("paragraphs", help="한 레포트의 문단별 자동 티커·주제와 집계 (검증용)")
    s.add_argument("id", help="staging/<id> 폴더 이름 또는 그 앞부분")
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
        if a.cmd == "paragraphs":
            return cmd_paragraphs(a.staging, a.id)
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
