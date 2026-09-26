# KAMIS 가격 비교·상관관계 대시보드

## 쿠팡 Codex agent 수집

쿠팡은 저장소 skill과 Codex CLI를 통해, 로그인된 Windows 사용자의 일반 Chrome
창을 UI Automation으로 조작해 수집합니다. 처음 clone한 뒤 Codex CLI 인증을
완료하세요.

```powershell
codex login
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app\main.py
```

서버는 당일 플랫폼·품목별 완료 CSV를 먼저 확인합니다. 이미 완료된 항목은 다시
요청하지 않고, 빠진 쿠팡 항목들만 한 번의 agent batch로 수집합니다. 직접 한 품목을
점검하려면 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m app.collectors.coupang_agent --date 2026-09-26 --item 111:10
```

Windows 데스크톱은 로그인된 상태로 잠금 해제되어 있어야 하며, 일반 Chrome 창을
사용합니다. 화면 좌표 클릭은 사용하지 않습니다. 접근 차단, CAPTCHA 또는 로그인
요구를 우회하지 않으며 agent 수집이 실패한 품목에만 기존 Playwright 수집기를
fallback으로 실행합니다. Codex CLI 호출에는 계정 사용량이 발생합니다.
Windows UI Automation 프로세스 실행 때문에 기본 `CODEX_SANDBOX_MODE`는
`danger-full-access`입니다. 이 설정은 명시적 `coupang-ui-collector` skill에만 사용하고,
외부 prompt나 임의 명령 실행에 재사용하지 마세요.

원시 agent 파일은 `data/runs/coupang-agent/<run-id>/` 아래의 `manifest.json`,
`result-schema.json`, `agent-result.json`, `offers.csv`로 남습니다. 검증을 통과한 결과는
`data/normalized/online_offers.csv`, 판단 사유는
`data/normalized/online_offer_decisions.csv`, 일별 평균은
`data/normalized/online_price_summaries.csv`에서 확인합니다. 실행 원인과 실패 범위는
`log/logs/`의 `codex_cli.*`, `coupang_agent.*`, `online.collection.*` 이벤트로 추적합니다.

API에서 직접 실행할 때는 `POST /api/v1/collections/coupang-agent`에 다음 JSON을
전송합니다. `item`을 생략하면 설정된 대표 10개 중 당일 누락 항목만 처리합니다.

```json
{"observed_date":"2026-09-26","item":"111:10"}
```

KAMIS 도매·소매가격, 네이버·쿠팡 온라인 판매가격, 원자재 선물과 주요 주가지수를 하루 한 번 수집해 비교·분석하는 FastAPI 프로젝트입니다. 데이터는 CSV에 원본·정규화 형태로 보존하며 웹에서 검색, 필터, 표, 그래프와 상관관계 분석을 제공합니다.

## 저장소 클론 및 실행

### Windows PowerShell

1. 저장소를 클론하고 프로젝트 폴더로 이동합니다.

```powershell
git clone https://github.com/EazyNick/KAMIS.git
Set-Location KAMIS
```

2. Python 3.11 가상환경을 만들고 패키지와 Chromium을 설치합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

3. 환경변수 파일을 만들고 KAMIS 인증정보를 입력합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`의 필수 항목은 다음과 같습니다. 실제 키는 Git에 커밋하지 마세요.

```dotenv
KAMIS_CERT_KEY=발급받은_API_키
KAMIS_CERT_ID=발급받은_요청자_ID
```

4. 웹 서버를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000
```

서버가 시작되면 서울 기준 오늘의 `daily_pipeline` 성공 이력을 자동으로 확인합니다. 오늘 성공 이력이 없거나 이전 실행이 실패·부분 실패라면 백그라운드에서 KAMIS·네이버·쿠팡·시장 데이터 통합 수집을 시작합니다. 수집 중에도 대시보드와 API는 바로 사용할 수 있으며, 이미 성공한 날짜에는 다시 수집하지 않습니다.

수집 도중 서버가 종료된 경우에도 다음 실행에서 날짜별 KAMIS·온라인·시장 성공 체크포인트와 기존 CSV의 관측일을 확인합니다. 이미 저장까지 완료된 소스는 건너뛰고 실패·부분 완료·미실행 소스만 다시 수집하며, 이 판단은 `log/logs/`의 `daily_pipeline.checkpoint.recovered`와 `daily_pipeline.source.skipped` 이벤트에서 확인할 수 있습니다.

KAMIS 품목·도매가·소매가는 전체 수집하고, 네이버·쿠팡 검색은 대표 KAMIS 품목 10개에만 수행합니다(플랫폼별 10회, 하루 최대 20회). 기본 요청 간격은 5초이며 진행 상황과 실패 원인은 `log/logs/`의 로그에서 확인할 수 있습니다.

온라인 수집은 기본적으로 설치된 Google Chrome과 `data/browser-profile`의 전용 프로필을 화면 표시 모드로 재사용합니다. 쿠팡은 검색 URL로 직접 진입하지 않고 홈페이지를 연 뒤 검색창을 사용합니다. 서버 환경에 Chrome이 없으면 `.env`의 `SHOPPING_BROWSER_CHANNEL`을 빈 값으로 설정해 Playwright Chromium을 사용할 수 있지만, 쿠팡은 해당 브라우저를 차단할 수 있습니다. `ONLINE_TARGETS`에는 정확히 10개의 KAMIS `item_code:kind_code` 쌍을 지정할 수 있습니다. HTTP 403/418/429, `Access Denied` 또는 CAPTCHA가 감지되면 우회하지 않고 그 플랫폼의 남은 검색을 당일 중단합니다.

### VS Code에서 실행

프로젝트 루트가 `D:\Python\KAMIS`라면 다음 두 방식 모두 지원합니다.

```powershell
# 권장 방식
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000

