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
    kept, heading = lr.cut_disclosure(pages, lr.load_dicts().cutoff)
    assert heading == "Analyst Certification"
    assert kept == pages[:2] + ["Last body paragraph."]


def test_cut_disclosure_heading_at_page_top_and_none():
    cutoff = lr.load_dicts().cutoff
    pages = ["p1", "p2", "IMPORTANT DISCLOSURES\nlegal"]
    assert lr.cut_disclosure(pages, cutoff) == (["p1", "p2"], "IMPORTANT DISCLOSURES")
    assert lr.cut_disclosure(["p1", "p2"], cutoff) == (["p1", "p2"], None)


def test_cut_disclosure_dict_phrase_heading_only():
    long = "Disclaimer: the figures above are estimates and should not be relied upon by any investor"
    pages = ["Disclosure Appendix", f"Body two.\n{long}\nMore body.", "Body three.\nDisclosure Appendix\nlegal", "x"]
    assert lr.cut_disclosure(pages, lr.load_dicts().cutoff) == (pages[:2] + ["Body three."], "Disclosure Appendix")


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


# ---------- dictionaries, paragraphs, tagging ----------

def test_load_dicts_real_files():
    d = lr.load_dicts()
    assert len(d.tickers) >= 134 and len(d.cutoff) >= 8
    assert [t for t, _ in d.topics] == ["ai", "smartphone", "auto", "smartwatch", "smartglass", "tablet", "humanoid"]
    assert ("005930-KRX", "Samsung Electronics", ["Samsung", "Samsung Electronics", "SEC", "삼성전자"]) in d.tickers
    assert all(len(kws) >= 8 for _, kws in d.topics)  # seed size; the owner may add more
    assert lr.tag_text("EV/EBITDA of 8x; EVs and electric vehicles", d)[1] == ["auto"]
    assert lr.tag_text("EV/EBITDA of 8x on pixel density gains", d)[1] == []
    assert lr.tag_text("Google Pixel 10 and Google Pixel Watch 4", d)[1] == ["smartphone", "smartwatch"]
    assert lr.tag_text("Google Pixel Watch 4 only", d)[1] == ["smartwatch"]


def dict_dir(tmp_path, tickers: str) -> Path:
    d = tmp_path / "dict"
    d.mkdir()
    (d / "tickers.csv").write_text("ticker,name,aliases\n" + tickers, encoding="utf-8")
    (d / "topics.csv").write_text("# 주제\ntopic,keywords\nai,AI|GPU\n", encoding="utf-8-sig")  # Excel writes a BOM
    (d / "cutoff.csv").write_text("phrase\nDisclaimer\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("rows,words", [
    ("AAPL-USQ,Apple,Apple\n# comment\nAAPL-USQ,Apple Inc,AAPL\n", ["tickers.csv 4행", "중복"]),
    ("AAPL-USQ,Apple,Apple||AAPL\n", ["tickers.csv 2행", "별칭"]),
    ("AAPL-USQ,Apple,\n", ["tickers.csv 2행", "별칭"]),
    (",Apple,Apple\n", ["tickers.csv 2행", "ticker"]),
    ("AAPL-USQ,Apple\n", ["tickers.csv 2행"]),
])
def test_load_dicts_errors(tmp_path, rows, words):
    with pytest.raises(lr.LoaderError) as e:
        lr.load_dicts(dict_dir(tmp_path, rows))
    assert all(w in str(e.value) for w in words), str(e.value)


def test_load_dicts_small_dir(tmp_path):
    d = lr.load_dicts(dict_dir(tmp_path, "AAPL-USQ,Apple,Apple | AAPL\n"))
    assert (d.tickers, d.topics, d.cutoff) == ([("AAPL-USQ", "Apple", ["Apple", "AAPL"])], [("ai", ["AI", "GPU"])],
                                              ["Disclaimer"])


def test_split_paragraphs_pages_numbering_and_merge():
    body = ("[p.1]\nFirst paragraph of page one.\nThis line has no period but is long enough\nSource: Company data\n"
            "[p.3]\nShort heading\nThird page text.\nFigure 2\n")
    assert lr.split_paragraphs(body) == [
        {"page": 1, "para_no": 1, "text": "First paragraph of page one."},
        {"page": 1, "para_no": 2, "text": "This line has no period but is long enough Source: Company data"},
        {"page": 3, "para_no": 3, "text": "Short heading"},
        {"page": 3, "para_no": 4, "text": "Third page text. Figure 2"},
    ]
    assert lr.split_paragraphs("") == []


