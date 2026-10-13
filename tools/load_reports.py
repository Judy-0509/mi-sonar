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
