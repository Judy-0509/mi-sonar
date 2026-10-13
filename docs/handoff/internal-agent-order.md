# Work order: finish mi-sonar inside the company network

You are an agent running on a company PC with access to the internal GitHub,
the PostgreSQL DBaaS and MinIO. Everything that does not need the network is
already built and tested. Do the following in order; stop and report if any step fails.

## 0. Preconditions
- `python --version` >= 3.10, `git --version`, `pip install -r requirements-dev.txt`
- `python -m pytest scripts -q` -> all tests pass before you change anything.

## 1. Fill placeholders (grep for `__` to find them all)
| File | Placeholder | Replace with |
|---|---|---|
| `install.ps1`, `README.md` | `__REPO_URL__` | internal GitHub repo URL, no trailing `.git` |
| `install.ps1` | `__FILL_DSN__` | `postgresql://USER:PASSWORD@HOST:5432/DBNAME` (shared read-only account) |
| `install.ps1` | `__FILL_MINIO__` | `http(s)://ACCESS:SECRET@HOST:PORT/BUCKET` (URL-encode special chars in SECRET) |

The repo MUST be private to the team: the installer embeds shared credentials.

## 2. Verify the shared account really is read-only
Set both env vars in the current shell, then run:
`python scripts/query.py sql smartphone "SELECT current_user, has_table_privilege('smartphone_market_data','INSERT') AS can_insert"`
Expected: `can_insert = false`. If true, stop and report; do not distribute.

## 3. Fill `sources/smartphone.md`
- Run `python scripts/query.py schema smartphone`.
- Copy the column/type table into the `## 컬럼 의미` section and write a one-line meaning
  for each column (ask the owner for any you cannot infer from the sample rows).
- Replace `__KEY_COLUMN__` with the real column that holds the MinIO object key.
- Adjust the example queries so column names match the real schema; run each one once.

## 4. Integration check (all must succeed)
```
python scripts/query.py sources            # both 설정됨
python scripts/query.py schema smartphone
python scripts/query.py sql smartphone "SELECT COUNT(*) FROM smartphone_market_data"
python scripts/query.py ls minio ""
python scripts/query.py fetch minio "<one key from step 3>" --out %TEMP%\mi-sonar-fetch-test.bin
python -m pytest scripts -q
```

## 5. Publish
- Commit as `chore: fill in-company configuration` and push to the private repo (`main`).
- On a clean colleague PC (or a fresh Windows user profile): paste the README one-liner,
  open a new terminal, run `python %USERPROFILE%\.claude\skills\mi-sonar\scripts\query.py sources`
  -> both 설정됨. Confirm `%USERPROFILE%\.config\opencode\skill\mi-sonar\SKILL.md` exists.
- In that terminal ask Claude Code: "2026년 2분기 제조사별 점유율 보여줘". It must call
  `query.py sql` and answer with a table plus the SQL it used.

## 6. Report back
Repo URL, commit hash, which step-4 commands passed, any column whose meaning is still unknown.
