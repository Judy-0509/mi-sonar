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
python -m pytest -q                    # all pass before you start
```

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
extracted (matched by sha256, unless `--force`). Check the output:

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
  - `firm_analysis`: short analysis article from a research firm (TechInsights), saved from pasted text as a `.md` file
  - `other`: anything else
- `relevance`, exactly one of:
  - `high`: the smartphone / handset / phone-component **or smartwatch** market, shipments or OEMs are the subject
  - `medium`: the subject is something else, but the report has a section on smartphone / handset / phone-component **or smartwatch** demand
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
| `topics` | 1 or more, no duplicates, only from: `스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시, 스마트워치`. |
| `key_numbers` | The key figures, copied exactly with unit and period, each followed by its `[p.N]`. `""` if the report has none. |

For `kind` = `firm_analysis`: `keywords_en` MUST include every vendor name and every country / region named in the article (for example `Apple, Huawei, China, India`) and `keywords_ko` their Korean forms; `key_numbers` quotes every shipment and growth figure verbatim with `[p.1]`.

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

**Owner only, typed by hand. The agent stops after 4a and reports.** Never put these values in a command an agent runs or in a file.

```powershell
# Prompts without echo and without shell history. DSN: postgresql://USER:PASSWORD@HOST:5432/DBNAME (URL-encode special chars, e.g. @ -> %40)
# MinIO: http://ACCESS:SECRET@HOST:9000/BUCKET
$env:MI_DB_REPORTS_WRITE = [Net.NetworkCredential]::new('', (Read-Host 'MI_DB_REPORTS_WRITE' -AsSecureString)).Password
$env:MI_MINIO_WRITE      = [Net.NetworkCredential]::new('', (Read-Host 'MI_MINIO_WRITE' -AsSecureString)).Password
python tools/load_reports.py load --dsn-env MI_DB_REPORTS_WRITE
Remove-Item Env:MI_DB_REPORTS_WRITE, Env:MI_MINIO_WRITE
```

- If the table does not exist yet the command stops with `테이블이 아직 없습니다` and writes nothing.
- Each report is one transaction: the row is inserted first, then the PDF is uploaded; an upload failure rolls the row back. A `FAIL <id>` line does not stop the others.
- Safe to re-run: a report whose `file_sha256` is already in the table is skipped and not uploaded again.
- `--no-minio` loads rows without uploading PDFs. Use it only if the owner says so.

Then check what colleagues will see (read-only account):

```powershell
python skills/mi-sonar/scripts/query.py sources    # reports: 설정됨
python skills/mi-sonar/scripts/query.py sql reports "SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC"
```

## Report back

- The last line of `status` and the summary line of each `load` run.
- Ids you could not triage or annotate, and why (no report text).
- Any `FAIL` lines (they contain no secrets).
