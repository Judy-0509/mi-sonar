# 1일차 실행 지시 (사내 에이전트용)

이 파일을 읽은 에이전트는 STEP 0 부터 순서대로 진행하고, 각 STEP 끝에 "보고" 항목을 출력한 뒤 다음 STEP 으로 넘어간다. "멈춤" 이라고 적힌 곳에서는 사용자의 답을 기다린다.

## 공통 규칙
- 이 PC 밖으로 나가는 것은 없다. 엑셀 내용, PDF 본문, CSV 행, `staging/` 파일을 채팅·티켓·메일·git 에 붙이지 않는다. 숫자 요약(건수, 분기 목록)만 보고한다.
- 회사 DB 에 쓰지 않는다. `--dsn-env`, `MI_DB_REPORTS_WRITE`, `MI_MINIO_WRITE` 는 사용자만 손으로 다룬다. 에이전트는 설정·출력·질문하지 않는다.
- 비밀번호·DSN 이 보이면 출력에서 지운다 (프로그램이 이미 가리지만 확인한다).
- 엑셀·PDF 원본을 수정·이동·삭제하지 않는다.

## 문제가 생겼을 때 (객관식 보고)
문제·불확실·선택이 필요한 모든 상황은 아래 형식으로 묻고 멈춘다. 주관식으로 묻지 않는다.

```
문제: <한 줄>
근거: <오류 메시지 1~2줄 또는 상황>
선택지:
A. <조치> → <결과/영향>  (권장)
B. <조치> → <결과/영향>
C. <조치> → <결과/영향>
D. 기타 (직접 입력)
```
- 선택지는 최소 3개, 서로 다른 실제 조치여야 한다 (예: 건너뛰기 / 수정 후 재시도 / 중단하고 담당자 확인). 하나에 "(권장)" 을 붙인다.
- 사용자는 글자 하나(A/B/C)로 답한다. D 를 고른 경우에만 자유 입력을 받는다.
- 답을 받기 전에는 아무것도 바꾸지 않는다. 같은 문제를 두 번 묻지 않도록 답을 기록해 둔다.

## STEP 0. 준비
목적: 도구가 이 PC 에서 도는지, 테이블이 벌써 있는지 확인.
```powershell
git -C <레포 경로> pull --ff-only
python "<레포 경로>\skills\mi-sonar\scripts\query.py" sources
python "<레포 경로>\skills\mi-sonar\scripts\query.py" schema reports
python "<레포 경로>\skills\mi-sonar\scripts\query.py" schema smartwatch
```
- `sources` 출력에서 환경변수 설정 여부와 소스 목록만 확인. 접속 실패면 객관식 보고.
- 보고: 현재 커밋 해시, 소스별 OK/FAIL, 레포트 표 / 스마트워치 표: 있음·없음 (relation does not exist 면 없음). 있으면 컬럼 `thesis`, `scope` (레포트) 와 `dataset`, `revenue_musd`, `asp_usd` (스마트워치) 가 있는지도 보고.

## STEP 1. 스마트폰 테이블 컬럼 설명 채우기
목적: 에이전트가 스마트폰 표의 컬럼을 이해해야 동료 질문에 맞는 컬럼을 고를 수 있다. price band·시점 컬럼 유무는 TAM·주간보고 설계의 전제.
```powershell
python "<레포 경로>\skills\mi-sonar\scripts\query.py" schema smartphone
```
- 출력의 컬럼명·타입·comment 로 `skills/mi-sonar/sources/smartphone.md` 의 컬럼 표를 채운다 (값·샘플 행은 적지 않는다).
- comment 가 없어 의미가 불명확한 컬럼은 한 번에 모아 객관식으로 묻는다: 컬럼마다 추정 의미 A/B/C + D 기타. (멈춤)
- 보고: 채운 컬럼 수, 질문한 컬럼 수, `smartphone_market_data` 에 (a) 적재 시각 또는 발행월 컬럼과 (b) 가격대 컬럼이 있는지 (있으면 컬럼명, 없으면 "없음"). 사용자가 OK 하면 커밋 (`sources/smartphone: fill column table`).

