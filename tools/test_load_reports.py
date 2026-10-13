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
