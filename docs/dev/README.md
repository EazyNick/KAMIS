# KAMIS 개발 환경 가이드

이 문서는 저장소를 처음 클론한 개발자가 로컬 개발 환경을 구성하기 위한 안내서다.

> 현재 프로젝트는 초기 개발 단계다. 데이터 수집기와 웹 대시보드의 실행 진입점은 구현하면서 이 문서에 계속 추가한다.

## 1. 사전 요구사항

- Git
- Python 3.11 권장
- VS Code 또는 원하는 Python IDE
- KAMIS Open API 인증 키와 요청자 ID

현재 `requirements.txt`는 Python 3.11 환경에서 생성됐다. 다른 Python 버전에서도 설치할 수 있지만 동일한 재현 환경이 필요하면 3.11을 사용한다.

## 2. 저장소 클론

```bash
git clone <repository-url>
cd KAMIS
```

`<repository-url>`은 실제 Git 저장소 주소로 교체한다.

## 3. 가상환경 생성 및 활성화

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 때문에 활성화가 차단되면 현재 터미널에서만 다음 정책을 적용한다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

활성화 없이도 가상환경의 Python을 직접 사용할 수 있다.

```powershell
.\.venv\Scripts\python.exe --version
```

### macOS/Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

## 4. Python 패키지 설치

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### macOS/Linux

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

설치 상태는 다음 명령으로 확인한다.

```bash
python -m pip check
```

## 5. Playwright 브라우저 설치

Python 패키지와 별도로 크롤링 실행에 필요한 Chromium 런타임을 설치한다.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### macOS/Linux

```bash
python -m playwright install chromium
```

대상 사이트의 이용약관과 `robots.txt`를 확인하고, CAPTCHA나 접근 제한을 우회하지 않는다.

## 6. 환경변수 설정

루트의 `.env.example`을 `.env`로 복사한다.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS/Linux

```bash
cp .env.example .env
```

`.env`에 발급받은 값을 입력한다.

```dotenv
KAMIS_CERT_KEY=your_kamis_api_key
KAMIS_CERT_ID=your_kamis_requester_id
```

`.env`는 Git에 커밋하지 않는다. 실제 인증 키를 문서, 로그, 테스트 코드 또는 화면 캡처에 포함하지 않는다.

## 7. VS Code 설정

1. VS Code에서 저장소 루트를 연다.
2. 명령 팔레트에서 `Python: Select Interpreter`를 실행한다.
3. Windows는 `.venv\Scripts\python.exe`, macOS/Linux는 `.venv/bin/python`을 선택한다.
4. 새 터미널을 열고 Python 경로를 확인한다.

```powershell
python -c "import sys; print(sys.executable)"
```

출력 경로가 이 저장소의 `.venv` 아래여야 한다.

## 8. 로그 위치

프로젝트 로그는 다음 경로에 저장한다.

```text
log/logs/
```

`log` 패키지를 통해 생성되는 로그 파일은 해당 디렉터리에 모으며, 런타임 로그 파일은 Git에 커밋하지 않는다.

## 9. 개발 도구

### 테스트

```bash
python -m pytest
```

### 린트

```bash
python -m ruff check .
```

### 코드 포맷 확인 및 적용

```bash
python -m ruff format --check .
python -m ruff format .
```

## 10. 의존성 변경

새 패키지는 반드시 프로젝트 가상환경에 설치한다.

```bash
python -m pip install <package-name>
```

설치 또는 제거 후 현재 환경을 고정한다.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m pip freeze | Set-Content requirements.txt -Encoding utf8
```

### macOS/Linux

```bash
python -m pip freeze > requirements.txt
```

커밋 전 다음 검사를 수행한다.

```bash
python -m pip check
python -m pytest
python -m ruff check .
```

## 11. 현재 주요 라이브러리

| 용도 | 라이브러리 |
|---|---|
| HTTP/API | `requests`, `python-dotenv`, `tenacity` |
| HTML 수집 | `beautifulsoup4`, `lxml`, `playwright` |
| 데이터 처리 | `pandas`, `openpyxl`, `duckdb` |
| 통계 분석 | `scipy`, `statsmodels` |
| 금융 데이터 | `yfinance` |
| 웹 대시보드 | `streamlit`, `plotly` |
| 배치 실행 | `APScheduler` |
| 로그 | `colorlog` |
| 테스트·품질 | `pytest`, `ruff` |

## 12. 문서 위치

- 공모전 기획: `docs/Contest/KAMIS_공모전_주제_기획.md`
- 개발 환경: `docs/dev/README.md`

데이터 수집기와 대시보드가 구현되면 다음 내용을 추가한다.

- 디렉터리 구조와 모듈 역할
- 수집기별 실행 명령
- 데이터 스키마와 CSV 예제
- 스케줄러 등록 방법
- Streamlit 실행 및 배포 방법
- 테스트 데이터와 장애 대응 절차