# app/main.py를 직접 실행하는 방식
.\.venv\Scripts\python.exe app\main.py
```

VS Code의 Python 인터프리터는 `.venv\Scripts\python.exe`를 선택하고, 반드시 저장소 루트를 작업 폴더로 연 뒤 실행하세요.

### macOS/Linux

```bash
git clone https://github.com/EazyNick/KAMIS.git
cd KAMIS
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium
cp .env.example .env
# 편집기로 .env에 KAMIS_CERT_KEY와 KAMIS_CERT_ID를 입력합니다.
./.venv/bin/python -m app.cli serve --host 127.0.0.1 --port 8000
```

## 실행 후 접속 주소

- 웹 대시보드: <http://127.0.0.1:8000/>
- API 문서: <http://127.0.0.1:8000/docs>
- 상태 확인: <http://127.0.0.1:8000/health>
- 개발·운영 안내: [docs/dev/README.md](docs/dev/README.md)

## 추가 수집 명령

KAMIS만 지정 기간으로 수집하거나 과거 3년 자료를 초기 적재할 수 있습니다.

```powershell
$today = Get-Date -Format yyyy-MM-dd
.\.venv\Scripts\python.exe -m app.cli collect-all --date $today
.\.venv\Scripts\python.exe -m app.cli collect-kamis --start 2026-09-24 --end 2026-09-24
.\.venv\Scripts\python.exe -m app.cli backfill-kamis --years 3
.\.venv\Scripts\python.exe -m app.cli schedule
```

## 수집기 개별 실행

서버가 사용하는 KAMIS·네이버·쿠팡·시장 수집기는 각각 독립된 파일로도 실행할 수 있습니다. 네이버·쿠팡 문제를 확인할 때는 `--headful`로 브라우저를 표시하고, `--item`으로 KAMIS 품목 하나만 지정할 수 있습니다.

```powershell
# KAMIS 전체 품목의 해당 날짜 가격
.\.venv\Scripts\python.exe app\collectors\kamis.py --date 2026-09-25

# 네이버 대표 10개 / 쌀 10kg 한 품목만 화면 표시
.\.venv\Scripts\python.exe app\collectors\naver.py --date 2026-09-25 --headful
.\.venv\Scripts\python.exe app\collectors\naver.py --date 2026-09-25 --item 111:10 --headful

# 쿠팡 대표 10개 / 쌀 10kg 한 품목만 화면 표시
.\.venv\Scripts\python.exe app\collectors\coupang.py --date 2026-09-25 --headful
.\.venv\Scripts\python.exe app\collectors\coupang.py --date 2026-09-25 --item 111:10 --headful

# 주가지수·선물·환율
.\.venv\Scripts\python.exe app\collectors\market.py --date 2026-09-25
```

날짜를 생략하면 서울 기준 오늘을 사용합니다. 네이버·쿠팡 단독 실행 결과는 해당 플랫폼 데이터만 갱신하며 다른 플랫폼과 기존 통합 평균은 덮어쓰지 않습니다. HTTP 403/418/429 또는 CAPTCHA는 로그에 `shopping.search.failed`와 `online.collection.source.blocked`로 기록됩니다.

실제 인증정보는 `.env`에만 저장하며 저장소, 로그, 화면에 노출하지 않습니다.

대시보드는 KAMIS 도매·소매, 네이버, 쿠팡, 통합 온라인 평균, 국내외 5개 주가지수와 관련 농산물 선물·환율을 제공합니다. 조회 기간의 원값 기준 변동폭이 가장 큰 선물은 `주목` 항목으로 범례 맨 앞에 배치하고 기본 활성화합니다. 시계열별 활성화, 기준 100·원값·1일·7일 변화율, 날짜 필터, 검색 가능한 웹 테이블과 상관관계 분석을 지원합니다.