@pytest.mark.parametrize("terms,text,hit", [
    (["SEC"], "SEC raised DRAM prices", True),
    (["SEC"], "the sec rules", False),
    (["SEC"], "in the second half", False),
    (["Apple"], "apple shipped more", True),
    (["Apple"], "Pineapple exports", False),
    (["Galaxy S"], "the Galaxy S series", True),
    (["Galaxy S"], "the galaxy s series", True),
    (["삼성전자"], "삼성전자는 올해", True),
    (["하이닉스"], "SK하이닉스가", True),
    (["Micron"], "Microns are small", False),
    (["Micron"], "Micron's view", True),
    (["AI"], "AIR quality", False),
    (["AI"], "said the AI team", True),
    (["AI"], "ai demand", False),
    (["a.b"], "axb", False),
])
def test_compile_matcher(terms, text, hit):
    assert bool(lr.compile_matcher(terms).search(text)) is hit


DICTS = lr.Dicts(
    tickers=[("AAPL-USQ", "Apple", ["Apple"]), ("005930-KRX", "Samsung Electronics", ["Samsung", "SEC"]),
             ("006400-KRX", "Samsung SDI", ["Samsung SDI"])],
    topics=[("smartwatch", ["smartwatch", "Apple Watch"]), ("tablet", ["tablet", "iPad"])],
    cutoff=["Disclaimer"])


def test_tag_text_longest_term_wins():
    assert lr.compile_matcher(["Samsung", "Samsung SDI"]).search("Samsung SDI cells").group() == "Samsung SDI"
    assert lr.tag_text("Samsung SDI ships cells.", DICTS) == (["006400-KRX"], [])
    assert lr.tag_text("SEC and APPLE: Apple Watch, iPad and a tablet", DICTS) == (
        ["005930-KRX", "AAPL-USQ"], ["smartwatch", "tablet"])
    assert lr.tag_paragraphs([{"page": 2, "para_no": 1, "text": "iPad"}], DICTS) == [
        {"page": 2, "para_no": 1, "text": "iPad", "tickers": [], "topics": ["tablet"]}]


def test_derive_share_and_title():
    texts = ["Apple grew.", "Apple again.", "Samsung once.", "smartwatch here.", "smartwatch two."] + ["plain."] * 5
    paras = lr.tag_paragraphs([{"page": 1, "para_no": i, "text": t} for i, t in enumerate(texts, 1)], DICTS)
    assert lr.derive(paras, "Samsung tablet outlook", DICTS) == {
        "tickers": {"AAPL-USQ": 2, "005930-KRX": 1}, "topics": {"smartwatch": 2},
        "doc_tickers": ["AAPL-USQ", "005930-KRX"], "doc_topics": ["smartwatch", "tablet"], "paragraphs": 10}
    assert lr.derive(paras, None, DICTS)["doc_tickers"] == ["AAPL-USQ"]  # Samsung: 1 of 10 < 20%
    fifteen = lr.tag_paragraphs([{"page": 1, "para_no": i, "text": "Apple." if i <= 3 else "x."}
                                 for i in range(1, 16)], DICTS)
    assert lr.derive(fifteen, None, DICTS)["doc_tickers"] == ["AAPL-USQ"]  # 3 of 15 is 20% (0.2 * 15 > 3 in floats)
    assert lr.derive([], "", DICTS) == {"tickers": {}, "topics": {}, "doc_tickers": [], "doc_topics": [],
                                        "paragraphs": 0}


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
    (d / "notes.docx").write_text("not a pdf", encoding="utf-8")
    return d


TRIED_FIRST = {"pymupdf": [], "pdfplumber": ["pymupdf", "fitz"], "pypdf": ["pymupdf", "fitz", "pdfplumber"]}


@pytest.fixture(params=list(TRIED_FIRST))
def extractor(request, monkeypatch):
    pytest.importorskip(request.param)
    for name in TRIED_FIRST[request.param]:  # import X -> ImportError, so read_pages falls through to the next one
        monkeypatch.setitem(sys.modules, name, None)
    return request.param


