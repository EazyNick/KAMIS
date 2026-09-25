# Coupang Codex Agent Collector Design

## 목적

FastAPI 일일 수집 파이프라인이 쿠팡의 대표 KAMIS 품목 10개를 일반 Chrome 사용자 세션에서 수집할 수 있게 한다. 서버는 저장소 전용 Codex skill을 명시적으로 호출하는 `codex exec` 프로세스를 시작하고, skill은 Windows 접근성 API로 쿠팡 홈페이지 검색창을 조작한다. 현재 Playwright 수집기는 agent 경로가 실패할 때 사용하는 예비 경로로 보존한다.

성공 조건은 다음과 같다.

- 서버가 시작될 때 오늘 날짜의 쿠팡 결과가 완전하면 Codex를 호출하지 않는다.
- 일부 품목만 있거나 실패 상태이면 누락된 품목만 agent 수집 대상으로 전달한다.
- 한 번의 `codex exec` 실행에서 대상 품목을 일괄 검색한다.
- 원시 후보는 실행 전용 CSV로 남고, 애플리케이션이 검증한 데이터만 기존 온라인 가격 저장소에 반영한다.
- 네이버 수집, KAMIS 수집, 시장 데이터 수집 및 기존 쿠팡 Playwright 진입점은 기존 동작을 유지한다.
- 로그만으로 명령, 실행 시간, 종료 코드, 대상 수, 수집 수, 제외 수, 예비 경로 실행 이유를 파악할 수 있다.

## 범위

### 포함

- 저장소 전용 `.agents/skills/coupang-ui-collector` skill
- Windows UI Automation 기반 쿠팡 홈페이지 검색 및 접근성 트리 추출 스크립트
- Python `subprocess` 기반 Codex CLI 실행기
- agent 결과 CSV 파서와 도메인 검증
- 쿠팡 agent 우선, Playwright 예비 수집 소스
- 대표 품목 10개의 단일 배치 실행과 품목별 부분 재수집
- 서버 시작 일일 파이프라인 통합
- 수동 실행용 Python 진입점과 FastAPI 엔드포인트
- 단위·통합 테스트 및 README 실행 방법

### 제외

- 쿠팡 접근 통제 우회, CAPTCHA 해제 또는 탐지 회피
- 쿠팡 계정 로그인 자동화와 자격 증명 저장
- 네이버 수집기의 agent 전환
- 대표 10개 이외 온라인 상품 수집
- Codex SDK 또는 App Server 도입

## 실행 전제

- Windows 사용자가 로그인된 대화형 데스크톱에서 FastAPI가 실행된다.
- 일반 Chrome 창을 열 수 있고 Windows 접근성 트리에서 웹 콘텐츠가 노출된다.
- Codex CLI가 설치되어 있으며 사용자의 저장된 CLI 인증으로 `codex exec`가 실행된다.
- 데스크톱이 잠겼거나 Chrome 접근성 요소를 읽을 수 없으면 agent 경로는 명시적으로 실패하며 Playwright 예비 경로가 실행된다.
- 사이트가 CAPTCHA 또는 접근 거부 화면을 표시하면 수집 성공으로 기록하지 않는다.

## 아키텍처

### 1. 저장소 전용 skill

경로는 `.agents/skills/coupang-ui-collector/`로 한다. Codex CLI는 저장소 루트에서 실행되므로 이 skill을 자동 발견한다. FastAPI가 만드는 프롬프트는 `$coupang-ui-collector`를 명시적으로 호출한다.

skill 구성은 다음과 같다.

- `SKILL.md`: 입력 manifest와 출력 CSV 계약, 실행 순서, 성공 판정 및 중단 조건
- `scripts/collect_coupang_ui.ps1`: Windows UI Automation으로 Chrome과 쿠팡을 조작하는 결정적 실행기
- `references/csv-schema.md`: 원시 후보 CSV 열과 값 제약
- `agents/openai.yaml`: 표시 이름과 명시적 호출용 기본 프롬프트

skill은 임의 웹 탐색이나 코드 수정을 수행하지 않는다. 전달받은 manifest를 읽고 지정된 출력 CSV만 생성하며, 대상은 최대 10개로 제한한다. 홈페이지를 먼저 연 뒤 접근성 이름이 `쿠팡 상품 검색`인 입력란을 찾아 검색한다. 각 요청 사이에는 설정된 최소 간격을 둔다.

### 2. Codex CLI 실행기

`CodexCliRunner`는 인자 배열로 `codex exec`를 실행하며 `shell=True`를 사용하지 않는다. 실행 위치는 저장소 루트로 고정한다. 공식 비대화형 모드에 맞춰 `--ephemeral`, 명시적 sandbox 설정, 구조화된 최종 출력 schema와 제한시간을 사용한다.

입력은 실행 전용 디렉터리의 JSON manifest다. manifest에는 다음만 포함한다.

- `run_id`
- `observed_date`
- 출력 CSV의 절대 경로
- 요청 간 최소 간격
- 대상별 `item_code`, `kind_code`, `item_name`, `variety`, 비교 단위 및 검색어

