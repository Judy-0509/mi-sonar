# Reports extraction probe (run once, hand back `reports_probe.md`)

## Purpose

Broker (sell-side) research reports, about 100 PDFs, English, are already downloaded on an in-company PC.
Plan: a program does the mechanical cleanup, an agent writes a summary and keywords per report, then rows go into
PostgreSQL `sales_team.nasdaq_report_doc` (one row per report, full cleaned body in a `body` column with `[p.N]`
page markers) and the PDFs go to MinIO. Before building the loader we need to see what the extracted text actually
looks like. This probe touches no DB and no MinIO. Nothing leaves the PC.

## Rules

- Read-only on the PDFs. Never modify, move or rename them.
- No DB, no MinIO, no network (other than `pip install`).
- Do NOT include credentials, hostnames or internal URLs in anything you write.
- Report facts, not fixes. If something is ambiguous, show the excerpt and say what is unclear.
- Do NOT paste full reports. Every excerpt is verbatim and at most 15 lines. The final report stays under ~400 lines.

## Filename convention (verify it against all files)

Example:

```
06-Oct-2026_08-02-29-MU-USQ-JPMorgan-Micron_Technology_Mgmt_Mtg__CY27_and_CY28_Both_Significantly_Ti.pdf
```

Pattern: `DD-Mon-YYYY_HH-MM-SS-<TICKER>-<MARKET>-<FIRM>-<TITLE_WITH_UNDERSCORES>.pdf`. The title may be truncated.

## Steps

### 0. Preconditions

- Python 3.10 or newer.
- `pip install pypdf`. If `pdfplumber` also installs, extract with both for comparison; if not, use pypdf only.
- Work in a scratch folder `reports_probe/` next to the PDFs:

  ```powershell
  python --version
  pip install pypdf
  pip install pdfplumber   # optional
  New-Item -ItemType Directory -Force reports_probe
  ```

### 1. Filename census

List all PDFs and parse each name with a regex for the pattern above. Report:

- total PDF count;
- how many names parse cleanly, and every name that does not fit, verbatim;
- count per FIRM;
- date range (earliest and latest date);
- count per TICKER (top 10).

### 2. Pick 3 PDFs

Different firms. One with a two-column layout, one table-heavy. Say which three and why.

### 3. Page-by-page extraction

For each of the 3, extract text page by page and save `reports_probe/<name>.pages.txt` with `[p.N]` on its own line
before each page's text (N starts at 1).

### 4. Collect patterns (main output)

For each of the 3 reports:

- **Repeated header/footer lines**: lines that occur on 60% or more of the pages of a report (firm name, date, page
  numbers, "see disclosures"). List them verbatim.
- **Disclosure cut-off**: find the first page where a heading like `Important Disclosures`, `Analyst Certification`,
  `Disclosure Appendix`, `Legal Disclaimer` or `Regulatory Disclosures` appears. Report the page number, the exact
  heading text, and what share of total pages comes after it. If none found, say so.
- **Line-wrap behaviour**: do sentences break mid-line with hard newlines? Are paragraphs separated by blank lines?
  Does two-column text interleave (sentences from the two columns alternate)? Show one 10-line excerpt for each
  observed problem.
- **Tables and charts**: how do table pages come out (number soup, column labels, nothing)? Show one 10-line
  excerpt. Do charts leave stray axis labels?
- **First page metadata**: can firm, date, title, analyst name(s) and rating/target price be read from page 1 text?
  Show the first 15 lines of page 1.
- **Encoding oddities**: ligatures (ﬁ ﬂ), bullets, non-breaking spaces, garbled characters. List any.
- **Size**: pages, characters before and after cutting at the disclosure heading.

### 5. Smartphone-relevance word counts

For each of the 3, count occurrences (case-insensitive) of: `smartphone, handset, iPhone, Galaxy, Pixel, Snapdragon,
Exynos, Dimensity, MediaTek, shipments, sell-through, units`. Report as a table (rows = words, columns = the 3
reports). This only calibrates a first-pass filter; no judgement needed.

### 6. Write the report

Write `reports_probe/reports_probe.md` with sections 1 to 5 above (census, the 3 picks, patterns, word counts), each
excerpt at most 15 lines, verbatim, whole file under ~400 lines.

## Report back

Hand `reports_probe/reports_probe.md` to the owner (it contains no secrets). Nothing else leaves the PC: do not
upload the PDFs, the `.pages.txt` files or the report anywhere except to the owner.
