# KAMIS 가격 비교·상관관계 대시보드

KAMIS 도매·소매가격, 네이버·쿠팡 온라인 판매가격, 원자재 선물과 주요 주가지수를 하루 한 번 수집해 비교·분석하는 FastAPI 기반 프로젝트입니다. 데이터는 CSV에 원본/정규화 형태로 보존하며 웹에서 검색, 필터, 표, 그래프와 상관관계 분석을 제공합니다.

## 빠른 실행

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.cli collect-kamis --start 2026-09-24 --end 2026-09-24
.\.venv\Scripts\python.exe -m app.cli backfill-kamis --years 3
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m app.cli collect-all --date 2026-09-24
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000
```

- API 문서: <http://127.0.0.1:8000/docs>
- 상태 확인: <http://127.0.0.1:8000/health>
- 웹 대시보드: <http://127.0.0.1:8000/>
- 개발·운영 안내: [docs/dev/README.md](docs/dev/README.md)

실제 인증정보는 `.env`에만 저장하며 저장소, 로그, 화면에 노출하지 않습니다.

대시보드는 KAMIS 도매·소매, 네이버, 쿠팡, 통합 온라인 평균, 국내외 5개 주가지수와 관련 농산물 선물·환율을 제공합니다. 시계열별 활성화, 기준 100·원값·1일·7일 변화율, 날짜 필터, 검색 가능한 웹 테이블과 상관관계 분석을 지원합니다.