stdout, stderr, 종료 코드와 실행 시간은 로그에 기록한다. 인증 토큰, 쿠키, 전체 환경 변수는 로그에 기록하지 않는다. 프로세스 제한시간이 지나면 자식 프로세스를 종료하고 실패로 반환한다.

### 3. Windows UI 수집 스크립트

PowerShell 스크립트가 담당하는 일은 다음으로 제한한다.

1. manifest 형식과 출력 경로가 프로젝트의 실행 전용 디렉터리 내부인지 검증한다.
2. 일반 Chrome 프로세스가 없으면 새 Chrome 창으로 `https://www.coupang.com/`을 연다.
3. 쿠팡 문서와 `쿠팡 상품 검색` 접근성 요소를 찾는다.
4. 각 검색어를 입력하고 결과 문서가 바뀔 때까지 조건 기반으로 대기한다.
5. 상품 결과의 접근성 이름에서 원문 상품명, 표시 가격, 단위가격 문구, 배송 문구와 광고 여부를 추출한다.
6. 접근 거부, CAPTCHA, 결과 없음과 시간 초과를 구분한다.
7. 임시 파일에 CSV를 기록한 후 원자적으로 최종 출력 경로로 이동한다.

화면 좌표 클릭은 DPI와 창 위치에 따라 달라지므로 사용하지 않는다. 접근성 컨트롤의 `ValuePattern`과 포커스 조작을 기본으로 한다. Chrome 주소창을 통한 쿠팡 검색 결과 URL 직접 진입은 사용하지 않는다.

### 4. CSV 데이터 계약

원시 CSV의 각 행은 하나의 상품 후보다. 필수 열은 다음과 같다.

- `run_id`, `observed_date`, `collected_at`
- `platform`
- `item_code`, `kind_code`
- `query`
- `product_id`
- `title`
- `url`
- `displayed_price`
- `shipping_fee`
- `member_price`
- `member_discount_scope`
- `quantity`, `unit`
- `unit_price_text`
- `advertisement`
- `availability`
- `raw_accessible_name`

`platform`은 `coupang`만 허용한다. 날짜와 실행 ID는 manifest와 일치해야 한다. 가격과 수량은 음수가 될 수 없고, 상품 ID가 없으면 접근성 원문을 기반으로 안정적인 해시 ID를 만든다. 모든 열은 CSV injection 방지를 위해 `=`, `+`, `-`, `@`로 시작하는 문자열을 이스케이프한다.

### 5. 애플리케이션 검증과 변환

Python의 `CoupangAgentCsvParser`가 원시 CSV를 읽고 `ShoppingOffer`로 변환한다. 다음 후보는 저장은 하되 평균 계산에서 제외 사유를 남긴다.

- 품목명이 일치하지 않는 상품
- 목표 품종과 호환되지 않는 상품
- 목표 중량 또는 개수로 정규화할 수 없는 상품
- 모종, 씨앗, 가공식품, 냉동 제품처럼 KAMIS 원물과 다른 상품
- 품절 상품
- 모든 회원에게 적용되지 않는 카드·쿠폰·결제수단·유료 멤버십 전용 가격

모든 가입 회원이 받을 수 있는 회원 가격만 `member_discount_scope=all_members`로 사용한다. 배송비는 비교 총액에 포함한다. 검증을 통과한 후보는 기존 `OnlinePriceCalculator`에 전달되어 최저가 이상치 제거와 최대 5개 평균 규칙을 그대로 적용한다.

### 6. 배치 수집 인터페이스

현재 `ShoppingSourceProtocol.search()`는 품목마다 호출된다. Codex 프로세스를 10번 만들지 않도록 선택적 배치 프로토콜을 추가한다.

- 일반 소스는 기존 `search(entry, observed_date)`를 유지한다.
- batch 기능이 있는 쿠팡 agent 소스는 수집 시작 전에 전체 누락 대상 목록을 받아 한 번 실행한다.
- 배치 결과는 `(item_code, kind_code)`별 메모리 캐시에 보관하고 기존 `search()` 호출에 반환한다.
- agent 배치가 전체 또는 일부 실패하면 누락된 품목에 대해서만 기존 Playwright 쿠팡 소스를 호출한다.

네이버 소스와 기존 서비스 소비자는 이 변경을 알 필요가 없다.

### 7. 일일 완전성 판단

플랫폼별, 날짜별, 대표 품목별 요약 상태를 검사한다. 쿠팡의 각 대상은 다음 중 하나일 때 완료로 본다.

- 유효 후보로 계산된 `available`
- 실제 검색 결과가 없음을 확인한 `unavailable`

`blocked`, `collection_failed`, CSV 누락 또는 행 검증 실패는 완료가 아니다. 이미 완료된 품목은 manifest에서 제외한다. 모든 품목이 완료되어 있으면 Codex CLI와 Playwright 모두 실행하지 않는다.

기존 `online` 체크포인트가 부분 실패였더라도 저장된 네이버 및 쿠팡 품목 상태를 기준으로 누락 범위를 다시 계산한다.

### 8. FastAPI 및 수동 실행

