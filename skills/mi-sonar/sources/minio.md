---
name: minio
kind: s3
env: MI_MINIO
summary: smartphone_market_data 원본 파일 저장소 (MinIO)
---
## 사용법

- 목록: `query.py ls minio <접두어>` (최대 200개. 접두어로 좁힌다)
- 다운로드: `query.py fetch minio <객체키> [--out 경로]` (기본: 현재 폴더에 파일명 그대로)
- 객체키는 `smartphone_market_data` 의 원본 키 컬럼 값과 동일하다.

## 환경변수 형식

`MI_MINIO = http(s)://ACCESS:SECRET@host:port/bucket` (SECRET에 특수문자가 있으면 URL 인코딩)
