# 개발·운영 가이드

## 시작 시 과거 시장 데이터 보충

`app/main.py`의 앱 시작 단계에서 오늘의 통합 수집을 처리한 뒤, 같은 백그라운드 작업에서 KAMIS CSV의 실제 최소·최대 관측일을 확인합니다. 오늘 수집이 이미 성공했거나 실패한 경우에도 과거 시장 데이터 확인은 수행합니다. KAMIS 데이터가 없으면 `market.history.skipped`로 기록합니다.

지수별 저장 날짜를 비교해 빠진 거래일의 최초~최종 날짜 구간을 조회하고, 기존 CSV에 upsert합니다. 한국 지수는 XKRX, 미국 지수는 XNYS 휴장 달력을 적용하며 이미 채워진 지수는 재조회하지 않습니다. 환율·선물은 평일 누락분을 확인하므로 공급자 휴장이나 미제공 날짜가 계속 비어 있으면 다음 시작 때 재확인할 수 있습니다. 실패·누락은 `market.history.incomplete` 또는 `market.history.series.failed`로 남기고 다른 지수의 수집은 계속합니다. 실행 결과는 `collection_runs.csv`의 `market_history` 소스로 기록하며, 데이터가 추가되면 분석 결과도 갱신합니다.

## 국내 증시 휴장 로그

시장 수집은 `holidays`의 한국거래소(`XKRX`) 달력과 주말 여부를 확인합니다. 조회 기간 전체가 휴장일이면 KOSPI·KOSDAQ 조회를 건너뛰고 `market.collection.closed` INFO 로그에 날짜와 한국어 휴일명을 기록합니다. 예: `observed_date=2026-09-25 holiday_name=추석`, 메시지: `국내 증시 휴장일로 가격 데이터가 없는 정상 상황입니다. 조회를 건너뜁니다.` 해외 지수·환율·선물은 계속 조회하며, 기간에 국내 거래일이 포함되면 국내 지수도 조회합니다. 임시 휴장일 등 달력 변경 사항은 `holidays` 의존성 업데이트로 반영해야 합니다.

## 환경 구성

Python 3.11 가상환경을 만들고 의존성을 설치합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에는 `KAMIS_CERT_KEY`, `KAMIS_CERT_ID`를 설정합니다. 이 파일은 Git에서 제외됩니다. 키가 노출되면 KAMIS에서 재발급한 뒤 `.env`만 교체하고 이전 키를 폐기합니다.

KAMIS 품목·가격은 전체 수집하며, 네이버·쿠팡은 `ONLINE_TARGETS`에 설정된 대표 KAMIS 품목 10개만 검색합니다. 기본값은 쌀, 감자, 배추, 무, 양파, 깐마늘, 토마토, 사과, 배, 고등어이며 정확한 `item_code:kind_code` 쌍은 `.env.example`에 있습니다. 카탈로그에 중복 행이 있어도 품목·플랫폼당 한 번만 요청하므로 하루 최대 20회이고, `SHOPPING_REQUEST_INTERVAL_SECONDS`(기본 5초) 간격으로 순차 실행합니다.

자동화 전용 Chromium 프로필은 기본적으로 `data/browser-profile`에 저장되며 `SHOPPING_USER_DATA_DIR`로 변경할 수 있습니다. 사람이 사용 중인 기본 브라우저 프로필을 동시에 열지 마십시오. 화면이 필요한 최초 로그인 준비 단계에서는 `SHOPPING_HEADLESS=false`, 일일 실행에서는 `true`를 사용합니다. 접근 제한·CAPTCHA·HTTP 403/418/429는 우회하지 않습니다. 감지 즉시 해당 플랫폼의 남은 대표 품목 검색을 중단하고 `online.collection.source.blocked` 이벤트에 상태 코드와 품목을 기록하며, 다른 플랫폼과 KAMIS·시장 데이터 수집은 계속합니다. 검색 결과가 정상적으로 0건인 경우에만 그 날짜를 온라인 비교 불가로 처리합니다.

## 실행

```powershell
.\.venv\Scripts\python.exe -m app.cli collect-kamis --start 2026-09-24 --end 2026-09-24
.\.venv\Scripts\python.exe -m app.cli backfill-kamis --years 3
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m app.cli collect-all --date 2026-09-24
.\.venv\Scripts\python.exe -m app.cli schedule
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000
```

`serve` 또는 `app/main.py`로 서버를 시작하면 서울 기준 오늘의 `daily_pipeline` 성공 이력을 확인합니다. 성공 이력이 없거나 이전 실행이 실패·부분 실패라면 통합 수집을 백그라운드에서 시작하며, 이미 성공했다면 중복 수집하지 않습니다. 수집 중에도 웹과 API는 바로 사용할 수 있습니다.

통합 수집은 날짜별 `kamis`, `online`, `market` 성공 체크포인트를 각각 확인합니다. 체크포인트가 없더라도 온라인 요약 CSV가 대표 품목·플랫폼별로 완전하거나 시장 CSV에 해당 관측일 자료가 있으면 체크포인트를 복구합니다. 이전 프로세스가 중간에 종료되었더라도 같은 날짜에 완료된 소스는 `daily_pipeline.source.skipped`로 기록하고 건너뛰며, 실패·부분 완료·미실행 소스만 다시 수집합니다. 온라인·시장 소스는 저장까지 끝난 뒤에만 성공 체크포인트를 기록합니다. 재실행되는 CSV 저장은 키 기반 upsert이므로 같은 날짜의 관측값을 중복 생성하지 않습니다.

Swagger UI는 <http://127.0.0.1:8000/docs>에서 확인합니다.

## 데이터 구조

- `data/raw/kamis/catalog/`: 날짜별 KAMIS 품목 사전 원본 스냅샷
- `data/normalized/kamis_catalog.csv`: 최신 정규화 품목 사전
- `data/normalized/kamis_prices.csv`: 도매·소매 가격 누적 자료
- `data/normalized/online_offers.csv`: 네이버·쿠팡 검색 후보와 정규화 가격
- `data/normalized/online_offer_decisions.csv`: 평균 포함 여부와 제외 사유
- `data/normalized/online_price_summaries.csv`: 플랫폼별·통합 일일 평균
- `data/normalized/market_observations.csv`: 지수·환율·농산물 선물 종가
- `data/analytics/`: 기준 100, 수익률, 상관·시차·이동 상관, 스프레드·변동성
- `data/runs/collection_runs.csv`: 실행 상태, 건수, 실패 범위와 원인
- `log/logs/`: 날짜별 애플리케이션 로그

CSV는 임시 파일에 완전히 쓴 다음 원자적으로 교체합니다. 같은 관측값은 복제하지 않고 갱신합니다.

## 로그로 장애 조사하기

주요 이벤트는 `startup.collection.scheduled/skipped/completed/failed`, `daily_pipeline.started/completed/source.failed`, `collection.started/completed/failed`, `collection.query.failed`, `kamis.request.started/succeeded/no_data/failed`, `csv.write.succeeded/failed`, `http.request.completed/failed`, `scheduler.collection.*`입니다.

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