## STEP 2. TechInsights 기사 받기 (사용자가 붙여넣는 경우만)
목적: 기사도 레포트와 같은 표에 넣어 함께 검색되게 한다.
- 사용자가 기사 본문을 붙여넣고 "적재해줘" 라고 하면 `docs/handoff/smartwatch-data.md` 2절대로 `staging/inbox/` 에 `.md` 로 저장한다. 제목·발행일이 없으면 객관식(예: 본문 첫 문장을 제목으로 / 오늘 날짜 / 직접 입력)으로 묻는다.
- 붙여넣은 기사가 없으면 이 STEP 은 건너뛴다고 보고만 한다.
- 보고: 저장한 파일명 목록.

## STEP 3. 레포트 추출
목적: PDF 를 글자로 꺼내 둔다 (디스클로저 제거, 쪽 번호 표시).
```powershell
python tools\load_reports.py extract "<PDF 폴더>" staging\inbox
python tools\load_reports.py status
```
- PDF 폴더는 사용자가 알려준 경로. 모르면 객관식으로 묻는다 (최근 쓴 경로 후보가 있으면 선택지에 넣는다).
- 보고: 총 파일 수, 추출 성공/실패 수, 실패 파일명 (본문 없이), 제목·증권사를 파일명에서 못 읽은 건수.

## STEP 4. 분류 (triage) — 멈춤 있음
목적: 어떤 레포트를 지식으로 삼을지 사람이 정한다. 쓸모없는 것(링크 모음 등)을 걸러 검색 품질을 지킨다.
- `docs/handoff/reports-loader-run.md` 의 triage 규칙대로 모든 레포트에 `triage.json` 을 쓴다 (kind + 이유 한 줄, 관련도는 프로그램이 주제 사전으로 자동 산출).
- `python tools\load_reports.py triage-report` 로 `staging/triage.md` 를 만든다.
- 보고: 적재 대상 수 / 제외 수, kind 별 건수, 관련도(`status` 줄의 `rel=`) 별 건수, 관련도 low 레포트 수와 제목, 자동 티커·주제가 비어 있는 레포트 수와 그 제목 (`status` 줄의 `tickers=-` 또는 `topics=-`). 제외 목록은 "제목 + 이유" 만 (본문 인용 금지).
- 멈춤: "triage.md 를 열어 확인 후 A. 그대로 진행 / B. 바꿀 항목 알려줌(제목 + load true/false) / C. 전부 다시 분류 / D. 기타" 로 묻는다.
- 멈춤 (자동 티커·주제가 빈 레포트가 있을 때): 레포트별로 "A. 사전에 추가 후 재실행(권장): 에이전트가 넣을 별칭·키워드 후보를 보여 주고 사용자가 `tools/dict/tickers.csv`·`topics.csv` 에 넣은 뒤 `status` 다시 실행 (재추출 불필요) / B. 그대로 진행 / C. 제외 / D. 기타" 로 묻는다.

