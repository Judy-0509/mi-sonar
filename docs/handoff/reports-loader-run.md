# Reports loader run (in-company, owner PC)

## Purpose

About 54 broker research PDFs (English) are on this PC. `tools/load_reports.py` turns the smartphone-relevant
ones into rows of `sales_team.nasdaq_report_doc`: one row per report with a cleaned English body (`[p.N]` page
markers), Korean + English summary and keywords. Each loaded report's paragraphs also go to
`sales_team.nasdaq_report_para`, tagged with tickers and topics by the dictionaries in `tools/dict/`. The program does
the mechanical work, including all ticker and topic tagging. You (the agent) make the judgements and write them into
two small JSON files per report. You never write or edit body text.

| Stage | Who | What |
|---|---|---|
| 1. extract | program | `extract <PDF folder>` → `staging/<id>/text.txt` + `meta.json` |
| 2. triage | you | `staging/<id>/triage.json` for every report, then `triage-report` → `staging/triage.md` for the owner |
| 3. annotate | you | `staging/<id>/annotate.json` for every report whose decision is `load` |
| 3b. check tags | you + owner | `paragraphs <id>`: each paragraph's tickers and topics; the owner fixes `tools/dict/*.csv` |
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
pip install -r requirements-dev.txt    # pymupdf, pdfplumber, pypdf, pgserver, pytest
python -m pytest -q                    # all pass before you start
```

pymupdf is the preferred PDF extractor; `extract` falls back to pdfplumber, then pypdf, and `meta.json` records which
one ran (`extractor`). If pymupdf is missing, install it on its own: `pip install pymupdf`.

## 1. Extract

```powershell
python tools/load_reports.py extract "D:\path\to\reports"    # the folder with the PDFs (.pdf or .PDF)
python tools/load_reports.py status
```

`extract` prints one line per PDF, for example
`ok   3f9a0c1d2e4b 2026-10-06 JPMorgan pages=13 body=7 cut=Analyst Certification phone=12 url=0 06-Oct-2026_…pdf`
(`body` = pages kept before the disclosure tail, `phone` = smartphone word count, `url` = link count).
Pasted TechInsights articles (`.md`, saved in `staging/inbox`) can go in the same call, e.g.
`python tools/load_reports.py extract "D:\path\to\reports" staging/inbox`. Running it again skips files that are already
extracted (matched by sha256, unless `--force`).
A `.zip` of new PDFs can be passed directly (`extract "D:\new_reports.zip"`); it is unpacked under `staging/inbox/`.
Check the output:

- `FAIL <file>: ValueError: 파일명 형식 불일치` → the name is not `DD-Mon-YYYY_HH-MM-SS-…`. Report it.
- Firm, ticker or title in `status` is clearly wrong (misparsed name) → with the owner's OK rename the PDF to
  `DD-Mon-YYYY_HH-MM-SS-<TICKER>-<MARKET>-<FIRM>-<Title_With_Underscores>.pdf` and run
  `python tools/load_reports.py extract --force "<renamed file>"`.
- `cut=-` (no heading from `tools/dict/cutoff.csv` found) or `body` much smaller than half of
  `pages` → open `text.txt`. If the cut is clearly wrong (body missing, or pages of legal text left in), report the id
  and skip it.

## 2. Triage (every report)

For each id, read the WHOLE `staging/<id>/text.txt` (and `meta.json` for firm, date and signals). Then write
`staging/<id>/triage.json`:

```json
{"kind": "company_update", "reason": "메모리 업체 레포트지만 스마트폰 DRAM 탑재량 전망 단락이 있음"}
```

- `kind`, exactly one of:
  - `link_digest`: mostly a list of links or headlines pointing to other reports or news, little own analysis
  - `weekly_note`: recurring weekly or periodic sector note covering several items
  - `company_update`: one company: earnings preview or review, estimate or rating change, reaction to news
  - `industry_deep_dive`: longer sector or thematic analysis (market size, supply chain, forecasts)
  - `mgmt_meeting`: write-up of a management meeting, investor day, conference meeting or site visit
  - `firm_analysis`: short analysis article from a research firm (TechInsights), saved from pasted text as a `.md` file
  - `other`: anything else
- Do not write `relevance`: the program derives it from the topic dictionary tags (`tools/dict/topics.csv`), and a `relevance` key is an error.
  - `high`: an application topic is document-level (>= 20% of paragraphs or in the title)
  - `medium`: no document-level topic, but at least one paragraph has a topic tag
  - `low`: no paragraph has a topic tag
- The agent writes only `kind` and `reason`.
- `reason`: one line, Korean, saying why.
- Do not write a `load` key. Only the owner adds it.
- The `phone` count is a hint only: 51 of the 54 reports mention smartphone words at least once.

The program decides: load ⇔ derived relevance is `high` or `medium` AND `kind` is not `link_digest`.
If a report is `low` but should load, add keywords to `tools/dict/topics.csv` (preferred) or set `"load": true`.

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
  "thesis": "AI 서버 HBM과 스마트폰 LPDDR5X 수요로 메모리 공급 부족이 2028년까지 이어진다.",
  "summary_ko": [
    "경영진은 2027~2028년 메모리 공급이 크게 부족할 것으로 본다.",
    "2027년 DRAM 비트 수요는 전년 대비 18% 늘어난다 [p.2].",
    "스마트폰 평균 DRAM 탑재량이 2027년 9.5GB로 늘어 수요를 받친다 [p.3].",
    "증권사는 비중확대 의견과 상향된 목표주가를 유지했다 [p.1]."
  ],
  "summary_en": "Management expects memory supply to stay significantly tight through CY28, helped by rising smartphone LPDDR5X content.",
  "keywords_ko": ["HBM", "모바일 DRAM", "공급 부족", "목표주가"],
  "keywords_en": ["HBM", "LPDDR5X", "DRAM supply", "price target"],
  "key_numbers": "CY27 DRAM bit demand +18% YoY [p.2]; average smartphone DRAM content 9.5GB in 2027 [p.3]"
}
```

