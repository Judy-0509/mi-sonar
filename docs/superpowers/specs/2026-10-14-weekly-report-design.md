# 주간보고 설계 (1차)

작성일: 2026-10-14
상태: **초안, 루틴 확정**

이번 주에 새로 들어온 자료로 주간보고 주제를 제안하고, 사용자가 고른 주제로 초안을 쓰는 흐름입니다. 레포트 표와 주석(`thesis`, `scope`) 규칙은 [증권사 레포트 저장 설계](2026-10-13-reports-storage-design.md)를 따릅니다.

## 1. 목적

- 주간보고 주제 2~5개 제안 → 사용자 선택 → 초안 작성.
- 관문은 두 곳이며 둘 다 사람입니다: (1) 주제 선택, (2) 초안 검토. 에이전트는 관문을 건너뛰지 않습니다.

## 2. 입력 (이번 주 새로 온 것)

1. **증권사 레포트**: `loaded_at` 이 지난 점검 이후인 행의 `thesis`, `scope`, `published_on` 목록.
   ```sql
   SELECT id, published_on, firm, thesis, scope FROM sales_team.nasdaq_report_doc WHERE loaded_at >= TIMESTAMP '<지난 점검 시각>' ORDER BY published_on DESC
   ```
2. **스마트폰 조사기관 데이터의 변화**: `smartphone_market_data` 에 `published_month` / `loaded_at` 같은 컬럼이 생기기 전까지는 로컬 스냅샷 비교로 감지합니다.
   - `tools/weekly_snapshot.py` (미구현) 가 매주 `staging/weekly/<date>.json` 에 조사기관(firm)별로 최신 period, 행 수, 업체별 최신 분기 합계를 저장합니다.
   - 직전 스냅샷과의 차이(diff)를 표로 출력합니다. `staging/` 이므로 PC 밖으로 나가지 않습니다.
3. **사용자가 붙여넣은 메모** (선택).

## 3. 주제 제안 규칙 (초안)

- 우선순위: 새 레포트 주장 중 2건 이상이 가리키는 주제 > 조사기관 데이터가 바뀐 항목 > 단일 레포트 주장.
- 지난 4주 주간보고 주제와 겹치면 제외합니다 (5절 `weekly_report` 의 `topic` 으로 확인).
- 후보 하나 = 제목 1줄 + 근거(레포트 `id`·`[p.N]`, 데이터 항목) + 왜 지금인지 1줄.
- 최소 2개, 최대 5개.

## 4. 작성 규칙

- `design/weekly-rules.md`: 주제 선정 기준. 2026 주간보고에서 OpenCode 가 추출하고 사용자가 고칩니다.
- `design/weekly-tone.md`: 말투 샘플 (사내 비공개).
- 둘 다 아직 없습니다. 위치는 `skills/mi-sonar/design/` (`slide-rules.md`, `slide-tone.md` 와 같은 자리)입니다.

## 5. 기록

로컬 DB(`--local`, 내 PC의 내장 PostgreSQL)에 테이블 `weekly_report` 를 둡니다. DBaaS 팀 요청은 형식이 안정된 뒤에 합니다.

| 칸 | 의미 |
|---|---|
| `id` | 행 번호 |
| `week_start` | 주 시작일 |
| `title` | 보고 제목 |
| `topic` | 주제 (지난 4주 중복 확인용) |
| `stance` | 보고의 입장·관점 (값 목록은 `weekly-rules.md` 에서 정함) |
| `body` | 보고 본문 |
| `report_ids` | 근거로 쓴 레포트 `id` 목록 |
| `data_notes` | 근거로 쓴 조사기관 데이터 항목 |
| `proposed_topics` | 그 주에 제안했던 후보 전체 (고르지 않은 것 포함) |
| `created_at` | 기록 시각 |

2026 과거 주간보고도 같은 표에 적재합니다. 원본 파일 형식은 확인이 필요합니다 (7절).

## 6. 내일 할 수 있는 것 / 못 하는 것

| 가능 | 불가 |
|---|---|
| 레포트 `thesis` 목록 뽑기 (2절 1번 쿼리) | 조사기관 데이터 변화 감지 (스냅샷 도구 미구현, 컬럼 없음) |
| 과거 주간보고 → 주제·범위 표 추출 (OpenCode) | |
| `weekly-rules.md` 규칙 초안 | |

## 7. 열린 질문

1. 주간보고 원본 형식은 무엇인가 (PPT, Word, 메일 본문 등)?
2. "지난 점검" 기준일을 어디에 저장하나 (`staging/` 안의 파일 vs 로컬 DB 표)?
3. 오토 등 다른 응용처로 언제 포팅하나?

## 주간 루틴 (사용자 확정 2026-10-14)

| 언제 | 사용자가 말하면 | 에이전트 | 사람 |
|---|---|---|---|
| 월 오전 | "나스닥 레포트 업데이트 해줘" + zip 폴더 경로 | `extract <zip>` → triage → `triage.md` → annotate → `status` | triage 검토, `load --dsn-env MI_DB_REPORTS_WRITE` 직접 1회 |
| 월 오전 | "이번 주 주간보고 주제 찾아줘" | 지난 실행 이후 새 레포트 `thesis/scope` 목록 + 스냅샷 diff + 지난 4주 주제 제외 → 후보 2~5개(근거·왜 지금) | 후보 선택 |
| 화~수 | "주간보고 작성해줘 (N번)" | `design/weekly-rules.md`·`design/weekly-tone.md` 대로 초안 **최소 2개 버전**(예: 데이터 중심 / 레포트 주장 중심) md 저장 → 로컬 `weekly_report` 에 기록 | 버전 선택·수정 |

- 자동 실행 없음(사람 관문 때문). "지난 실행" 기준일 = 마지막 스냅샷 파일. 상태는 `staging/weekly/` (PC 안).
- 만들 것:
  - `skills/mi-sonar/scripts/snapshot.py` (읽기 전용)
  - `tools/load_weekly.py` (2026 주간보고 md → 로컬 `weekly_report`; 주당 1파일, 첫 줄 `# 제목`, 파일명에 주차 날짜)
  - `design/weekly-rules.md` (OpenCode 가 2026 주간보고에서 추출 → 사용자 수정)
  - `design/weekly-tone.md` (사내 비공개)
  - SKILL 단계 3개 (위 표의 문구가 트리거)
- 순서: 컬럼명 확인(day1 STEP 1) → snapshot → load_weekly → SKILL 단계.
