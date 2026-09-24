# 개발·운영 가이드

## 환경 구성

Python 3.11 가상환경을 만들고 의존성을 설치합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에는 `KAMIS_CERT_KEY`, `KAMIS_CERT_ID`를 설정합니다. 이 파일은 Git에서 제외됩니다. 키가 노출되면 KAMIS에서 재발급한 뒤 `.env`만 교체하고 이전 키를 폐기합니다.

## 실행

```powershell
.\.venv\Scripts\python.exe -m app.cli collect-kamis --start 2026-09-24 --end 2026-09-24
.\.venv\Scripts\python.exe -m app.cli backfill-kamis --years 3
.\.venv\Scripts\python.exe -m app.cli schedule
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000
```

Swagger UI는 <http://127.0.0.1:8000/docs>에서 확인합니다.

## 데이터 구조

- `data/raw/kamis/catalog/`: 날짜별 KAMIS 품목 사전 원본 스냅샷
- `data/normalized/kamis_catalog.csv`: 최신 정규화 품목 사전
- `data/normalized/kamis_prices.csv`: 도매·소매 가격 누적 자료
- `data/runs/collection_runs.csv`: 실행 상태, 건수, 실패 범위와 원인
- `logs/`: 날짜별 애플리케이션 로그

CSV는 임시 파일에 완전히 쓴 다음 원자적으로 교체합니다. 같은 관측값은 복제하지 않고 갱신합니다.

## 로그로 장애 조사하기

주요 이벤트는 `collection.started/completed/failed`, `collection.query.failed`, `kamis.request.started/succeeded/no_data/failed`, `csv.write.succeeded/failed`, `http.request.completed/failed`, `scheduler.collection.*`입니다.

1. `collection.completed`의 `run_id`, `status`, `error_count`를 찾습니다.
2. 같은 `run_id`의 `collection.query.failed`에서 품목·등급·기간과 `error_type`을 확인합니다.
3. `kamis.request.failed`에서 API 동작과 재시도 종료 원인을 확인합니다.
4. 저장 문제면 `csv.write.failed`의 경로와 예외를 확인합니다.
5. 웹 요청 문제면 응답의 `X-Correlation-ID`로 `http.request.*`를 검색합니다.

인증 키와 요청자 ID, 인증 헤더는 마스킹되며 전체 쿼리 문자열을 기록하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```