| key | rule |
|---|---|
| `title` | Required when the filename has no title (`status` shows `(제목 없음)`). Also write it when the filename title is cut off: copy the full title from page 1. One line, ≤ 300 characters. |
| `ticker` | Only if the filename had none and the report is about one listed company. ≤ 20 characters. Otherwise leave the key out. |
| `analyst` | Lead analyst if the name is visible. ≤ 100 characters. Otherwise leave the key out. |
| `thesis` | Required. The report's own claim in one Korean sentence on one line, 10 to 300 characters. Not a topic label. |
| `summary_ko` | 3 to 6 strings, each one Korean sentence on one line. Line 1 restates the thesis or the main claim. Lines 2 and after are supporting points and each contains its `[p.N]`. |
| `summary_en` | One English sentence on one line. |
| `keywords_ko`, `keywords_en` | 1 to 10 each. No commas inside a keyword. Company, product and technology names people would search for. |
| `key_numbers` | The key figures, copied exactly with unit and period, each followed by its `[p.N]`. `""` if the report has none. |

Do not write `scope` or `topics`: the program derives the report's tickers and topics from the paragraph tags
(section 3b). Either key in `annotate.json` is an error (`모르는 키`).

For `kind` = `firm_analysis`: `keywords_en` MUST include every vendor name and every country / region named in the article (for example `Apple, Huawei, China, India`) and `keywords_ko` their Korean forms; `key_numbers` quotes every shipment and growth figure verbatim with `[p.1]`.

No other keys. `report_type` comes from the triage `kind`; firm, date, market and the body come from the program.

Reading rules:

- Read the whole `text.txt` before writing anything. Do not skim the first page only.
- Summaries and keywords describe the report; they never replace or rewrite the body. Do not paraphrase the body
  into any file; the body is stored exactly as the program extracted it.
- Use only what the report says. No outside knowledge, no guesses. Copy numbers exactly.
- Korean summaries in plain Korean; keep English product and company names as they are.

```powershell
python tools/load_reports.py status   # every load report shows annotate=ok; fix every "! annotate.json:" line
```

## 3b. Check the tags (`paragraphs <id>`)

Nobody judges tickers or topics. The program splits `text.txt` into paragraphs (one line = one paragraph; a line under
40 characters not ending in `.` `?` `!` joins the paragraph before it) and tags each paragraph with the dictionaries.
A report's tickers (DB column `scope`) and topics are those in at least 20% of its paragraphs or in its title. `status`
shows them on every line (`tickers=… topics=… paras=…`) and `triage.md` has the columns `티커(자동)` / `주제(자동)`.

```powershell
python tools/load_reports.py paragraphs 3f9a    # the id or its first characters
```

It prints one row per paragraph (number, page, tickers, topics, first 100 characters), then the counts per ticker and
topic, the report-level result, the cut heading and pages kept / total. This is how the owner verifies a report.

