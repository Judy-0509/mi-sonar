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
