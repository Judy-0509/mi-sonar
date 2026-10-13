# Smartwatch data run (in-company, owner PC)

## Purpose

Two jobs, both done on this PC:

1. Convert the TechInsights smartwatch Excel files (quarterly actuals, annual forecast) and MI's own TAM sheet into
   CSV files and load them into `sales_team.smartwatch_market_data` with `tools/load_smartwatch.py`.
2. Turn the short TechInsights analysis article (3 to 4 paragraphs, about once per quarter between Excel releases)
   into a `.md` file and run it through the reports pipeline, so it lands in `sales_team.nasdaq_report_doc` as
   `report_type = firm_analysis`. The smartwatch TAM review step cites these articles later.

## Rules

- Nothing leaves this PC except what `load` writes to the company DB. Do not paste Excel contents, CSV rows, article
  text or `staging/` files into chats, tickets, email, git or any other place.
- `MI_DB_REPORTS_WRITE` is set only by the owner, typed by hand in the current PowerShell window. You never set,
  print or echo it. Stop after the `--local` load and report.
- Never modify, move or delete the Excel files or PDFs.
- Write CSV and Markdown files as UTF-8.

## 1. Excel to CSV

Output one file per publication month: `smartwatch_<YYYY-MM>.csv` (the publication month of the Excel file).
Columns and allowed values are defined by `python tools/load_smartwatch.py -h` and `skills/mi-sonar/sources/smartwatch.md`.
Rules the owner already approved:

- Common:
  - `vendor` is only one of Apple, Samsung, Huawei, Garmin, Fitbit, Others. Every other vendor is added into
    Others, and the row's `note` says `Others includes: <names>`.
  - Exclude total rows (Total / Worldwide / Global / regional subtotals). Exception: `our_tam` rows are
    Worldwide by design and are kept.
  - A blank cell, `-` or `n/a` creates no row.
  - `published_month` is the 1st of the file's publication month. If you cannot find it, ask the owner.
  - If the same key appears twice, stop and report; do not merge or pick one.
- Actuals: `dataset=actual`, `period` = `YYYYQn`, `country` as written in the Excel, `sell_in_mu` in million units
  (if the Excel is in thousands, divide by 1000).
- Forecast: `dataset=forecast`, `period` = `YYYY`, `revenue_musd` in million USD, `asp_usd` in USD, leave
  `sell_in_mu` empty (the program computes it). The forecast Excel has no units column.
- Our TAM: `dataset=our_tam`, `firm=MI`, `country=Worldwide`, `period` = `YYYYQn`, `sell_in_mu` in million units.
- Country names: if actuals and forecast spell a country differently, use the actuals spelling everywhere and report
  the list of changes.

Validation report (print it for the owner, numbers only):

- Row count per `dataset`.
- The list of quarters and years.
- Number of countries.
- For each country, whether the vendor total matches the Excel total within +/-0.5%.
- The vendors that were summed into Others.
- The list of country spelling changes.

## 2. TechInsights analysis article to Markdown

The owner pastes the article text to you. Save it as a `.md` file in the same folder as the broker PDFs.

- Filename: `DD-Mon-YYYY_HH-MM-SS-TechInsights-<TITLE>.md`, for example
  `06-Oct-2026_00-00-00-TechInsights-Smartwatch_Q3_Analysis.md`. The date is the article's publication date; use
  `00-00-00` if no time is known. Title words are joined with `_`.
- First line: `# <article title>` (exactly as published). The program uses it as the report title.
- Then paste the paragraphs verbatim. No edits, no summary, no translation, no added headings, no "improved" wording.
  Copy numbers exactly.
- Do not change the PDFs in that folder.

Then run the pipeline exactly as in `docs/handoff/reports-loader-run.md` (stages 1 to 4a):

```powershell
python tools/load_reports.py extract "D:\path\to\reports"    # PDFs and .md/.txt files are both picked up
python tools/load_reports.py status
```

- Triage: `kind` = `firm_analysis`; `relevance` = `high` (smartwatch is the subject).
- Annotate: `topics` includes `스마트워치`. For `firm_analysis`, `keywords_en` MUST include every vendor name and
  every country / region named in the article (for example `Apple, Huawei, China, India`), `keywords_ko` their
  Korean forms, and `key_numbers` quotes every shipment and growth figure verbatim with `[p.1]`.
- Then `triage-report`, wait for the owner, and `load --local`, as in the reports run.

## 3. Load the smartwatch CSV

```powershell
python tools/load_smartwatch.py check smartwatch_2026-10.csv
python tools/load_smartwatch.py load --local smartwatch_2026-10.csv
python tools/load_smartwatch.py load --local smartwatch_2026-10.csv    # second run: all keys already exist
```

`check` validates only and prints a summary table; fix every error in the CSV, never in the program. `--local` uses
the embedded PostgreSQL in `staging/localpg/`; no company system is touched. The owner runs
`load --dsn-env MI_DB_REPORTS_WRITE` later, by hand.

## Report back

- The `check` summary and the status lines of each `load` run.
- The validation report from section 1 (numbers only).
- For the article: the `status` line and the summary line of `load --local`.
- Any `FAIL` or error lines (they contain no secrets).
- Nothing else leaves the PC.