Wrong or missing tags are fixed in the dictionaries, never in JSON files. The agent drafted them (2026-10-14); from now
on only the owner edits them:

- `tools/dict/tickers.csv` (`ticker,name,aliases`): aliases separated by `|`,
  e.g. `005930-KRX,Samsung Electronics,Samsung|Samsung Electronics|SEC|삼성전자`.
- `tools/dict/topics.csv` (`topic,keywords`): the 7 topics `ai, smartphone, auto, smartwatch, smartglass, tablet,
  humanoid` and their keywords.
- `tools/dict/cutoff.csv` (`phrase`): headings where the disclosure tail starts (page 2+, a line of ≤ 60 characters
  starting with the phrase, any case).

Matching: English terms match whole words only (`Micron` does not hit `Microns`), Korean terms match anywhere. Terms
of 4+ characters ignore case; shorter ones (`SEC`, `AI`) must match exactly. Where terms overlap the longer one wins.
Lines starting with `#` are comments; save as UTF-8. A dictionary edit applies on the next `status` / `paragraphs` /
`load` without re-extracting, because paragraphs and tags are recomputed from `text.txt` every run. Exceptions: a
`cutoff.csv` change needs `extract --force` for the affected reports, and reports already loaded are not changed.
Commit the CSVs: they hold names and keywords only, no report content.

## 4. Load

### 4a. Local first (now)

```powershell
python tools/load_reports.py load --local
python tools/load_reports.py load --local    # second run: every line says "exists"
```

This uses an embedded PostgreSQL in `staging/localpg/` (schema `sales_team` and both tables are created there) and no
MinIO. No company system is touched. Exit code 1 with `wait <id>` lines means some `annotate.json` is missing or
invalid; fix it and run again.

### 4b. Company DB (only after the owner confirms the table exists and the write account has its grants)

**Owner only, typed by hand. The agent stops after 4a and reports.** Never put these values in a command an agent runs or in a file.

```powershell
# Prompts without echo and without shell history. DSN: postgresql://USER:PASSWORD@HOST:5432/DBNAME (URL-encode special chars, e.g. @ -> %40)
# MinIO: http://ACCESS:SECRET@HOST:9000/BUCKET
$env:MI_DB_REPORTS_WRITE = [Net.NetworkCredential]::new('', (Read-Host 'MI_DB_REPORTS_WRITE' -AsSecureString)).Password
$env:MI_MINIO_WRITE      = [Net.NetworkCredential]::new('', (Read-Host 'MI_MINIO_WRITE' -AsSecureString)).Password
python tools/load_reports.py load --dsn-env MI_DB_REPORTS_WRITE
Remove-Item Env:MI_DB_REPORTS_WRITE, Env:MI_MINIO_WRITE
```

- If either table (`nasdaq_report_doc`, `nasdaq_report_para`) does not exist yet the command stops with
  `테이블이 아직 없습니다`, naming the table, and writes nothing.
- Each report is one transaction: the report row and its paragraph rows are inserted first, then the PDF is uploaded; an upload failure rolls the rows back. A `FAIL <id>` line does not stop the others.
- Safe to re-run: a report whose `file_sha256` is already in the table is skipped and not uploaded again.
- `--no-minio` loads rows without uploading PDFs. Use it only if the owner says so.

Then check what colleagues will see (read-only account):

```powershell
python skills/mi-sonar/scripts/query.py sources    # reports: 설정됨
python skills/mi-sonar/scripts/query.py sql reports "SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC"
```

## DBaaS request (pending)

The owner sends this; the agent does not. The `thesis` / `scope` columns of `nasdaq_report_doc` are already requested.
Add the paragraph table to the pending request:

```
[추가 요청] sales_team 스키마에 테이블 1개 생성 (nasdaq_report_doc 의 문단 테이블)
1. 테이블 이름: sales_team.nasdaq_report_para
2. DDL:
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
3. 인덱스: 추가 요청 없음 (UNIQUE (doc_id, para_no) 가 만드는 것만)
용도: 증권사 레포트 본문을 문단 단위로 저장 (레포트당 수십 행, 주 약 150건). 레포트 행을 지우면 문단도 함께 지워짐.
```

Grants are requested separately, as for the report table: the write account needs SELECT, INSERT and USAGE on
`sales_team.nasdaq_report_para_id_seq`; the read account (`MI_DB_SMARTPHONE`) needs SELECT.

## Report back

- The last line of `status` and the summary line of each `load` run.
- Ids you could not triage or annotate, and why (no report text).
- Any `FAIL` lines (they contain no secrets).
