---
name: smartphone
kind: postgres
env: MI_DB_SMARTPHONE
tables: [smartphone_market_data]
summary: 스마트폰 시장 데이터 (모델/출하량/점유율 등)
---
## 컬럼 의미
(사내 에이전트가 `query.py schema smartphone` 출력으로 채움)

## 자주 쓰는 쿼리
(Task 6에서 채움)

## 주의사항
- 원본 파일 키 컬럼: `__KEY_COLUMN__` → `query.py fetch minio <키>`
