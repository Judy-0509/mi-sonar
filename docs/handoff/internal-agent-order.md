# Work order: finish mi-sonar inside the company network

You are an agent running on a company PC with access to the internal GitHub,
the PostgreSQL DBaaS and MinIO. Everything that does not need the network is
already built and tested. Do the following in order; stop and report if any step fails.

## 0. Preconditions
- `python --version` >= 3.10, `git --version`, `pip install -r requirements-dev.txt`
- `python -m pytest scripts -q` -> all tests pass before you change anything.

## 0b. DB capability check (do this before section 1)
- Follow `docs/handoff/db-capability-check.md`: run `python tools/db_check.py --table smartphone_market_data --out db_check_report.md`
  with the owner account in `MI_DB_CHECK` (current shell only). It changes nothing; everything is rolled back.
- Attach the whole `db_check_report.md` to your report, plus the DBaaS team's answers to every question in its `## 10. 판정`.

## 1. Fill placeholders (grep for `__` to find them all)
| File | Placeholder | Replace with |
|---|---|---|
| `README.md` | `__REPO_URL__` | internal GitHub repo URL, no trailing `.git` |
| `install.ps1` | `__FILL_DSN__` | `postgresql://USER:PASSWORD@HOST:5432/DBNAME` (shared read-only account; special characters in PASSWORD must be URL-encoded, e.g. `@` -> `%40`) |
| `install.ps1` | `__FILL_MINIO__` | `http(s)://ACCESS:SECRET@HOST:PORT/BUCKET` (URL-encode special chars in SECRET) |
| `sources/smartphone.md` | `__KEY_COLUMN__` | the column holding the MinIO object key (see step 3) |
| `sources/smartphone.md` | `__FIRM_COLUMN__` | the column holding the research-firm name |

The repo MUST be private to the team: the installer embeds shared credentials.

## 2. Verify the shared account really is read-only
Set both env vars in the current shell, then run these 4 read-only checks with
`python scripts/query.py sql smartphone "<SQL>"`. If any check fails, stop and report; do not distribute.

1. `SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = current_user`
   -> all four are false.
2. `SELECT count(*) FROM information_schema.table_privileges WHERE grantee = current_user AND privilege_type <> 'SELECT'`
   -> 0.
3. `SELECT extname FROM pg_extension WHERE extname IN ('dblink','postgres_fdw')`
   -> 0 rows.
4. `SELECT table_schema, table_name FROM information_schema.table_privileges WHERE grantee = current_user AND privilege_type = 'SELECT'`
   -> list every row in your report; the owner confirms every listed table may be exposed to the team.
5. `SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user)`
   -> stop if the result includes pg_write_all_data, pg_signal_backend, pg_read_server_files or pg_execute_server_program; list every other role in the report for the owner to review (inherited privileges are not visible to checks 2 and 4).

## 3. Fill `sources/smartphone.md`
- Run `python scripts/query.py schema smartphone`.
- Copy the column/type table into the `## 컬럼 의미` section and write a one-line meaning
  for each column (ask the owner for any you cannot infer from the sample rows).
- Replace `__KEY_COLUMN__` with the real column that holds the MinIO object key.
- Adjust the example queries so column names match the real schema; run each one once.
- In the column table, mark which columns hold the period granularity (weekly/monthly), region, model and period; the mixing rules in SKILL.md step 4 depend on them.

## 3b. Research-firm check
- Run `python scripts/query.py sql smartphone "SELECT <firm column>, COUNT(*) FROM smartphone_market_data GROUP BY 1 ORDER BY 2 DESC"`.
- Fill the firm table in `sources/smartphone.md` (one row per distinct value, with a one-line coverage note).
- If the same firm appears under different spellings, or periods/units differ between firms, report it: the owner
  normalizes keys at load time; do not patch it in the skill.

## 4. Integration check (all must succeed)
```
python scripts/query.py sources            # both 설정됨
python scripts/query.py schema smartphone
python scripts/query.py sql smartphone "SELECT COUNT(*) FROM smartphone_market_data"
python scripts/query.py sql smartphone "SELECT <firm column>, COUNT(*) FROM smartphone_market_data GROUP BY 1"
python scripts/query.py ls minio ""
python scripts/query.py fetch minio "<one key from step 3>" --out %TEMP%\mi-sonar-fetch-test.bin
python -m pytest scripts -q
```

## 5. Publish
- Commit as `chore: fill in-company configuration` and push to the private repo (`main`).
- On a clean colleague PC (or a fresh Windows user profile): paste the README one-liner into PowerShell
  (`git clone <repo URL> "$HOME\.claude\skills\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"`),
  open a new terminal, run `python %USERPROFILE%\.claude\skills\mi-sonar\scripts\query.py sources`
  -> both 설정됨. Start OpenCode in any folder and confirm `mi-sonar` appears exactly once in its skills list
  (OpenCode reads `~/.claude/skills` natively; there is no separate registration).
- In that terminal ask Claude Code: "2026년 2분기 제조사별 점유율 보여줘". It must call
  `query.py sql` and answer with a table plus the SQL it used. Claude asks which research firm to use first (SKILL.md step 3); choose one, then expect a table plus the SQL, naming the firm.
- Second prompt: ask "일본 월별 아이폰 판매량 보여줘" (assuming Japan is missing at monthly level for the chosen firm); Claude must show a mixing plan and wait for confirmation before computing. If Japan exists directly, note that in the report instead.

## 6. Report back
Repo URL, commit hash, which step-4 commands passed, any column whose meaning is still unknown.
