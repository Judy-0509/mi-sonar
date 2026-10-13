# Reports Loader (`tools/load_reports.py`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An owner-only CLI, `tools/load_reports.py`, that turns the ~54 downloaded broker research PDFs into rows of `sales_team.nasdaq_report_doc` (one row per smartphone-relevant report: cleaned English body with `[p.N]` page markers, Korean + English summary and keywords) in four stages `extract` → `triage` → `annotate` → `load`, accumulating first in an embedded local PostgreSQL and later pushing the same staging into the company DB and MinIO; plus `sources/reports.md` and a short SKILL.md step so colleagues' agents can search the table read-only with the existing `query.py sql`.

**Architecture:** Pipeline C. The program does every mechanical step (filename parsing, sha256, text extraction and cleanup, validation, the load decision, DB/MinIO writes); the in-company agent only writes two small JSON files per report (`triage.json`, `annotate.json`) and never writes body text. All work lives under `staging/<id>/` (id = first 12 hex of the PDF's sha256), which is gitignored and never leaves the PC. `load --local` boots `pgserver` in `staging/localpg/` and creates schema + table from the spec DDL; `load --dsn-env MI_DB_REPORTS_WRITE` pushes the same staging into the company DB (table must already exist, nothing is created there) and uploads PDFs with `MI_MINIO_WRITE`. Idempotent on `file_sha256`. One file in the same single-file style as `scripts/query.py` and `tools/db_check.py`; every command shares `report_state`/`all_states`, so splitting adds nothing.

**Tech Stack:** Python 3.10+, `pdfplumber` 0.11 (fallback `pypdf`), `psycopg[binary]` 3.x, `minio` 7.x, `pgserver` (dev: local mode and tests), `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-13-reports-storage-design.md`

## Global Constraints

- Python floor 3.10, Windows. No syntax or stdlib newer than 3.10 (no `hashlib.file_digest`).
- No new runtime deps for colleagues: `requirements.txt` stays `psycopg[binary]`, `minio`. The loader is owner-only, so `pdfplumber>=0.11,<1` and `pypdf>=4,<7` go into `requirements-dev.txt` (next to `pgserver`), not `requirements.txt`.
- Secrets only via env vars: `MI_DB_REPORTS_WRITE` (postgres DSN) and `MI_MINIO_WRITE` (`http(s)://ACCESS:SECRET@host:port/bucket`, same format as `MI_MINIO`). Never printed: every error text passes through `redact`; summary lines name the env var, never its value.
- Table name exactly `sales_team.nasdaq_report_doc`, DDL exactly the spec §3 column list (`SERIAL` / `VARCHAR` style). Only `--local` runs DDL; company mode never creates or alters anything.
- Body text comes only from the program (`text.txt`). Reports whose decision is "skip" get no DB row and no MinIO object.
- `staging/` holds confidential report text: gitignored, never committed, never uploaded except through `load`.
- Console may be cp949: `main()` reconfigures stdout/stderr to UTF-8 exactly like `query.py`.
- Exit codes: 0 ok, 1 runtime error or any report failed / still waiting for annotate, 2 setup missing (env var, PDF library, bad `MI_MINIO_WRITE` format).
- Tests run with `python -m pytest tools scripts -q`. pgserver-backed tests skip only when pgserver is not installed (it is in `requirements-dev.txt`, so they must run).
- Commit messages end with the two attribution lines used in this repo's history (`git log -3` shows them: a `Co-Authored-By:` line and a `Claude-Session:` line).

## Review Focus

1. Filename shapes: full, no title, firm only, no ticker/market, upper-case `.PDF`; bad month, impossible date, empty firm → `ValueError` → `FAIL` line while the batch continues. Tests in Tasks 1 and 3.
2. Disclosure cut never fires on page 1 ("See Important Disclosures…" is common there); text above the heading on the cut page is kept; no heading → nothing cut. Test in Task 2.
3. Repeated-line removal counts over all pages (before the cut) and is skipped below 3 pages; a long table line survives `join_wraps`. Tests in Task 2.
4. Decision rule and owner override (`"load": true/false` beats the rule); a "skip" report never reaches the DB or MinIO. Tests in Tasks 4 and 5.
5. Idempotency: `extract` twice → `skip`; `load` twice → `exists` and no second MinIO upload. Tests in Tasks 3 and 5.
6. Secrets: the DSN password and MinIO secret never appear in stdout/stderr, on connect failure or per-report failure. Test in Task 5.
7. Company mode with the table missing → exit 1 with a clear message, no DDL executed. Test in Task 5.
8. Agent-written JSON that is broken, has a BOM, or has a typo'd key shows as `ERR` with a reason in `status` instead of crashing. Test in Task 4.

---

## File Structure

```
tools/load_reports.py               CLI + all four stages                    (Tasks 1-5)
tools/test_load_reports.py          unit + pgserver integration tests        (Tasks 1-5)
.gitignore                          + staging/                               (Task 1)
requirements-dev.txt                + pdfplumber, pypdf                      (Task 3)
sources/reports.md                  read-only source for colleagues          (Task 6)
SKILL.md                            + 증권사 레포트 찾기                      (Task 6)
docs/handoff/reports-loader-run.md  in-company run order                     (Task 7)

staging/                            runtime only, gitignored
├── <id>/meta.json                  program-owned
├── <id>/text.txt                   program-owned (cleaned body, [p.N] markers)
├── <id>/triage.json                agent-owned (owner may add "load")
├── <id>/annotate.json              agent-owned (load reports only)
├── triage.md                       rendered by triage-report
└── localpg/                        pgserver data for load --local
```

`load_reports.py` sections in file order: constants → `LoaderError` → `redact` → file identity → text cleanup → extract → triage/annotate files → load → CLI `main`. Tasks 4 and 5 insert their sections directly above the `# ---------- CLI ----------` line.

CLI grammar (used verbatim by the handoff doc):

```
python tools/load_reports.py [--staging DIR] extract PATH... [--force]
python tools/load_reports.py [--staging DIR] status
python tools/load_reports.py [--staging DIR] triage-report
python tools/load_reports.py [--staging DIR] load (--local | --dsn-env ENV) [--no-minio]
```

---

### Task 1: Skeleton, filename parser, file identity

**Files:**
- Modify: `.gitignore`
- Create: `tools/load_reports.py` (header, constants, `LoaderError`, `redact`, file identity section)
- Test: `tools/test_load_reports.py`

**Interfaces:**
- Produces: `LoaderError(msg: str, code: int = 1)` with `.code` (1 runtime, 2 setup missing); `redact(text: str, conn: str | None) -> str` (verbatim copy of `scripts/query.py`); `parse_filename(name: str) -> dict` with keys `published_on` (ISO `YYYY-MM-DD` str), `ticker`, `market`, `firm`, `title` (`str | None`; `_` → space, whitespace collapsed), raises `ValueError`; `file_sha256(path: Path) -> str` (64 lowercase hex). Report id convention everywhere: `id = sha256[:12]`. Constants `ROOT`, `STAGING`, `TABLE`, `MINIO_ENV`, `MONTHS`.

- [ ] **Step 1: Ignore staging**

Append to `.gitignore`:
```
staging/
```

- [ ] **Step 2: Write failing tests**

Create `tools/test_load_reports.py`:
```python
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_reports as lr  # noqa: E402


# ---------- filename + identity ----------

@pytest.mark.parametrize("name,expect", [
    ("06-Oct-2026_08-02-29-MU-USQ-JPMorgan-Micron_Technology_Mgmt_Mtg__CY27_and_CY28_Both_Significantly_Ti.pdf",
     {"published_on": "2026-10-06", "ticker": "MU", "market": "USQ", "firm": "JPMorgan",
      "title": "Micron Technology Mgmt Mtg CY27 and CY28 Both Significantly Ti"}),
    ("01-Sep-2026_17-45-00-AAPL-USQ-Jefferies.PDF",
     {"published_on": "2026-09-01", "ticker": "AAPL", "market": "USQ", "firm": "Jefferies", "title": None}),
    ("15-Aug-2026_07-00-01-JPMorgan.PDF",
     {"published_on": "2026-08-15", "ticker": None, "market": None, "firm": "JPMorgan", "title": None}),
    ("08-Oct-2026_06-30-00-Nomura-Largan_Precision_3Q-26_Preview.pdf",
     {"published_on": "2026-10-08", "ticker": None, "market": None, "firm": "Nomura",
      "title": "Largan Precision 3Q-26 Preview"}),
    ("02-Jan-2026_09-00-00-2382-TT-Morgan_Stanley-Quanta_AI_Servers.pdf",
     {"published_on": "2026-01-02", "ticker": "2382", "market": "TT", "firm": "Morgan Stanley",
      "title": "Quanta AI Servers"}),
])
def test_parse_filename_shapes(name, expect):
    assert lr.parse_filename(name) == expect


@pytest.mark.parametrize("name", [
    "report.pdf",
    "06-Oct-2026_08-02-29-MU-USQ-JPMorgan.docx",
    "06-Xyz-2026_08-02-29-JPMorgan.pdf",
    "31-Feb-2026_08-02-29-JPMorgan.pdf",
    "06-Oct-2026_08-02-29--Title.pdf",
])
def test_parse_filename_rejects(name):
    with pytest.raises(ValueError):
        lr.parse_filename(name)


def test_file_sha256_matches_hashlib(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4 test" * 100_000)
    assert lr.file_sha256(f) == hashlib.sha256(f.read_bytes()).hexdigest()


def test_redact_masks_dsn_and_password():
    dsn = "postgresql://writer:p%40ss@db.corp:5432/mi"
    msg = f"failed for {dsn}; password p@ss; raw p%40ss"
    out = lr.redact(msg, dsn)
    assert "p@ss" not in out and "p%40ss" not in out and "db.corp" not in out
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'load_reports'`

- [ ] **Step 4: Write `tools/load_reports.py` header and file identity section**

```python
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
```

The ticker/market test (`TICKER_RE` upper-case/digits, `MARKET_RE` 1-4 upper-case letters) is what separates `MU-USQ-JPMorgan-…` from `Nomura-Largan_…`. Known ceiling: an all-caps firm followed by a short all-caps title word (e.g. `UBS-AI-Servers`) would be read as ticker/market. Such a name shows a wrong firm in `status`; the fix is renaming the file to the standard shape and `extract --force` (Task 7 tells the agent).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add .gitignore tools/load_reports.py tools/test_load_reports.py
git commit -m "feat(reports): load_reports skeleton with filename parser and file hash"
```

---

### Task 2: Text cleanup and signals

**Files:**
- Modify: `tools/load_reports.py` (append text cleanup section after file identity)
- Test: `tools/test_load_reports.py`

**Interfaces:**
- Produces (all pure, on strings): `strip_repeated_lines(pages: list[str], threshold: float = 0.6) -> list[str]`; `cut_disclosure(pages: list[str]) -> tuple[list[str], str | None]` (kept pages, matched heading text as written in the PDF); `strip_page_numbers(page: str) -> str`; `join_wraps(text: str) -> str` (one paragraph per line); `render_body(pages: list[str]) -> str` (`[p.N]` line before each non-empty page, N = PDF page number, NFKC-normalised); `url_count(text: str) -> int`; `smartphone_hits(text: str) -> int`; `SMARTPHONE_WORDS` (the probe's word list).
- Pipeline used by `extract` (Task 3): `pages, heading = cut_disclosure(strip_repeated_lines(raw)); body = render_body(pages)`. Repeated lines are counted over all pages, so header/footer lines that also run through the disclosure tail reach the threshold.

- [ ] **Step 1: Write failing tests**

Append to `tools/test_load_reports.py`:
```python
# ---------- text cleanup ----------

HEADER = "Nomura | Largan Precision 8 October 2026"


def test_strip_repeated_lines_drops_header_keeps_body():
    pages = [f"{HEADER}\nbody {i}\nSource: Nomura estimates" if i < 2 else f"{HEADER}\nbody {i}" for i in range(5)]
    out = lr.strip_repeated_lines(pages)
    assert all(HEADER not in p for p in out)
    assert out[0] == "body 0\nSource: Nomura estimates"  # on 2 of 5 pages (< 60%): kept


def test_strip_repeated_lines_needs_three_pages():
    pages = [f"{HEADER}\nbody", f"{HEADER}\nbody 2"]
    assert lr.strip_repeated_lines(pages) == pages


def test_cut_disclosure_skips_page_one_and_keeps_text_before_heading():
    pages = [
        "Summary\nSee Important Disclosures on page 4.\nImportant Disclosures are at the end",
        "Body page two.",
        "Last body paragraph.\nAnalyst Certification\nI, Jane Doe, certify...",
        "Important Disclosures\nRatings...",
    ]
    kept, heading = lr.cut_disclosure(pages)
    assert heading == "Analyst Certification"
    assert kept == pages[:2] + ["Last body paragraph."]


def test_cut_disclosure_heading_at_page_top_and_none():
    pages = ["p1", "p2", "IMPORTANT DISCLOSURES\nlegal"]
    assert lr.cut_disclosure(pages) == (["p1", "p2"], "IMPORTANT DISCLOSURES")
    assert lr.cut_disclosure(["p1", "p2"]) == (["p1", "p2"], None)


def test_strip_page_numbers():
    assert lr.strip_page_numbers("Text\n 3 \n2026 shipments\n12") == "Text\n2026 shipments"


def test_join_wraps_paragraphs_bullets_hyphens():
    text = ("Smartphone shipments rose\nin 3Q26 as demand\nrecovered.\nKey points:\n"
            "• Memory prices up\n  further in 4Q\n• Camera content flat\n"
            "high-\nend models gained share\n\nNext para")
    assert lr.join_wraps(text).splitlines() == [
        "Smartphone shipments rose in 3Q26 as demand recovered.",
        "Key points:",
        "• Memory prices up further in 4Q",
        "• Camera content flat high-end models gained share",
        "Next para",
    ]


def test_join_wraps_keeps_long_table_line():
    row = "Shipments (m) 1Q26 2Q26 3Q26 " + " ".join(str(i) for i in range(120))
    assert row in lr.join_wraps(f"Figure 3: Global shipments\n{row}\n")


def test_render_body_markers_and_ligatures():
    out = lr.render_body(["ﬁrst page line\nwraps here.", "", "7\nthird page."])
    assert out == "[p.1]\nfirst page line wraps here.\n[p.3]\nthird page.\n"


def test_signals():
    text = "See https://a.example and www.b.example. Smartphone units; iPhone shipments; handsets."
    assert lr.url_count(text) == 2
    assert lr.smartphone_hits(text) == 5  # smartphone, units, iphone, shipments, handset
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/test_load_reports.py -v -k "strip or cut or join or render or signals"`
Expected: FAIL, `AttributeError: module 'load_reports' has no attribute 'strip_repeated_lines'`

- [ ] **Step 3: Implement the cleanup section**

Append to `tools/load_reports.py` (after `file_sha256`):
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add tools
git commit -m "feat(reports): page text cleanup (disclosure cut, headers, wraps, [p.N]) and signals"
```

---

### Task 3: `extract` command + CLI

**Files:**
- Modify: `requirements-dev.txt`
- Modify: `tools/load_reports.py` (append extract section and CLI section)
- Test: `tools/test_load_reports.py`

**Interfaces:**
- Consumes: `parse_filename`, `file_sha256`, Task 2 cleanup functions, `LoaderError`, `STAGING`, `MINIO_ENV`, `redact`.
- Produces: `read_json(path: Path)` (UTF-8 with or without BOM; `None` if the file is missing; raises `ValueError` on bad JSON); `write_json(path: Path, data: dict) -> None`; `read_pages(pdf: Path) -> tuple[list[str], str]` (pages, `"pdfplumber"` or `"pypdf"`; `LoaderError(code=2)` if neither imports); `extract_one(pdf: Path, staging: Path, force: bool) -> str` (one summary line); `cmd_extract(staging: Path, paths: list[Path], force: bool) -> int`; `main(argv: list[str] | None = None) -> int`.
- `staging/<id>/meta.json` keys (program-owned, consumed by Tasks 4-5): `id, file_sha256, source_path, published_on, ticker, market, firm, title, pages, body_pages, cut_heading, chars, url_count, smartphone_hits, extractor, extracted_at, loaded` (`loaded` = `{target: ISO time}`, filled by Task 5, kept on `--force`). The PDF itself is not copied.

- [ ] **Step 1: Add the PDF libraries (owner-only, so the dev file)**

`requirements-dev.txt` becomes:
```
-r requirements.txt
pytest>=8
Pillow>=10
pgserver>=0.1.4
pdfplumber>=0.11,<1
pypdf>=4,<7
```

Run: `pip install -r requirements-dev.txt`. Colleagues never run the loader, so `requirements.txt` (what `install.ps1` installs) is unchanged. If the PC already has pypdf 6.x, pip downgrades it to 5.x; that is expected.

- [ ] **Step 2: Write failing tests**

The test builds its own tiny PDF (Helvetica text, one stream per page, correct xref offsets), so no fixture files and no new deps. The `extractor` fixture runs every extract test once with pdfplumber and once with pypdf (pdfplumber hidden via `sys.modules`).

Append to `tools/test_load_reports.py`:
```python
# ---------- extract ----------

def make_pdf(path: Path, pages: list[list[str]]) -> None:
    """Write a minimal valid PDF: one Helvetica text stream per page, one line per entry."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
        stream = "BT /F1 10 Tf 14 TL 72 760 Td " + " ".join(f"({ln}) Tj T*" for ln in esc) + " ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


PDF_NAME = "06-Oct-2026_08-02-29-MU-USQ-JPMorgan-Micron_Mgmt_Mtg.PDF"
PDF_PAGES = [
    [HEADER, "Smartphone shipments rose", "in 3Q26 as demand recovered.", "1"],
    [HEADER, "Memory content per handset grows.", "2"],
    [HEADER, "Analyst Certification", "I certify that the views are mine.", "3"],
    [HEADER, "Important Disclosures", "Ratings definitions.", "4"],
]


@pytest.fixture
def pdf_dir(tmp_path):
    d = tmp_path / "pdfs"
    d.mkdir()
    make_pdf(d / PDF_NAME, PDF_PAGES)
    (d / "notes.txt").write_text("not a pdf", encoding="utf-8")
    return d


@pytest.fixture(params=["pdfplumber", "pypdf"])
def extractor(request, monkeypatch):
    pytest.importorskip(request.param)
    if request.param == "pypdf":
        monkeypatch.setitem(sys.modules, "pdfplumber", None)  # import pdfplumber -> ImportError
    return request.param


def test_extract_writes_staging_and_is_idempotent(pdf_dir, tmp_path, extractor, capsys):
    st = tmp_path / "staging"
    assert lr.main(["--staging", str(st), "extract", str(pdf_dir)]) == 0
    sha = hashlib.sha256((pdf_dir / PDF_NAME).read_bytes()).hexdigest()
    d = st / sha[:12]
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == sha[:12] and meta["file_sha256"] == sha
    assert (meta["firm"], meta["ticker"], meta["title"]) == ("JPMorgan", "MU", "Micron Mgmt Mtg")
    assert (meta["pages"], meta["body_pages"], meta["cut_heading"]) == (4, 2, "Analyst Certification")
    assert meta["extractor"] == extractor and meta["smartphone_hits"] == 3
    assert (d / "text.txt").read_text(encoding="utf-8") == (
        "[p.1]\nSmartphone shipments rose in 3Q26 as demand recovered.\n"
        "[p.2]\nMemory content per handset grows.\n"
    )
    assert not (d / "source.pdf").exists()
    out = capsys.readouterr().out
    assert "ok" in out and "notes.txt" not in out
    assert lr.main(["--staging", str(st), "extract", str(pdf_dir / PDF_NAME)]) == 0
    assert "skip" in capsys.readouterr().out


def test_extract_bad_name_fails_but_continues(pdf_dir, tmp_path, capsys):
    pytest.importorskip("pypdf")
    make_pdf(pdf_dir / "random.pdf", [["x"]])
    assert lr.main(["--staging", str(tmp_path / "st"), "extract", str(pdf_dir)]) == 1
    out = capsys.readouterr().out
    assert "FAIL random.pdf" in out and "ok" in out


def test_extract_without_any_pdf_library(pdf_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert lr.main(["--staging", str(tmp_path / "st"), "extract", str(pdf_dir)]) == 2
    assert "requirements-dev.txt" in capsys.readouterr().err
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tools/test_load_reports.py -v -k extract`
Expected: FAIL, `AttributeError: module 'load_reports' has no attribute 'main'`

- [ ] **Step 4: Implement the extract section**

Append to `tools/load_reports.py`:
```python
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
```

- [ ] **Step 5: Implement the CLI section (extract only for now)**

Append to `tools/load_reports.py` (this stays the last section of the file; Tasks 4 and 5 insert above it):
```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: 25 passed, none skipped (a skipped `[pdfplumber]` or `[pypdf]` case means Step 1's install did not happen).
By hand: `python tools/load_reports.py extract -h` prints the usage with Korean help text.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tools
git commit -m "feat(reports): extract command (pdfplumber/pypdf -> staging text.txt + meta.json)"
```

---

### Task 4: Triage/annotate schemas, `status`, `triage-report`

**Files:**
- Modify: `tools/load_reports.py` (insert triage/annotate section above `# ---------- CLI ----------`; extend `main`)
- Test: `tools/test_load_reports.py`

**Interfaces:**
- Consumes: `read_json`, `meta.json` keys from Task 3.
- Produces: `KINDS`, `RELEVANCE`, `TOPICS`, `TRIAGE_KEYS`, `ANNOTATE_KEYS`; `validate_triage(t) -> list[str]`; `decide(t: dict) -> bool`; `validate_annotate(a, meta: dict) -> list[str]`; `report_state(d: Path) -> dict` with keys `id, dir, meta, triage, t_err, load (None | bool), annotate, a_err` (annotate is read only when `load` is true); `all_states(staging: Path) -> list[dict]` sorted by `(published_on, firm, id)`, skipping folders without `meta.json` (so `staging/localpg/` is ignored); `md_table(cols, rows) -> list[str]`; `cmd_status(staging) -> int`; `cmd_triage_report(staging) -> int` (writes `staging/triage.md`).
- File contracts (the Task 7 handoff restates these rules for the agent):

`triage.json` (agent; the owner may add `"load"`):
```json
{"kind": "company_update", "relevance": "high", "reason": "아이폰 부품 수요 전망이 주제"}
```

| key | rule |
|---|---|
| `kind` | one of `link_digest, weekly_note, company_update, industry_deep_dive, mgmt_meeting, other` |
| `relevance` | `high` (smartphone / handset / phone-component market, shipments or OEMs are the subject), `medium` (other subject with a smartphone-demand section), `low` (unrelated) |
| `reason` | one non-empty line (Korean) |
| `load` | optional, owner only, `true`/`false`; overrides the rule |

Decision rule (`decide`): load ⇔ `relevance ∈ {high, medium}` and `kind != link_digest`, unless `load` is present.

`annotate.json` (agent, only for reports whose decision is load):

| key | rule | stored as |
|---|---|---|
| `title` | one line ≤ 300 chars; required when the filename had no title, optional override otherwise | `title` |
| `ticker` | optional, one line ≤ 20 chars, overrides the filename ticker | `ticker` |
| `analyst` | optional, one line ≤ 100 chars | `analyst` |
| `summary_ko` | list of exactly 3 one-line Korean sentences | `summary` = 3 lines + `\n` + `summary_en` |
| `summary_en` | one English line | (in `summary`) |
| `keywords_ko`, `keywords_en` | 1-10 one-line strings each, no commas; joined length ≤ 500 | `keywords` = ko + en joined with `", "` |
| `topics` | ≥ 1 distinct values from `스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시` | `topics` joined with `", "` |
| `key_numbers` | string, may be `""` | `key_numbers` (`""` → NULL) |

`report_type` = triage `kind`. Unknown keys are errors (catches typos such as `summery_ko`).

- [ ] **Step 1: Write failing tests**

Append to `tools/test_load_reports.py`:
```python
# ---------- triage / annotate / status ----------

GOOD_TRIAGE = {"kind": "company_update", "relevance": "high", "reason": "아이폰 부품 수요 전망이 주제"}
GOOD_ANNOTATE = {
    "title": "Micron Technology: Mgmt Meeting, CY27 and CY28 Both Significantly Tight",
    "analyst": "Jane Doe",
    "summary_ko": ["HBM 수요가 2027년까지 공급을 웃돈다.", "모바일 DRAM 탑재량이 늘어난다.", "목표주가 상향."],
    "summary_en": "Management sees tight memory supply through CY28.",
    "keywords_ko": ["HBM", "모바일 DRAM"],
    "keywords_en": ["HBM", "mobile DRAM", "LPDDR5X"],
    "topics": ["메모리", "스마트폰"],
    "key_numbers": "CY27 DRAM bit growth 18%",
}
META = {"id": "a1b2c3d4e5f6", "file_sha256": "a1b2c3d4e5f6" + "0" * 52, "source_path": "x.pdf",
        "published_on": "2026-10-06", "ticker": "MU", "market": "USQ", "firm": "JPMorgan",
        "title": "Micron Technology Mgmt Mtg", "pages": 13, "body_pages": 7, "cut_heading": None,
        "chars": 100, "url_count": 0, "smartphone_hits": 4, "extractor": "pdfplumber",
        "extracted_at": "2026-10-13T10:00:00", "loaded": {}}


def test_validate_triage_ok_and_errors():
    assert lr.validate_triage(GOOD_TRIAGE) == []
    errs = lr.validate_triage({"kind": "news", "relevance": "hi", "reason": "a\nb", "load": "yes", "x": 1})
    assert len(errs) == 5
    assert lr.validate_triage([1]) == ["JSON 객체가 아닙니다"]


@pytest.mark.parametrize("kind,relevance,load,expect", [
    ("company_update", "high", None, True),
    ("industry_deep_dive", "medium", None, True),
    ("company_update", "low", None, False),
    ("link_digest", "high", None, False),
    ("link_digest", "high", True, True),
    ("company_update", "high", False, False),
])
def test_decide(kind, relevance, load, expect):
    t = {"kind": kind, "relevance": relevance, "reason": "r"}
    if load is not None:
        t["load"] = load
    assert lr.decide(t) is expect


def test_validate_annotate_ok_and_title_rule():
    assert lr.validate_annotate(GOOD_ANNOTATE, META) == []
    no_title = {k: v for k, v in GOOD_ANNOTATE.items() if k != "title"}
    assert lr.validate_annotate(no_title, META) == []  # filename title is used
    assert any("title" in e for e in lr.validate_annotate(no_title, {**META, "title": None}))


@pytest.mark.parametrize("patch,word", [
    ({"summary_ko": ["한 줄", "두 줄"]}, "summary_ko"),
    ({"summary_en": ""}, "summary_en"),
    ({"keywords_ko": [f"k{i}" for i in range(11)]}, "keywords_ko"),
    ({"keywords_en": ["a, b"]}, "keywords_en"),
    ({"topics": ["스마트폰", "반도체"]}, "topics"),
    ({"topics": []}, "topics"),
    ({"ticker": "X" * 21}, "ticker"),
    ({"key_numbers": None}, "key_numbers"),
    ({"summary": "x"}, "모르는 키"),
])
def test_validate_annotate_errors(patch, word):
    errs = lr.validate_annotate({**GOOD_ANNOTATE, **patch}, META)
    assert any(word in e for e in errs), errs


def write_report(st: Path, rid: str, triage=None, annotate=None, **meta) -> Path:
    d = st / rid
    d.mkdir(parents=True)
    lr.write_json(d / "meta.json", {**META, "id": rid, "file_sha256": rid + "0" * 52, **meta})
    (d / "text.txt").write_text(f"[p.1]\nBody of {rid}.\n", encoding="utf-8")
    if triage is not None:
        (d / "triage.json").write_text(triage if isinstance(triage, str) else json.dumps(triage), encoding="utf-8")
    if annotate is not None:
        lr.write_json(d / "annotate.json", annotate)
    return d


@pytest.fixture
def staging(tmp_path):
    st = tmp_path / "staging"
    write_report(st, "aaaaaaaaaaaa", GOOD_TRIAGE, GOOD_ANNOTATE)  # load, ready
    write_report(st, "bbbbbbbbbbbb", {**GOOD_TRIAGE, "relevance": "low", "reason": "서버 전용"})  # skip
    write_report(st, "cccccccccccc", {**GOOD_TRIAGE, "kind": "link_digest", "load": True})  # load (manual), no annotate
    write_report(st, "dddddddddddd", "{not json")  # broken triage
    write_report(st, "eeeeeeeeeeee", published_on="2026-01-01")  # untriaged
    return st


def test_status_lines(staging, capsys):
    assert lr.main(["--staging", str(staging), "status"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("eeeeeeeeeeee 2026-01-01")  # sorted by date
    by_id = {ln[:12]: ln for ln in lines}
    assert "triage=ok decision=load annotate=ok loaded=-" in by_id["aaaaaaaaaaaa"]
    assert "decision=skip annotate=n/a" in by_id["bbbbbbbbbbbb"]
    assert "decision=load* annotate=-" in by_id["cccccccccccc"]
    assert "triage=ERR" in by_id["dddddddddddd"]
    assert any(ln.startswith("    ! triage.json: JSON 오류") for ln in lines)
    assert lines[-1] == "(전체 5, 분류됨 3, 적재 대상 2, 주석 완료 1)"


def test_triage_report(staging, capsys):
    assert lr.main(["--staging", str(staging), "triage-report"]) == 0
    md = (staging / "triage.md").read_text(encoding="utf-8")
    assert "## 적재 (2)" in md and "## 제외 (1)" in md and "## 미분류·오류 (2)" in md
    assert "서버 전용" in md and "적재 (수동)" in md and "triage.json 없음" in md
    assert "적재 2" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/test_load_reports.py -v -k "triage or decide or annotate or status"`
Expected: FAIL, `AttributeError: module 'load_reports' has no attribute 'validate_triage'`

- [ ] **Step 3: Implement the triage/annotate section**

Insert in `tools/load_reports.py` directly above the `# ---------- CLI ----------` line:
```python
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
```

- [ ] **Step 4: Wire the two commands into `main`**

In `main()`, directly after the line `    s.add_argument("--force", action="store_true", help="이미 추출된 것도 다시 추출")` insert:
```python
    sub.add_parser("status", help="레포트별 단계 상태 한 줄씩")
    sub.add_parser("triage-report", help="staging/triage.md 생성")
```

In the `try:` block of `main()`, replace the line `        return cmd_extract(a.staging, a.paths, a.force)` with:
```python
        if a.cmd == "status":
            return cmd_status(a.staging)
        if a.cmd == "triage-report":
            return cmd_triage_report(a.staging)
        return cmd_extract(a.staging, a.paths, a.force)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: 44 passed

- [ ] **Step 6: Commit**

```bash
git add tools
git commit -m "feat(reports): triage/annotate validation, load decision rule, status and triage-report"
```

---

### Task 5: `load` command (local pgserver or company DSN, optional MinIO)

**Files:**
- Modify: `tools/load_reports.py` (insert load section above `# ---------- CLI ----------`; extend `main`)
- Test: `tools/test_load_reports.py`

**Interfaces:**
- Consumes: `all_states`, `write_json`, `redact`, `TABLE`, `MINIO_ENV`, `LoaderError`.
- Produces: `DDL` (`CREATE SCHEMA IF NOT EXISTS sales_team;` + the spec §3 table with `IF NOT EXISTS`); `COLUMNS` (insert columns, everything except `id`, `loaded_at`); `INSERT` (named placeholders); `slug(text: str) -> str`; `build_row(meta, triage, ann, body) -> dict` (keys == `COLUMNS`); `minio_client(url: str) -> tuple[client, bucket]`; `load_all(staging, dsn, target, create, minio_url) -> int`; `cmd_load(staging, local: bool, dsn_env: str | None, no_minio: bool) -> int`.
- `minio_key` = `reports/<slug(firm)>/<published_on>_<slug(title)[:60]>_<id[:6]>.pdf`, always computed (also with `--no-minio`). The 6-hex suffix keeps two same-day, same-title reports from overwriting each other's object.
- Per report: validate → `SELECT 1 … WHERE file_sha256 = %s` → if absent: MinIO `fput_object` (when enabled) then `INSERT`, all inside one `conn.transaction()`; a failure prints a redacted `FAIL` line and the loop continues. Success records `meta["loaded"][target]` (`target` = `"local"` or the env var name).
- `--local` implies no MinIO. Company mode needs `MI_MINIO_WRITE` unless `--no-minio`.

- [ ] **Step 1: Write failing tests**

Append to `tools/test_load_reports.py`:
```python
# ---------- load ----------

def test_build_row_joins_fields():
    row = lr.build_row(META, GOOD_TRIAGE, GOOD_ANNOTATE, "[p.1]\nbody\n")
    assert row["summary"] == "\n".join(GOOD_ANNOTATE["summary_ko"]) + "\n" + GOOD_ANNOTATE["summary_en"]
    assert row["keywords"] == "HBM, 모바일 DRAM, HBM, mobile DRAM, LPDDR5X"
    assert row["topics"] == "메모리, 스마트폰" and row["report_type"] == "company_update"
    assert row["minio_key"] == ("reports/JPMorgan/2026-10-06_Micron_Technology_Mgmt_Meeting_CY27_and_CY28_"
                                "Both_Significan_a1b2c3.pdf")
    assert (row["ticker"], row["market"], row["body_loaded"]) == ("MU", "USQ", True)
    assert set(row) == set(lr.COLUMNS)


def test_minio_client_parses_and_rejects():
    client, bucket = lr.minio_client("http://AK:p%40ss@minio.local:9000/mi-reports")
    assert bucket == "mi-reports"
    with pytest.raises(lr.LoaderError) as e:
        lr.minio_client("http://minio.local:9000/mi-reports")
    assert e.value.code == 2


def test_load_requires_minio_env_unless_no_minio(staging, monkeypatch, capsys):
    monkeypatch.delenv("MI_MINIO_WRITE", raising=False)
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://u:p@127.0.0.1:1/db")
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE"]) == 2
    assert "--no-minio" in capsys.readouterr().err


def test_load_never_prints_secrets_on_connect_failure(staging, monkeypatch, capsys):
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://writer:SECRETPW@127.0.0.1:1/db")
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 1
    cap = capsys.readouterr()
    assert "SECRETPW" not in cap.out + cap.err and "[load_reports]" in cap.err


class FakeMinio:
    def __init__(self):
        self.put = []

    def fput_object(self, bucket, key, path, content_type=None):
        self.put.append((bucket, key, path, content_type))


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    import psycopg

    with pgserver.get_server(tmp_path_factory.mktemp("pgdata")) as s:
        with psycopg.connect(s.get_uri(), autocommit=True) as c:
            c.execute(lr.DDL)  # stands in for the DBaaS team creating the table
            c.execute("CREATE DATABASE empty_db")
        yield s


def test_load_dsn_env_uploads_once_and_skips_existing(srv, staging, monkeypatch, capsys):
    import psycopg

    fake = FakeMinio()
    monkeypatch.setattr(lr, "minio_client", lambda url: (fake, "mi-reports"))
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", srv.get_uri())
    monkeypatch.setenv("MI_MINIO_WRITE", "http://AK:S%40CRET@minio.local:9000/mi-reports")
    argv = ["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE"]
    assert lr.main(argv) == 1  # cccccccccccc waits for annotate.json
    out = capsys.readouterr().out
    assert "loaded aaaaaaaaaaaa" in out and "wait cccccccccccc" in out
    assert "S@CRET" not in out and "S%40CRET" not in out
    assert [p[1] for p in fake.put] == ["reports/JPMorgan/2026-10-06_Micron_Technology_Mgmt_Meeting_CY27_and_"
                                        "CY28_Both_Significan_aaaaaa.pdf"]
    meta = json.loads((staging / "aaaaaaaaaaaa" / "meta.json").read_text(encoding="utf-8"))
    assert "MI_DB_REPORTS_WRITE" in meta["loaded"]
    assert lr.main(argv) == 1
    assert "exists aaaaaaaaaaaa" in capsys.readouterr().out and len(fake.put) == 1
    with psycopg.connect(srv.get_uri()) as c:
        rows = c.execute(f"SELECT firm, title, keywords, body, body_loaded FROM {lr.TABLE}").fetchall()
    assert rows == [("JPMorgan", GOOD_ANNOTATE["title"], "HBM, 모바일 DRAM, HBM, mobile DRAM, LPDDR5X",
                     "[p.1]\nBody of aaaaaaaaaaaa.\n", True)]


def test_load_dsn_env_refuses_missing_table(srv, staging, monkeypatch, capsys):
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", srv.get_uri("empty_db"))
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 1
    assert "DBaaS" in capsys.readouterr().err


def test_load_local_creates_table_and_accumulates(staging, capsys):
    pgserver = pytest.importorskip("pgserver")
    import psycopg

    (staging / "cccccccccccc" / "triage.json").write_text(json.dumps({**GOOD_TRIAGE, "relevance": "low"}),
                                                           encoding="utf-8")
    argv = ["--staging", str(staging), "load", "--local"]
    assert lr.main(argv) == 0
    assert "MinIO 건너뜀" in capsys.readouterr().out
    assert lr.main(argv) == 0
    assert "exists aaaaaaaaaaaa" in capsys.readouterr().out
    with pgserver.get_server(staging / "localpg") as s, psycopg.connect(s.get_uri()) as c:
        assert c.execute(f"SELECT count(*) FROM {lr.TABLE}").fetchone()[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tools/test_load_reports.py -v -k "build_row or minio or load_"`
Expected: FAIL, `AttributeError: module 'load_reports' has no attribute 'build_row'`

- [ ] **Step 3: Implement the load section**

Insert in `tools/load_reports.py` directly above the `# ---------- CLI ----------` line:
```python
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
```

- [ ] **Step 4: Wire `load` into `main`**

In `main()`, directly after the line `    sub.add_parser("triage-report", help="staging/triage.md 생성")` insert:
```python
    s = sub.add_parser("load", help="적재 대상을 DB(+MinIO)에 넣기")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--local", action="store_true", help="staging/localpg 내장 PostgreSQL (MinIO 안 씀)")
    g.add_argument("--dsn-env", help="쓰기 DSN이 든 환경변수 이름 (예: MI_DB_REPORTS_WRITE)")
    s.add_argument("--no-minio", action="store_true", help="MinIO 업로드 건너뛰기")
```

In the `try:` block, directly above the line `        return cmd_extract(a.staging, a.paths, a.force)` insert:
```python
        if a.cmd == "load":
            return cmd_load(a.staging, a.local, a.dsn_env, a.no_minio)
```

`main()` is now final:
```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tools/test_load_reports.py -v`
Expected: 51 passed, none skipped (three tests start pgserver; allow ~30 s).
Run: `python -m pytest tools scripts -q`
Expected: 99 passed (48 existing + 51).

- [ ] **Step 6: Commit**

```bash
git add tools
git commit -m "feat(reports): load command (local pgserver or company DSN, MinIO upload, idempotent on sha256)"
```

---

### Task 6: `sources/reports.md` + SKILL.md step

**Files:**
- Create: `sources/reports.md`
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: `query.py` front matter format and CLI (`sql reports "…"`, `schema reports`; `cmd_schema` already splits `schema.table`). Same env `MI_DB_SMARTPHONE`, so `install.ps1` is unchanged and colleagues need no reinstall.
- Commit now, but push only after the company table exists and is loaded (spec §9 step 6): until then a colleague's `sql reports …` fails with `relation "sales_team.nasdaq_report_doc" does not exist`.

- [ ] **Step 1: Write `sources/reports.md`**

````markdown
---
name: reports
kind: postgres
env: MI_DB_SMARTPHONE
tables: [sales_team.nasdaq_report_doc]
summary: 증권사 레포트 (스마트폰 관련만, 요약·키워드·영문 본문)
---
## 무엇이 들어 있나

- 스마트폰(완제품·부품·시장)과 관련된 증권사 레포트만 1건 = 1행으로 들어 있다. 관련 없는 레포트는 없다.
- `body` 는 PDF에서 뽑은 **영어 원문**이다. 면책·공시 부분은 잘라냈고, 각 쪽 앞에 `[p.N]` 페이지 표시가 있다.
- `summary`, `keywords` 는 한국어와 영어가 함께 있고, `topics` 는 한국어 고정 목록이다.

## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| id | 행 번호 | 2·3단계에서 레포트를 지정할 때 쓴다 |
| firm | 증권사 | 예: JPMorgan, Nomura |
| published_on | 발행일 | DATE |
| title | 제목 (영어) | |
| report_type | 종류 | weekly_note, company_update, industry_deep_dive, mgmt_meeting, other |
| topics | 주제, 쉼표로 이은 문자열 | 스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시 중에서 |
| analyst | 애널리스트 | 없을 수 있음 |
| pages | PDF 전체 쪽수 | |
| minio_key | 원본 PDF의 MinIO 키 | `fetch minio <키>` 는 `MI_MINIO` 가 같은 버킷을 가리킬 때만 된다 |
| file_sha256 | PDF 지문 | 중복 방지용. 조회에 쓸 일 없음 |
| summary | 요약: 한국어 3줄 + 영어 1줄 | |
| keywords | 키워드: 한국어 + 영어, 쉼표로 이은 문자열 | |
| key_numbers | 핵심 숫자 메모 (자유 서술) | 출처 페이지 `[p.N]` 이 붙어 있을 수 있다 |
| body | 본문 (영어 원문, `[p.N]` 표시) | 길다. 목록 조회에 넣지 않는다 |
| body_loaded | 본문 적재 여부 | 지금은 모두 true |
| loaded_at | 적재 시각 | |
| ticker | 티커 | 예: MU, AAPL. 산업 레포트는 비어 있음 |
| market | 거래소 코드 | 예: USQ |

## 자주 쓰는 쿼리

```sql
-- 1) 메타로 좁히기: 한국어 단어 그대로 찾는다. body 는 가져오지 않는다.
SELECT id, firm, published_on, title, topics, summary
FROM sales_team.nasdaq_report_doc
WHERE published_on >= DATE '2026-07-01'
  AND topics ILIKE '%스마트폰%'
  AND (keywords ILIKE '%폴더블%' OR keywords ILIKE '%foldable%' OR summary ILIKE '%폴더블%')
ORDER BY published_on DESC;

-- 2) 좁힌 id 안에서 본문 위치 찾기: 본문은 영어라서 영어 단어로 찾는다 (폴더블 = foldable).
SELECT id, firm, published_on, title,
       substring(body FROM greatest(strpos(lower(body), 'foldable') - 300, 1) FOR 800) AS snippet
FROM sales_team.nasdaq_report_doc
WHERE id IN (3, 7, 12) AND body ILIKE '%foldable%';

-- 3) 한 건의 본문 전체 읽기
SELECT firm, published_on, title, body
FROM sales_team.nasdaq_report_doc WHERE id = 7;
```

## 주의사항

- 무엇이 있는지 먼저 볼 때: `SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC`
- 답에는 근거마다 `(증권사, 발행일, 제목, [p.N])` 출처를 붙인다. 본문에 없는 내용은 지어내지 않고, 숫자는 본문 그대로 옮긴다.
- 문자열 안에 `update` 같은 단어를 따로 쓰면 SQL이 거부된다 (`report_type = 'company_update'` 는 괜찮다).
````

- [ ] **Step 2: Extend `SKILL.md`**

In the front matter `description:` line, replace
`MinIO 원본 파일 다운로드. "출하량"`
with
`MinIO 원본 파일 다운로드, 증권사 레포트(브로커 리서치) 검색·요약. "출하량"`
and replace
`"mi-sonar 설치 확인" 같은 요청에 사용.`
with
`"mi-sonar 설치 확인", "증권사 레포트", "리포트", "애널리스트", "broker report" 같은 요청에 사용.`

Insert directly above the line `## 제약 (스크립트가 강제함)`:
```markdown
## 증권사 레포트 찾기 (소스 `reports`)

스마트폰 관련 증권사 레포트 1건 = 1행 (`sales_team.nasdaq_report_doc`). 컬럼과 예시 쿼리는 `sources/reports.md`.

1. **좁히기**: `topics`, `keywords`, `summary`, `title` 을 질문의 한국어·영어 단어로 `ILIKE` 하고 증권사·기간으로 거른다. 이 단계에서는 `body` 를 SELECT 하지 않는다.
2. **본문 위치**: 좁힌 `id` 안에서 `body ILIKE '%영어 단어%'`. 본문은 영어 원문이므로 질문 단어를 영어로 바꿔 찾는다.
3. **읽기**: 필요한 레포트의 `body` 를 한 건씩 가져와 끝까지 읽고 한국어로 답한다. 본문에 없는 내용은 지어내지 않는다.
4. **출처**: 근거마다 `(증권사, 발행일, 제목, [p.N])` 를 붙인다. `[p.N]` 은 본문 속 페이지 표시 그대로다.
```

- [ ] **Step 3: Verify**

Run: `python scripts/query.py sources` → a `reports` row, kind `postgres`, env `MI_DB_SMARTPHONE`, Korean summary intact.

Run (Git Bash) to prove every example statement passes the read-only guard:
```bash
python - <<'EOF'
import re, sys
sys.path.insert(0, "scripts")
import query
text = open("sources/reports.md", encoding="utf-8").read()
block = re.search(r"```sql\n(.*?)```", text, re.S).group(1)
stmts = [s for s in (re.sub(r"--[^\n]*", "", x).strip() for x in block.split(";")) if s]
for s in stmts:
    query.check_sql(s)
print(len(stmts), "statements pass the guard")
EOF
```
Expected: `3 statements pass the guard`

Run: `python -m pytest tools scripts -q` → 99 passed.

- [ ] **Step 4: Commit**

```bash
git add sources/reports.md SKILL.md
git commit -m "docs(reports): reports source (read-only via MI_DB_SMARTPHONE) and SKILL.md search step"
```

---

### Task 7: In-company run order (`docs/handoff/reports-loader-run.md`)

**Files:**
- Create: `docs/handoff/reports-loader-run.md`

**Interfaces:**
- Consumes: CLI grammar (Tasks 3-5), file contracts (Task 4), `sources/reports.md` (Task 6).

- [ ] **Step 1: Write the run order**

````markdown
# Reports loader run (in-company, owner PC)

## Purpose

About 54 broker research PDFs (English) are on this PC. `tools/load_reports.py` turns the smartphone-relevant
ones into rows of `sales_team.nasdaq_report_doc`: one row per report with a cleaned English body (`[p.N]` page
markers), Korean + English summary and keywords. The program does the mechanical work. You (the agent) make the
judgements and write them into two small JSON files per report. You never write or edit body text.

| Stage | Who | What |
|---|---|---|
| 1. extract | program | `extract <PDF folder>` → `staging/<id>/text.txt` + `meta.json` |
| 2. triage | you | `staging/<id>/triage.json` for every report, then `triage-report` → `staging/triage.md` for the owner |
| 3. annotate | you | `staging/<id>/annotate.json` for every report whose decision is `load` |
| 4. load | program | `load --local` now; `load --dsn-env MI_DB_REPORTS_WRITE` once the company table exists |

`<id>` is the first 12 hex characters of the PDF's sha256. `status` shows every report on one line at any time.

## Rules

- Nothing leaves this PC except what `load` writes to the company DB and MinIO. Do not paste report text,
  `text.txt`, summaries or `triage.md` into chats, tickets, email, git or any other place. `staging/` is gitignored;
  keep it that way. `triage.md` goes to the owner only.
- `MI_DB_REPORTS_WRITE` and `MI_MINIO_WRITE` are set only in the current PowerShell window, never in a file, a
  commit or `install.ps1`. Never print or echo them. The tool masks them in every message.
- Never modify, move or delete the PDFs (one exception: renaming a misparsed file, stage 1).
- Never edit `text.txt` or `meta.json`. If a text looks wrong, report the id instead of working around it.
- Write JSON files as UTF-8. Work one report at a time: read it, write its JSON, check `status`, move on.

## 0. Preconditions

```powershell
python --version                       # 3.10 or newer
pip install -r requirements-dev.txt    # pdfplumber, pypdf, pgserver, pytest
python -m pytest tools scripts -q      # all pass before you start
```

## 1. Extract

```powershell
python tools/load_reports.py extract "D:\path\to\reports"    # the folder with the PDFs (.pdf or .PDF)
python tools/load_reports.py status
```

`extract` prints one line per PDF, for example
`ok   3f9a0c1d2e4b 2026-10-06 JPMorgan pages=13 body=7 cut=Analyst Certification phone=12 url=0 06-Oct-2026_…pdf`
(`body` = pages kept before the disclosure tail, `phone` = smartphone word count, `url` = link count).
Running it again skips PDFs that are already extracted. Check the output:

- `FAIL <file>: ValueError: 파일명 형식 불일치` → the name is not `DD-Mon-YYYY_HH-MM-SS-…`. Report it.
- Firm, ticker or title in `status` is clearly wrong (misparsed name) → with the owner's OK rename the PDF to
  `DD-Mon-YYYY_HH-MM-SS-<TICKER>-<MARKET>-<FIRM>-<Title_With_Underscores>.pdf` and run
  `python tools/load_reports.py extract --force "<renamed file>"`.
- `cut=-` (no `Analyst Certification` / `Important Disclosures` heading found) or `body` much smaller than half of
  `pages` → open `text.txt`. If the cut is clearly wrong (body missing, or pages of legal text left in), report the id
  and skip it.

## 2. Triage (every report)

For each id, read the WHOLE `staging/<id>/text.txt` (and `meta.json` for firm, date and signals). Then write
`staging/<id>/triage.json`:

```json
{"kind": "company_update", "relevance": "medium", "reason": "메모리 업체 레포트지만 스마트폰 DRAM 탑재량 전망 단락이 있음"}
```

- `kind`, exactly one of:
  - `link_digest`: mostly a list of links or headlines pointing to other reports or news, little own analysis
  - `weekly_note`: recurring weekly or periodic sector note covering several items
  - `company_update`: one company: earnings preview or review, estimate or rating change, reaction to news
  - `industry_deep_dive`: longer sector or thematic analysis (market size, supply chain, forecasts)
  - `mgmt_meeting`: write-up of a management meeting, investor day, conference meeting or site visit
  - `other`: anything else
- `relevance`, exactly one of:
  - `high`: the smartphone / handset / phone-component market, shipments or smartphone OEMs are the subject
  - `medium`: the subject is something else, but the report has a section on smartphone demand
    (example: a memory report with a mobile-demand section)
  - `low`: unrelated
- `reason`: one line, Korean, saying why.
- Do not write a `load` key. Only the owner adds it.
- The `phone` count is a hint only: 51 of the 54 reports mention smartphone words at least once.

The program decides: load ⇔ `relevance` is `high` or `medium` AND `kind` is not `link_digest`.

```powershell
python tools/load_reports.py status          # every line triage=ok; fix every "! triage.json:" line
python tools/load_reports.py triage-report   # writes staging/triage.md
```

Give `staging/triage.md` to the owner and wait. The owner may add `"load": true` or `"load": false` to a
`triage.json` to override the rule (shown as `decision=load*` / `skip*` in `status`). Run `triage-report` again
after any change. Excluded reports go nowhere: no DB row, no MinIO upload; `triage.md` is their only record.

## 3. Annotate (decision=load only)

For each report whose `status` line says `decision=load` (or `load*`), read the WHOLE `text.txt` again and write
`staging/<id>/annotate.json`:

```json
{
  "title": "Micron Technology: Mgmt Meeting - CY27 and CY28 Both Significantly Tight",
  "analyst": "Jane Doe",
  "summary_ko": [
    "경영진은 2027~2028년 메모리 공급이 크게 부족할 것으로 본다.",
    "AI 서버용 HBM과 함께 스마트폰 LPDDR5X 탑재량 증가가 수요를 받친다.",
    "증권사는 비중확대 의견과 상향된 목표주가를 유지했다."
  ],
  "summary_en": "Management expects memory supply to stay significantly tight through CY28, helped by rising smartphone LPDDR5X content.",
  "keywords_ko": ["HBM", "모바일 DRAM", "공급 부족", "목표주가"],
  "keywords_en": ["HBM", "LPDDR5X", "DRAM supply", "price target"],
  "topics": ["메모리", "스마트폰"],
  "key_numbers": "CY27 DRAM bit demand +18% YoY [p.2]; average smartphone DRAM content 9.5GB in 2027 [p.3]"
}
```

| key | rule |
|---|---|
| `title` | Required when the filename has no title (`status` shows `(제목 없음)`). Also write it when the filename title is cut off: copy the full title from page 1. One line, ≤ 300 characters. |
| `ticker` | Only if the filename had none and the report is about one listed company. ≤ 20 characters. Otherwise leave the key out. |
| `analyst` | Lead analyst if the name is visible. ≤ 100 characters. Otherwise leave the key out. |
| `summary_ko` | Exactly 3 strings, each one Korean sentence on one line. |
| `summary_en` | One English sentence on one line. |
| `keywords_ko`, `keywords_en` | 1 to 10 each. No commas inside a keyword. Company, product and technology names people would search for. |
| `topics` | 1 or more, no duplicates, only from: `스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시`. |
| `key_numbers` | The key figures, copied exactly with unit and period, each followed by its `[p.N]`. `""` if the report has none. |

No other keys. `report_type` comes from the triage `kind`; firm, date, market and the body come from the program.

Reading rules:

- Read the whole `text.txt` before writing anything. Do not skim the first page only.
- Summaries and keywords describe the report; they never replace or rewrite the body. Do not paraphrase the body
  into any file; the body is stored exactly as the program extracted it.
- Use only what the report says. No outside knowledge, no guesses. Copy numbers exactly.
- Korean summaries in plain Korean; keep English product and company names as they are.
- Keep to the fixed topics list; do not invent topics.

```powershell
python tools/load_reports.py status   # every load report shows annotate=ok; fix every "! annotate.json:" line
```

## 4. Load

### 4a. Local first (now)

```powershell
python tools/load_reports.py load --local
python tools/load_reports.py load --local    # second run: every line says "exists"
```

This uses an embedded PostgreSQL in `staging/localpg/` (schema `sales_team` and the table are created there) and no
MinIO. No company system is touched. Exit code 1 with `wait <id>` lines means some `annotate.json` is missing or
invalid; fix it and run again.

### 4b. Company DB (only after the owner confirms the table exists and the write account has its grants)

```powershell
$env:MI_DB_REPORTS_WRITE = "postgresql://USER:PASSWORD@HOST:5432/DBNAME"   # URL-encode special chars, e.g. @ -> %40
$env:MI_MINIO_WRITE      = "http://ACCESS:SECRET@HOST:9000/BUCKET"
python tools/load_reports.py load --dsn-env MI_DB_REPORTS_WRITE
Remove-Item Env:MI_DB_REPORTS_WRITE, Env:MI_MINIO_WRITE
```

- If the table does not exist yet the command stops with `테이블이 아직 없습니다` and writes nothing.
- Each report is one transaction: MinIO upload, then the row. A `FAIL <id>` line does not stop the others.
- Safe to re-run: a report whose `file_sha256` is already in the table is skipped and not uploaded again.
- `--no-minio` loads rows without uploading PDFs. Use it only if the owner says so.

Then check what colleagues will see (read-only account):

```powershell
python scripts/query.py sources    # reports: 설정됨
python scripts/query.py sql reports "SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC"
```

## Report back

- The last line of `status` and the summary line of each `load` run.
- Ids you could not triage or annotate, and why (no report text).
- Any `FAIL` lines (they contain no secrets).
````

- [ ] **Step 2: Verify the JSON examples against the validators**

Run (Git Bash):
```bash
python - <<'EOF'
import json, re, sys
sys.path.insert(0, "tools")
import load_reports as lr
text = open("docs/handoff/reports-loader-run.md", encoding="utf-8").read()
blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.S)]
print("triage:", lr.validate_triage(blocks[0]))
print("annotate:", lr.validate_annotate(blocks[1], {"title": None}))
EOF
```
Expected: `triage: []` and `annotate: []`.

Check: the only connection strings in the file are the `USER:PASSWORD@HOST` / `ACCESS:SECRET@HOST` templates.

- [ ] **Step 3: Commit**

```bash
git add docs/handoff/reports-loader-run.md
git commit -m "docs(reports): in-company run order for the four-stage loader"
```

---

## Self-review notes

- Spec coverage: §1 decisions → Global Constraints, Tasks 4-5 (skip = nowhere), Task 5 (local first). §2 storage (one table, MinIO for loaded only, staging local) → Tasks 1, 3, 5. §3 DDL → Task 5 `DDL` (column list and types verbatim). §4 cleanup rules 1-7 → Task 2 (`cut_disclosure`, `strip_repeated_lines`, `strip_page_numbers`, `join_wraps`, NFKC, `render_body`; tables kept because nothing drops long lines). §5 four stages, filename shapes, triage rubric and decision rule, annotate fields, staging layout, `status` / `triage-report`, idempotent load → Tasks 1, 3, 4, 5, 7. §6 retrieval via `sources/reports.md` + `sql` → Task 6. §8 open items are DBaaS/permission work, not code.
- Review Focus 1-8 pinned by tests in Tasks 1/3, 2, 2, 4/5, 3/5, 5, 5, 4.
- Placeholders: none in code. The handoff's `USER:PASSWORD@HOST` / `ACCESS:SECRET@HOST` are deliberate templates (same as `docs/handoff/db-capability-check.md`).
- Names used across tasks: `LoaderError`, `redact`, `parse_filename`, `file_sha256`, `strip_repeated_lines`, `cut_disclosure`, `strip_page_numbers`, `join_wraps`, `render_body`, `url_count`, `smartphone_hits`, `read_json`, `write_json`, `read_pages`, `extract_one`, `cmd_extract`, `validate_triage`, `decide`, `validate_annotate`, `report_state`, `all_states`, `md_table`, `cmd_status`, `cmd_triage_report`, `DDL`, `COLUMNS`, `INSERT`, `slug`, `build_row`, `minio_client`, `load_all`, `cmd_load`, `main`. Consistent.
- Deviation from the work order: the `requirements-dev.txt` change moved from Task 6 to Task 3, because Task 3's tests need pdfplumber and pypdf installed (otherwise they would only skip).
- For the owner: the requested pin `pypdf>=4,<7` downgrades this PC's pypdf 6.14. The loader only uses `PdfReader(path).pages` and `page.extract_text()`, which exist unchanged in 4.x-6.x; drop the `<6` cap if the in-company pypdf is already 6.x.
- Skipped on purpose: a local SQL console for `staging/localpg` (verify with `status` and the load summary; the pgserver tests cover the rows), indexes (spec §3: none requested now), re-loading changed rows (rows are insert-once by sha256; delete the row first to replace it).
- All code in this plan was run before writing it down: 51 tests pass on Python 3.10 with pdfplumber 0.11.10, pypdf 6.14.2 and pgserver 0.1.4; the three example queries in `sources/reports.md` pass `check_sql` and run against the DDL with Korean `ILIKE`.
