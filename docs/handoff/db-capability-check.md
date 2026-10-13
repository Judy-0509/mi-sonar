# DB capability check (run once, paste the report back)

## Purpose

Before any new table is designed (증권사 레포트 청크, 조사기관 내러티브), the owner needs to know what the
DBaaS account can actually do: create schemas or only tables, use temp tables, which search extensions exist,
and what the existing `smartphone_market_data` table looks like. `tools/db_check.py` answers all of that in one
report. It runs everything inside one transaction and rolls it back at the end, so nothing in the database changes.

## Which DSN

- Ask the DBaaS team or the owner for the **owner account** of the database (the account used to load data).
- Set it as `MI_DB_CHECK` for the current PowerShell window only. Never put it in `install.ps1`, a file, or a commit:

  ```powershell
  $env:MI_DB_CHECK = "postgresql://USER:PASSWORD@HOST:5432/DBNAME"   # URL-encode special chars, e.g. @ -> %40
  ```

- If only the shared read-only account exists, skip `MI_DB_CHECK`; the tool falls back to `MI_DB_SMARTPHONE`.
  The report's first line (`접속 환경변수: ...`) shows which one was used. Say so in your reply.
- The tool never prints the DSN or the password. Connection errors are masked.

## Run

From the repo root:

```powershell
pip install -r requirements.txt
python tools/db_check.py --table smartphone_market_data --out db_check_report.md
Remove-Item Env:MI_DB_CHECK   # when done
```

Exit codes: `0` report written, `1` connection or runtime error (message is masked), `2` env var missing or
`@` not URL-encoded in the password. A failing step inside the report is written as `실패: ...` or `오류: ...`
and the run continues; that is expected and is exactly what the owner needs to see.

## Report back

1. Paste the whole `db_check_report.md` into your reply (it contains no secrets).
2. For every `아니오` or `DBaaS 팀 요청 필요` line in `## 10. 판정`, send the questions listed under
   `DBaaS 팀에 물어볼 것` to the DBaaS team and record their answers in the reply.
3. If `## 8. 한국어 검색 테스트` shows a similarity of `0.000`, the database locale makes pg_trgm ignore Hangul.
   Report it: the GIN index will not speed up Korean searches even when the plan says `Bitmap`.

## Report sections

`## 1. 서버`, `## 2. 역할`, `## 3. 데이터베이스 권한`, `## 4. 스키마 권한`, `## 5. 보이는 테이블`,
`## 6. 생성 테스트 (모두 롤백됨)`, `## 7. 확장`, `## 8. 한국어 검색 테스트`, `## 9. 대상 테이블 프로필`, `## 10. 판정`.

## Decision table (owner fills from §10)

| 결과 | 다음 설계 |
|---|---|
| 스키마 분리 가능 | reports 스키마 + firm_narrative 테이블을 우리가 직접 생성 |
| 테이블 추가만 가능 | 같은 스키마에 reports_report / reports_chunk / firm_narrative 로 접두어 분리 |
| 둘 다 아니오 | DBaaS 팀에 테이블 3개 생성 요청 (DDL은 다음 단계에서 제공) |
| pg_trgm 가능 | 청크 본문에 GIN 인덱스, ILIKE 검색 |
| pg_trgm 불가 | ILIKE 순차검색으로 시작 (수만 청크까지 충분), 느려지면 재요청 |
| pgvector 가능 | 2단계에서 의미 검색 추가 검토 |