서버 시작 시 기존 `StartupCollectionService`의 백그라운드 스레드에서 일일 파이프라인이 실행된다. HTTP 애플리케이션 시작 자체는 agent 완료를 기다리지 않는다.

수동 실행은 두 경로를 제공한다.

- `POST /api/v1/collections/coupang-agent`: 요청 날짜와 선택적 `item_code:kind_code`를 받아 기존 동시 실행 잠금을 사용한다.
- `python -m app.collectors.coupang_agent --date YYYY-MM-DD [--item ITEM:KIND]`: 동일한 서비스 객체를 사용한다.

응답은 실행 ID, 상태, 대상 수, 수집 후보 수, 유효 후보 수, 예비 경로 사용 품목과 오류 수를 제공한다. 동기 엔드포인트는 제한시간 내 결과를 반환하며, 이미 실행 중이면 HTTP 409를 반환한다.

## 권한과 보안

- Codex CLI는 저장소 루트에서만 실행하고 쓰기 가능 범위를 프로젝트 작업공간으로 제한한다.
- agent 프롬프트는 하나의 skill과 manifest만 지시하며 임의 명령 실행을 요구하지 않는다.
- PowerShell 실행은 프로젝트에 포함된 정확한 스크립트 경로와 인자 형식으로 제한한다.
- 광범위한 `danger-full-access`를 기본값으로 사용하지 않는다.
- 비대화형 실행에서 추가 승인이 필요하면 실패로 처리하고 Playwright 예비 경로로 전환한다.
- `.env`, Codex 인증 파일과 브라우저 쿠키를 CSV 또는 로그에 기록하지 않는다.
- 외부 입력 문자열을 shell 명령 문자열에 보간하지 않는다.

## 로깅

기존 `log.logger.StructuredLogger`만 사용한다. 최소 이벤트는 다음과 같다.

- `coupang.agent.batch.started`
- `coupang.agent.codex.started`
- `coupang.agent.codex.completed`
- `coupang.agent.codex.failed`
- `coupang.agent.csv.validated`
- `coupang.agent.item.completed`
- `coupang.agent.item.failed`
- `coupang.agent.fallback.started`
- `coupang.agent.fallback.completed`
- `coupang.agent.batch.completed`

모든 이벤트에는 가능한 경우 `run_id`, `observed_date`, 대상 수, 품목 코드, 실행 시간, 종료 코드, CSV 경로, 후보 수와 오류 유형을 포함한다. stderr는 길이를 제한하고 비밀값을 제거한 후 기록한다.

## 오류 처리

- Codex CLI 미설치 또는 인증 실패: agent 전체 실패, 모든 누락 대상에 Playwright 실행
- Chrome 미실행: 일반 프로필의 새 창 실행을 시도하고 실패하면 예비 경로 실행
- 데스크톱 잠김 또는 접근성 요소 미노출: 명확한 환경 오류로 기록하고 예비 경로 실행
- 일부 검색 시간 초과: 성공 품목은 유지하고 실패 품목만 예비 경로 실행
- 잘못된 CSV: 행 단위 검증 오류를 기록하되 유효 행은 보존하고, 유효 행이 없는 품목만 예비 경로 실행
- 접근 거부 또는 CAPTCHA: 성공 데이터로 저장하지 않고 해당 품목을 예비 경로 대상으로 표시
- FastAPI 종료: 실행 중인 Codex 자식 프로세스에 종료 신호를 보내고 제한시간 뒤 강제 종료

## 테스트 전략

테스트는 실제 Codex 사용량이나 실제 쿠팡 접속 없이 기본적으로 실행한다.

- CLI 인자, 작업 디렉터리, 제한시간과 stdout/stderr 처리 단위 테스트
- manifest 및 CSV schema 검증 테스트
- 악성 CSV 셀, 경로 이탈, 잘못된 날짜·플랫폼·가격 테스트
- 배치 한 번으로 10개 품목을 처리하는 테스트
- 일부 품목 성공 시 실패 품목에만 Playwright가 실행되는 테스트
- 오늘 데이터가 완전하면 Codex가 호출되지 않는 테스트
- 중간 중단 데이터에서 누락 품목만 호출되는 테스트
- FastAPI 409 및 결과 응답 테스트
- 수동 CLI 인자 테스트
- 기존 Playwright 및 전체 테스트 회귀 검증

실환경 검증은 별도 명령으로 수행하며 일반 Chrome, 활성 데스크톱, 저장된 Codex 인증이 필요하다는 점을 README에 명시한다. 실환경 검증 결과 CSV는 테스트 fixture로 커밋하지 않는다.

## 운영상 제한

이 경로는 LLM 실행 시간과 Codex 사용량이 발생하며 일반 결정적 크롤러보다 느리다. UI와 접근성 이름이 바뀌면 skill 스크립트를 수정해야 한다. 서버가 Windows 서비스나 잠긴 세션에서 실행되면 UI 수집은 동작하지 않는다. 이러한 제약 때문에 기존 Playwright 경로를 보존하고, 실패 상태를 정상 수집으로 오인하지 않도록 날짜별 완전성 검사를 유지한다.