class FakeDoc(list):
    """Stand-in for a pymupdf Document: iterable pages, usable in `with`."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePage:
    def __init__(self, text):
        self.text = text

    def get_text(self, kind):
        assert kind == "text"
        return self.text


def test_read_pages_prefers_pymupdf_then_legacy_fitz(tmp_path, monkeypatch):
    import types

    fake = types.SimpleNamespace(open=lambda path: FakeDoc([FakePage("page one\n"), FakePage("page two\n")]))
    monkeypatch.setitem(sys.modules, "pymupdf", fake)
    assert lr.read_pages(tmp_path / "x.pdf") == (["page one\n", "page two\n"], "pymupdf")
    monkeypatch.setitem(sys.modules, "pymupdf", None)  # before 1.24 the module was only importable as fitz
    monkeypatch.setitem(sys.modules, "fitz", fake)
    assert lr.read_pages(tmp_path / "x.pdf") == (["page one\n", "page two\n"], "pymupdf")


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
    assert "ok" in out and "notes.docx" not in out
    assert lr.main(["--staging", str(st), "extract", str(pdf_dir / PDF_NAME)]) == 0
    assert "skip" in capsys.readouterr().out


def test_extract_bad_name_fails_but_continues(pdf_dir, tmp_path, capsys):
    pytest.importorskip("pypdf")
    make_pdf(pdf_dir / "random.pdf", [["x"]])
    assert lr.main(["--staging", str(tmp_path / "st"), "extract", str(pdf_dir)]) == 1
    out = capsys.readouterr().out
    assert "FAIL random.pdf" in out and "ok" in out


def test_extract_without_any_pdf_library(pdf_dir, tmp_path, monkeypatch, capsys):
    for name in ("pymupdf", "fitz", "pdfplumber", "pypdf"):
        monkeypatch.setitem(sys.modules, name, None)
    assert lr.main(["--staging", str(tmp_path / "st"), "extract", str(pdf_dir)]) == 2
    assert "requirements-dev.txt" in capsys.readouterr().err


# ---------- text articles (.md / .txt) ----------

ART_NAME = "06-Oct-2026_00-00-00-TechInsights-Smartwatch_Q3_Analysis.md"
ART_TEXT = ("\ufeff# Smartwatch Q3 2026: Apple regains share\nApple shipped 12.3m units in\nQ3, up 8% YoY.\n\n"
            "2026\nHuawei grew in China.\n")


def test_parse_filename_article():
    assert lr.parse_filename(ART_NAME) == {
        "published_on": "2026-10-06", "ticker": None, "market": None, "firm": "TechInsights",
        "title": "Smartwatch Q3 Analysis"}


def test_extract_text_article(tmp_path, capsys):
    src = tmp_path / "in"
    src.mkdir()
    (src / ART_NAME).write_bytes(ART_TEXT.encode("utf-8"))
    st = tmp_path / "st"
    assert lr.main(["--staging", str(st), "extract", str(src / ART_NAME)]) == 0
    d = st / hashlib.sha256((src / ART_NAME).read_bytes()).hexdigest()[:12]
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Smartwatch Q3 2026: Apple regains share"  # `# ` line beats the filename title
    assert (meta["firm"], meta["pages"], meta["body_pages"], meta["extractor"], meta["cut_heading"]) == (
        "TechInsights", 1, 1, "text", None)
    assert (d / "text.txt").read_text(encoding="utf-8") == (
        "[p.1]\nApple shipped 12.3m units in Q3, up 8% YoY.\n2026 Huawei grew in China.\n")
    capsys.readouterr()
    assert lr.main(["--staging", str(st), "extract", str(src / ART_NAME)]) == 0
    assert "skip" in capsys.readouterr().out


def test_extract_zip_of_articles(tmp_path, capsys):
    import zipfile
    zp = tmp_path / "new_reports.zip"
    other = "07-Oct-2026_00-00-00-TechInsights-Watch_Q3_Note.md"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(ART_NAME, ART_TEXT)
        z.writestr(other, "# Watch Note\nSome text.\n")
        z.writestr("../evil.md", "x")
    st = tmp_path / "st"
    assert lr.main(["--staging", str(st), "extract", str(zp)]) == 0
    out = capsys.readouterr().out
    assert "SKIP ../evil.md (path outside folder)" in out
    assert not (tmp_path / "evil.md").exists() and not (st / "inbox" / "evil.md").exists()
    assert (st / "inbox" / "new_reports" / ART_NAME).exists()
    lr.main(["--staging", str(st), "status"])
    assert "(전체 2," in capsys.readouterr().out
    lr.main(["--staging", str(st), "extract", str(zp)])
    assert capsys.readouterr().out.count("skip ") == 2


def test_extract_text_without_heading_and_upper_ext(tmp_path):
    f = tmp_path / "07-Oct-2026_00-00-00-TechInsights-Watch_Note.TXT"
    f.write_text("Plain paragraph.\n", encoding="utf-8")
    st = tmp_path / "st"
    assert lr.main(["--staging", str(st), "extract", str(f)]) == 0
    meta = json.loads(next(st.glob("*/meta.json")).read_text(encoding="utf-8"))
    assert meta["title"] == "Watch Note" and meta["extractor"] == "text"


def test_extract_mixed_folder_and_minio_extension(pdf_dir, tmp_path, capsys):
    pytest.importorskip("pypdf")
    (pdf_dir / ART_NAME).write_text(ART_TEXT, encoding="utf-8")
    st = tmp_path / "st"
    assert lr.main(["--staging", str(st), "extract", str(pdf_dir)]) == 0
    assert len(list(st.glob("*/meta.json"))) == 2
    assert "(파일 2개" in capsys.readouterr().out
    meta = next(m for m in (json.loads(f.read_text(encoding="utf-8")) for f in st.glob("*/meta.json"))
                if m["extractor"] == "text")
    assert lr.build_row(meta, {**GOOD_TRIAGE, "kind": "firm_analysis"}, GOOD_ANNOTATE, "b",
                        NO_TAGS)["minio_key"].endswith(".md")


# ---------- triage / annotate / status ----------

GOOD_TRIAGE = {"kind": "company_update", "reason": "아이폰 부품 수요 전망이 주제"}
GOOD_ANNOTATE = {
    "title": "Micron Technology: Mgmt Meeting, CY27 and CY28 Both Significantly Tight",
    "analyst": "Jane Doe",
    "thesis": "메모리 공급 부족이 2028년까지 이어져 스마트폰 DRAM 가격이 오른다.",
    "summary_ko": ["메모리 공급 부족이 2028년까지 이어진다.", "HBM 수요가 2027년까지 공급을 웃돈다 [p.2].",
                   "모바일 DRAM 탑재량이 늘어난다 [p.3]."],
    "summary_en": "Management sees tight memory supply through CY28.",
    "keywords_ko": ["HBM", "모바일 DRAM"],
    "keywords_en": ["HBM", "mobile DRAM", "LPDDR5X"],
    "key_numbers": "CY27 DRAM bit growth 18%",
}
NO_TAGS = {"doc_tickers": [], "doc_topics": []}
REPORT_TEXT = ("[p.1]\nApple will raise iPhone builds as smartphone demand recovers.\n"
               "Samsung Electronics and Apple both expand foldable lines.\nSource: company data\n"
               "[p.2]\nHBM supply for AI servers stays tight through 2027.\n")
META = {"id": "a1b2c3d4e5f6", "file_sha256": "a1b2c3d4e5f6" + "0" * 52, "source_path": "x.pdf",
        "published_on": "2026-10-06", "ticker": "MU", "market": "USQ", "firm": "JPMorgan",
        "title": "Micron Technology Mgmt Mtg", "pages": 13, "body_pages": 7, "cut_heading": None,
        "chars": 100, "url_count": 0, "smartphone_hits": 4, "extractor": "pdfplumber",
        "extracted_at": "2026-10-13T10:00:00", "loaded": {}}


def test_validate_triage_ok_and_errors():
    assert lr.validate_triage(GOOD_TRIAGE) == []
    errs = lr.validate_triage({"kind": "news", "relevance": "high", "reason": "a\nb", "load": "yes", "x": 1})
    assert len(errs) == 5
    assert any("모르는 키: relevance (프로그램이 주제 사전으로 산출)" in e for e in errs)
    assert lr.validate_triage([1]) == ["JSON 객체가 아닙니다"]


@pytest.mark.parametrize("kind,relevance,load,expect", [
    ("company_update", "high", None, True),
    ("industry_deep_dive", "medium", None, True),
    ("company_update", "low", None, False),
    ("link_digest", "high", None, False),
    ("link_digest", "high", True, True),
    ("company_update", "high", False, False),
    ("firm_analysis", "high", None, True),
    ("firm_analysis", "low", None, False),
])
def test_decide(kind, relevance, load, expect):
    t = {"kind": kind, "reason": "r"}
    if load is not None:
        t["load"] = load
    assert lr.decide(t, relevance) is expect


def test_low_load_override_stays_loaded(tmp_path):
    st = tmp_path / "staging"
    write_report(st, "aaaaaaaaaaaa", {**GOOD_TRIAGE, "load": True})
    assert lr.report_state(st / "aaaaaaaaaaaa", lr.load_dicts())["load"] is True


def test_relevance_from_derived():
    assert lr.relevance({"doc_topics": ["smartphone"], "topics": {"smartphone": 3}}) == "high"
    assert lr.relevance({"doc_topics": [], "topics": {"ai": 1}}) == "medium"
    assert lr.relevance({"doc_topics": [], "topics": {}}) == "low"


def test_validate_annotate_ok_and_title_rule():
    assert lr.validate_annotate(GOOD_ANNOTATE, META) == []
    assert lr.validate_annotate({**GOOD_ANNOTATE, "summary_ko": ["주장."] + ["근거 [p.1]"] * 5}, META) == []
    assert lr.validate_triage({**GOOD_TRIAGE, "kind": "firm_analysis"}) == []
    no_title = {k: v for k, v in GOOD_ANNOTATE.items() if k != "title"}
    assert lr.validate_annotate(no_title, META) == []  # filename title is used
    assert any("title" in e for e in lr.validate_annotate(no_title, {**META, "title": None}))


@pytest.mark.parametrize("patch,word", [
    ({"summary_ko": ["한 줄", "두 줄"]}, "summary_ko"),
    ({"summary_en": ""}, "summary_en"),
    ({"keywords_ko": [f"k{i}" for i in range(11)]}, "keywords_ko"),
    ({"keywords_en": ["a, b"]}, "keywords_en"),
    ({"topics": ["스마트폰"]}, "모르는 키: topics"),
    ({"scope": ["market"]}, "모르는 키: scope"),
    ({"ticker": "X" * 21}, "ticker"),
    ({"key_numbers": None}, "key_numbers"),
    ({"summary": "x"}, "모르는 키"),
    ({"summary_ko": ["주장.", "근거 [p.2]"] * 3 + ["근거 [p.3]"]}, "summary_ko"),
    ({"summary_ko": ["주장.", "페이지 표시 없는 근거", "근거 [p.2]"]}, "[p.N]"),
    ({"thesis": "짧은 주장"}, "thesis"),
    ({"thesis": "첫 줄\n둘째 줄 주장입니다"}, "thesis"),
])
def test_validate_annotate_errors(patch, word):
    errs = lr.validate_annotate({**GOOD_ANNOTATE, **patch}, META)
    assert any(word in e for e in errs), errs


def test_validate_annotate_requires_thesis():
    errs = lr.validate_annotate({k: v for k, v in GOOD_ANNOTATE.items() if k != "thesis"}, META)
    assert any("thesis" in e for e in errs), errs


def write_report(st: Path, rid: str, triage=None, annotate=None, text=None, **meta) -> Path:
    d = st / rid
    d.mkdir(parents=True)
    lr.write_json(d / "meta.json", {**META, "id": rid, "file_sha256": rid + "0" * 52, **meta})
    (d / "text.txt").write_text(text or f"[p.1]\nBody of {rid}.\n", encoding="utf-8")
    if triage is not None:
        (d / "triage.json").write_text(triage if isinstance(triage, str) else json.dumps(triage), encoding="utf-8")
    if annotate is not None:
        lr.write_json(d / "annotate.json", annotate)
    return d


@pytest.fixture
def staging(tmp_path):
    st = tmp_path / "staging"
    write_report(st, "aaaaaaaaaaaa", GOOD_TRIAGE, GOOD_ANNOTATE,
                text="[p.1]\nsmartphone demand.\n")  # load, ready
    write_report(st, "bbbbbbbbbbbb", {**GOOD_TRIAGE, "reason": "서버 전용"})  # skip
    write_report(st, "cccccccccccc", {**GOOD_TRIAGE, "kind": "link_digest", "load": True})  # load (manual), no annotate
    write_report(st, "dddddddddddd", "{not json")  # broken triage
    write_report(st, "eeeeeeeeeeee", published_on="2026-01-01")  # untriaged
    return st


def test_status_lines(staging, capsys):
    assert lr.main(["--staging", str(staging), "status"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("eeeeeeeeeeee 2026-01-01")  # sorted by date
    by_id = {ln[:12]: ln for ln in lines}
    assert "triage=ok rel=high decision=load annotate=ok loaded=- tickers=MU-USQ topics=smartphone paras=1  " in by_id["aaaaaaaaaaaa"]
    assert "rel=low decision=skip annotate=n/a" in by_id["bbbbbbbbbbbb"]
    assert "decision=load* annotate=-" in by_id["cccccccccccc"]
    assert "triage=ERR" in by_id["dddddddddddd"]
    assert any(ln.startswith("    ! triage.json: JSON 오류") for ln in lines)
    assert lines[-1] == "(전체 5, 분류됨 3, 적재 대상 2, 주석 완료 1)"


def test_triage_report(staging, capsys):
    assert lr.main(["--staging", str(staging), "triage-report"]) == 0
    md = (staging / "triage.md").read_text(encoding="utf-8")
    assert "## 적재 (2)" in md and "## 제외 (1)" in md and "## 미분류·오류 (2)" in md
    assert "서버 전용" in md and "적재 (수동)" in md and "triage.json 없음" in md
    assert "| 제목 | 티커(자동) | 주제(자동) | 종류 | 관련도(자동) |" in md
    assert "| Micron Technology Mgmt Mtg | MU-USQ | smartphone | company_update | high |" in md
    assert "규칙: 관련도(주제 사전으로 자동 산출)가 high 또는 medium 이고 kind 가 link_digest 가 아니면 적재합니다." in md
    assert "적재 2" in capsys.readouterr().out


def test_paragraphs_view_and_id_prefix(tmp_path, capsys):
    st = tmp_path / "staging"
    write_report(st, "abc123456789", GOOD_TRIAGE, GOOD_ANNOTATE, text=REPORT_TEXT, cut_heading="Analyst Certification")
    write_report(st, "abd123456789")
    assert lr.main(["--staging", str(st), "paragraphs", "abc1"]) == 0
    out = capsys.readouterr().out
    assert "| # | p. | tickers | topics | text |" in out
    assert "| 1 | 1 | AAPL-USQ | smartphone | Apple will raise iPhone builds" in out
    assert ("| 2 | 1 | 005930-KRX, AAPL-USQ | smartphone | Samsung Electronics and Apple both expand foldable lines. "
            "Source: company data |") in out
    assert "| 3 | 2 |  | ai | HBM supply" in out
    assert "티커별 문단 수: AAPL-USQ 2, 005930-KRX 1" in out and "주제별 문단 수: smartphone 2, ai 1" in out
    assert "): AAPL-USQ, 005930-KRX, MU-USQ" in out  # MU-USQ from the title only
    assert "Analyst Certification" in out and "7/13" in out
    long = "x" * 150 + "."
    write_report(st, "fff000000000", text=f"[p.1]\n{long}\n")
    lr.main(["--staging", str(st), "paragraphs", "fff"])
    assert "x" * 100 + " |" in capsys.readouterr().out
    assert lr.main(["--staging", str(st), "paragraphs", "ab"]) == 1
    err = capsys.readouterr().err
    assert "abc123456789" in err and "abd123456789" in err
    assert lr.main(["--staging", str(st), "paragraphs", "zzz"]) == 1
    assert "zzz" in capsys.readouterr().err


# ---------- load ----------

def test_build_row_joins_fields():
    derived = {"doc_tickers": ["AAPL-USQ", "MU-USQ"], "doc_topics": ["smartphone", "ai"]}
    row = lr.build_row(META, GOOD_TRIAGE, GOOD_ANNOTATE, "[p.1]\nbody\n", derived)
    assert row["summary"] == "\n".join(GOOD_ANNOTATE["summary_ko"]) + "\n" + GOOD_ANNOTATE["summary_en"]
    assert row["keywords"] == "HBM, 모바일 DRAM, HBM, mobile DRAM, LPDDR5X"
    assert row["topics"] == "smartphone, ai" and row["report_type"] == "company_update"
    assert (row["thesis"], row["scope"]) == (GOOD_ANNOTATE["thesis"], "AAPL-USQ, MU-USQ")
    many = [f"T{i:03d}-USQ" for i in range(40)]  # a comps table: 40 x 10 chars > VARCHAR(300)
    row = lr.build_row(META, GOOD_TRIAGE, GOOD_ANNOTATE, "b", {"doc_tickers": many, "doc_topics": []})
    assert (row["scope"], row["topics"]) == (", ".join(many[:30]), None)
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
        paras = c.execute(f"SELECT page, para_no, text FROM {lr.PARA_TABLE}").fetchall()
    assert rows == [("JPMorgan", GOOD_ANNOTATE["title"], "HBM, 모바일 DRAM, HBM, mobile DRAM, LPDDR5X",
                     "[p.1]\nsmartphone demand.\n", True)]
    assert paras == [(1, 1, "smartphone demand.")]


def test_load_dsn_env_refuses_missing_table(srv, staging, monkeypatch, capsys):
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", srv.get_uri("empty_db"))
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 1
    assert "DBaaS" in capsys.readouterr().err
    import psycopg

    with psycopg.connect(srv.get_uri("empty_db")) as c:  # no DDL ran: neither the table nor its schema exists
        assert c.execute("SELECT to_regclass(%s)", (lr.TABLE,)).fetchone()[0] is None
        assert c.execute("SELECT to_regnamespace('sales_team')").fetchone()[0] is None


def test_load_dsn_env_refuses_missing_para_table(srv, staging, monkeypatch, capsys):
    import psycopg

    with psycopg.connect(srv.get_uri(), autocommit=True) as c:
        c.execute("CREATE DATABASE doc_only_db")
    with psycopg.connect(srv.get_uri("doc_only_db"), autocommit=True) as c:
        c.execute(lr.DDL)
        c.execute(f"DROP TABLE {lr.PARA_TABLE}")  # the DBaaS team created only the doc table
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", srv.get_uri("doc_only_db"))
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 1
    err = capsys.readouterr().err
    assert "nasdaq_report_para" in err and "DBaaS" in err
    with psycopg.connect(srv.get_uri("doc_only_db")) as c:
        assert c.execute(f"SELECT count(*) FROM {lr.TABLE}").fetchone()[0] == 0


def test_load_local_creates_table_and_accumulates(staging, capsys):
    pgserver = pytest.importorskip("pgserver")
    import psycopg

    (staging / "cccccccccccc" / "triage.json").write_text(json.dumps(GOOD_TRIAGE),
                                                           encoding="utf-8")
    (staging / "aaaaaaaaaaaa" / "text.txt").write_text(REPORT_TEXT, encoding="utf-8")
    argv = ["--staging", str(staging), "load", "--local"]
    assert lr.main(argv) == 0
    out = capsys.readouterr().out
    assert "MinIO 건너뜀" in out and "paras=3" in out
    assert lr.main(argv) == 0
    assert "exists aaaaaaaaaaaa" in capsys.readouterr().out
    with pgserver.get_server(staging / "localpg") as s, psycopg.connect(s.get_uri()) as c:
        assert c.execute(f"SELECT count(*) FROM {lr.TABLE}").fetchone()[0] == 1
        doc_id, thesis, topics, scope = c.execute(f"SELECT id, thesis, topics, scope FROM {lr.TABLE}").fetchone()
        assert (thesis, topics, scope) == (GOOD_ANNOTATE["thesis"], "smartphone, ai", "AAPL-USQ, 005930-KRX, MU-USQ")
        paras = c.execute(f"SELECT doc_id, page, para_no, tickers, topics, text FROM {lr.PARA_TABLE} "
                          "ORDER BY para_no").fetchall()  # after the second run: still 3 rows
    assert [p[:5] for p in paras] == [(doc_id, 1, 1, "AAPL-USQ", "smartphone"),
                                      (doc_id, 1, 2, "005930-KRX, AAPL-USQ", "smartphone"),
                                      (doc_id, 2, 3, None, "ai")]
    assert paras[1][5].endswith("foldable lines. Source: company data")


# ---------- fix wave ----------

def test_load_local_with_non_ascii_staging_path(tmp_path):
    pytest.importorskip("pgserver")
    st = tmp_path / "★ 한글"
    write_report(st, "aaaaaaaaaaaa", GOOD_TRIAGE, GOOD_ANNOTATE)
    assert lr.main(["--staging", str(st), "load", "--local"]) == 0


@pytest.mark.parametrize("secret", ["postgresql://writer:TOPSECRET@h/db", "bad name"])
def test_dsn_env_must_be_a_name_and_is_not_echoed(staging, capsys, secret):
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", secret]) == 2
    cap = capsys.readouterr()
    assert "TOPSECRET" not in cap.out + cap.err and secret not in cap.out + cap.err


@pytest.mark.parametrize("dsn,tails", [
    ("postgresql://writer:Pa@ssW0rd@127.0.0.1:1/db", ["ssW0rd", "Pa@ss"]),
    ("postgresql://writer:Pa%40ssW0rd@127.0.0.1:1/db", ["ssW0rd", "Pa%40ss", "Pa@ss"]),
    ("postgresql://writer:ZZsecretZZ@127.0.0.1:1/db", ["ZZsecretZZ"]),
])
def test_load_never_leaks_password_fragments(staging, monkeypatch, capsys, dsn, tails):
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", dsn)
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) in (1, 2)
    cap = capsys.readouterr()
    for t in tails:
        assert t not in cap.out + cap.err


def test_unencoded_at_in_dsn_password_is_refused(staging, monkeypatch, capsys):
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://writer:Pa@ssW0rd@127.0.0.1:1/db")
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 2
    assert "%40" in capsys.readouterr().err


def test_extract_cuts_heading_with_ligature(tmp_path, monkeypatch):
    pdf = tmp_path / "06-Oct-2026_08-02-29-JPMorgan.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    pages = ["p1", "body\nAnalyst Certi\ufb01cation\nI certify", "more"]
    monkeypatch.setattr(lr, "read_pages", lambda p: (pages, "fake"))
    lr.extract_one(pdf, tmp_path / "st", False, lr.load_dicts().cutoff)
    meta = json.loads(next((tmp_path / "st").glob("*/meta.json")).read_text(encoding="utf-8"))
    assert meta["cut_heading"] is not None and "I certify" not in next((tmp_path / "st").glob("*/text.txt")).read_text(encoding="utf-8")


def test_need_missing_package_is_setup_error():
    with pytest.raises(lr.LoaderError) as e:
        lr.need("no_such_package_xyz")
    assert e.value.code == 2


def test_failed_upload_rolls_back_row(srv, staging, monkeypatch, capsys):
    import psycopg

    with psycopg.connect(srv.get_uri(), autocommit=True) as c:
        c.execute("CREATE DATABASE m1_db")

    class Boom(FakeMinio):
        def fput_object(self, *a, **k):
            raise OSError("upload down")

    with psycopg.connect(srv.get_uri("m1_db"), autocommit=True) as c:
        c.execute(lr.DDL)
    monkeypatch.setattr(lr, "minio_client", lambda url: (Boom(), "b"))
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", srv.get_uri("m1_db"))
    monkeypatch.setenv("MI_MINIO_WRITE", "http://AK:S@minio.local:9000/b")
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE"]) == 1
    assert "FAIL aaaaaaaaaaaa" in capsys.readouterr().out
    with psycopg.connect(srv.get_uri("m1_db")) as c:
        assert c.execute(f"SELECT count(*) FROM {lr.TABLE}").fetchone()[0] == 0
        assert c.execute(f"SELECT count(*) FROM {lr.PARA_TABLE}").fetchone()[0] == 0


def test_triage_json_with_bom_is_read(tmp_path, capsys):
    st = tmp_path / "staging"
    d = write_report(st, "aaaaaaaaaaaa", GOOD_TRIAGE, GOOD_ANNOTATE)
    (d / "triage.json").write_text(json.dumps(GOOD_TRIAGE), encoding="utf-8-sig")
    assert lr.main(["--staging", str(st), "status"]) == 0
    assert "ERR" not in capsys.readouterr().out


def test_load_redacts_secret_inside_driver_exception(staging, monkeypatch, capsys):
    import psycopg

    def boom(*a, **k):
        raise psycopg.OperationalError("connection failed: password=ZZsecretZZ host=x")

    monkeypatch.setattr(psycopg, "connect", boom)
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://writer:ZZsecretZZ@127.0.0.1:1/db")
    assert lr.main(["--staging", str(staging), "load", "--dsn-env", "MI_DB_REPORTS_WRITE", "--no-minio"]) == 1
    cap = capsys.readouterr()
    assert "ZZsecretZZ" not in cap.out + cap.err