## STEP 5. 요약·주석 (annotate) + 로컬 적재
목적: 검색 가능한 형태(주장 1줄, 근거, 키워드)로 만들고 PC 안 DB 에 넣어 전체 흐름을 리허설한다.
- 적재 대상만 `annotate.json` 작성. 쓰는 항목은 thesis(주장 한 문장), summary(한국어 3~6줄(2번째 줄부터 `[p.N]`) + 영어 1줄), keywords(한/영 각 ≤10), key_numbers(`[p.N]` 과 함께) 뿐이다 (title·ticker·analyst 는 필요할 때만). scope·topics 는 쓰지 않는다: 프로그램이 사전으로 자동 집계한다. TechInsights 기사는 `firm_analysis` 규칙(업체·국가명 전부 keywords_en 에). 규칙은 [reports-loader-run.md 3절](reports-loader-run.md#3-annotate-decisionload-only).
- 한 레포트의 자동 티커·주제를 확인할 때: `python tools\load_reports.py paragraphs <id>` (문단별 태그와 집계, id 앞 몇 글자만 써도 됨).
```powershell
python tools\load_reports.py status
python tools\load_reports.py load --local
python tools\load_reports.py status
```
- 보고: annotate 완료 수, `load --local` 결과 줄(적재/건너뜀/실패), 실패 id 와 오류 한 줄.
- 4b(회사 DB 적재)는 하지 않는다. 아래 5b 에서 묻는다.

## STEP 5b. 회사 DB 적재 (레포트 표가 있을 때만)
목적: 로컬 리허설이 통과한 것을 실제 표에 넣는다.
- 에이전트는 멈추고 사용자에게 객관식으로 묻는다 — A. 사용자가 지금 PowerShell 에서 `docs/handoff/reports-loader-run.md` 4b 대로 직접 적재 (권장, 표·권한 있을 때) / B. 오늘은 로컬까지만 / C. 표는 있으나 권한 미확인, 담당자 확인 후 / D. 기타. (멈춤)
- 사용자가 A 를 끝냈다고 하면 에이전트는 읽기 계정으로 아래를 실행해 결과 숫자만 보고한다.
```powershell
python "<레포 경로>\skills\mi-sonar\scripts\query.py" sql reports "SELECT COUNT(*), MAX(loaded_at) FROM sales_team.nasdaq_report_doc"
```
- 에이전트는 `--dsn-env` 를 실행하지 않고, DSN 을 묻거나 출력하지 않는다.

## STEP 6. 스마트워치 엑셀 → CSV → 로컬 적재
목적: 실적 vs 우리 TAM 비교의 숫자 준비. 국가 표기·단위 불일치를 여기서 잡는다.
- 엑셀 파일 경로는 사용자가 알려준다 (사내 ear 스킬로 받은 파일). 다른 엑셀을 찾거나 열지 않는다.
- `docs/handoff/smartwatch-data.md` 1절 규칙대로 `smartwatch_<YYYY-MM>.csv` 작성. 발행월·단위(천 대/백만 대)·국가 표기 불일치·중복 키는 객관식으로 묻는다 (멈춤).
```powershell
python tools\load_smartwatch.py check smartwatch_<YYYY-MM>.csv
python tools\load_smartwatch.py load --local smartwatch_<YYYY-MM>.csv
python tools\load_smartwatch.py latest --local
```
- 보고: `check` 요약표, dataset 별 행 수, 분기·연도 목록, 국가 수, 국가별 합계가 엑셀 합계와 ±0.5% 내인지, Others 에 합산한 업체, 국가 표기 변경 목록, `load --local` 결과 줄, `latest` 의 행 수. 미매핑 국가(`sources/smartwatch.md` 의 지역표에 없는 국가) 목록.

## STEP 6b. 회사 DB 적재 (스마트워치 표가 있을 때만)
목적: 로컬 리허설이 통과한 것을 실제 표에 넣는다.
- 에이전트는 멈추고 사용자에게 객관식으로 묻는다 — A. 사용자가 지금 PowerShell 에서 `docs/handoff/smartwatch-data.md` 3절 대로 직접 적재 (권장, 표·권한 있을 때) / B. 오늘은 로컬까지만 / C. 표는 있으나 권한 미확인, 담당자 확인 후 / D. 기타. (멈춤)
- 사용자가 A 를 끝냈다고 하면 에이전트는 읽기 계정으로 아래를 실행해 결과 숫자만 보고한다.
```powershell
python "<레포 경로>\skills\mi-sonar\scripts\query.py" sql smartwatch "SELECT dataset, COUNT(*), MAX(published_month) FROM sales_team.smartwatch_market_data GROUP BY dataset"
```
- 에이전트는 `--dsn-env` 를 실행하지 않고, DSN 을 묻거나 출력하지 않는다.

## STEP 7. 최종 보고
목적: 설계와 현실의 차이를 보고해 다음 작업을 정하게 한다.
한 화면에: STEP 별 상태(완료/건너뜀/멈춤), 커밋 해시, 남은 객관식 질문, 표 존재 여부와 회사 DB 적재 여부(5b/6b), 사용자가 직접 해야 할 일(4b 적재, 테이블·권한 확인). 그 외 아무것도 보내지 않는다.
