# KAMIS FastAPI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KAMIS 품목 사전과 도매·소매가격을 실제 수집하고 3년 자료를 백필해 CSV로 보존하며, FastAPI로 조회·수집 상태를 제공하고 실행 흐름과 실패 원인을 파일 로그만으로 추적할 수 있는 객체지향 백엔드를 구축한다.

**Architecture:** 설정, 도메인, 외부 API 클라이언트, CSV 저장소, 수집 서비스, 웹 API를 분리한 포트·어댑터 구조를 사용한다. FastAPI와 스케줄러는 동일한 `KamisCollectionService`를 호출하고, 모든 계층은 기존 `log` 패키지의 구조화 메시지 어댑터를 사용한다.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, requests, python-dotenv, pandas, APScheduler, tenacity, pytest, Ruff

**Spec:** `docs/Contest/KAMIS_공모전_주제_기획.md`, `docs/api/KAMIS_API_명세.md`

## Global Constraints

- 모든 애플리케이션 코드는 클래스 단위로 책임을 분리하고 생성자 주입을 사용한다.
- 제품 코드에서 `print()`를 사용하지 않는다. `log.log_manager` 기반 로깅만 사용한다.
- 로그에는 event, run_id, source, action, duration_ms, record_count와 예외 원인을 포함한다.
- API 키, 요청자 ID, 전체 요청 URL의 인증 쿼리는 로그에 남기지 않는다.
- KAMIS 원본·정규화 데이터는 CSV로 저장하고, 실패 시 이전 값을 복제하지 않는다.
- `productInfo`, `periodWholesaleProductList`, `periodRetailProductList`를 사용한다.
- 기간조회 한 번의 범위는 1년을 넘지 않는다.
- 날짜와 파일시각은 Asia/Seoul 기준으로 기록한다.
- FastAPI 경로는 `/api/v1` 아래에 둔다.
- 테스트는 네트워크에 의존하지 않으며 실제 호출은 별도 스모크 명령으로만 수행한다.

## Review Focus

1. KAMIS가 HTTP 200과 오류코드 900을 함께 반환할 때 인증 실패로 기록하고 비밀값은 로그에서 마스킹해야 한다. Task 3에서 테스트한다.
2. `productInfo`의 빈 배열·빈 문자열 필드는 모두 결측으로 정규화돼야 한다. Task 2와 Task 3에서 테스트한다.
3. 1년을 넘는 백필 기간은 1년 이하 구간으로 분리되고 경계 중복이 제거돼야 한다. Task 5에서 테스트한다.
4. 한 품목 수집 실패가 전체 실행을 중단시키지 않되 실행 결과는 partial_failure가 돼야 한다. Task 5에서 테스트한다.
5. 동시에 두 번 수집을 요청하면 두 번째 실행은 409를 반환하고 중복 CSV를 만들지 않아야 한다. Task 6에서 테스트한다.

---

## File Structure

```text
app/
  __init__.py
  main.py                    # FastAPI 앱 팩토리
  cli.py                     # 수집·서버 실행 CLI
  api/
    __init__.py
    dependencies.py          # 컨테이너 의존성
    routes_health.py         # 상태 확인
    routes_catalog.py        # 품목 사전 조회
    routes_prices.py         # 가격 조회
    routes_collection.py     # 수집 실행·이력 조회
  core/
    __init__.py
    container.py             # 객체 조립
    errors.py                # 명시적 예외 계층
  domain/
    __init__.py
    models.py                # 도메인 dataclass와 enum
  infrastructure/
    __init__.py
    kamis_client.py          # KAMIS HTTP 어댑터
    csv_repository.py        # CSV 저장·조회 어댑터
  services/
    __init__.py
    collection_service.py    # 수집 유스케이스
    scheduler.py             # 하루 한 번 실행
config/
  __init__.py
  server_config.py           # 환경변수 설정
log/
  logger.py                  # 기존 로거 보완
  context_logger.py          # 구조화 메시지와 비밀값 마스킹
tests/
  conftest.py
  test_config.py
  test_logging.py
  domain/test_models.py
  infrastructure/test_kamis_client.py
  infrastructure/test_csv_repository.py
  services/test_collection_service.py
  api/test_routes.py
data/
  .gitkeep
```

## Task 1: Runtime Configuration and Logging Foundation

**Files:**
- Create: `config/__init__.py`
- Create: `config/server_config.py`
- Create: `log/context_logger.py`
- Modify: `log/logger.py`
- Modify: `log/__init__.py`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Test: `tests/test_config.py`
- Test: `tests/test_logging.py`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`
- Produces: `Settings.require_kamis_credentials() -> tuple[str, str]`
- Produces: `ContextLogger.info(event: str, message: str, **context: object) -> None`
- Produces: `ContextLogger.exception(event: str, message: str, error: BaseException, **context: object) -> None`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_settings_load_paths_relative_to_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path / "data"
    assert settings.timezone == "Asia/Seoul"


def test_missing_kamis_credentials_raise_clear_error(monkeypatch):
    monkeypatch.delenv("KAMIS_CERT_KEY", raising=False)
    monkeypatch.delenv("KAMIS_CERT_ID", raising=False)
    with pytest.raises(ConfigurationError, match="KAMIS_CERT_KEY"):
        Settings.from_env().require_kamis_credentials()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`  
Expected: FAIL because `config.server_config.Settings` does not exist.

- [ ] **Step 3: Implement immutable settings**

```python
@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    log_level: str
    timezone: str
    kamis_base_url: str
    kamis_cert_key: str | None
    kamis_cert_id: str | None
    request_timeout_seconds: float
    scheduler_hour: int
    scheduler_minute: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        root = Path(__file__).resolve().parents[1]
        return cls(
            project_root=root,
            data_dir=Path(os.getenv("DATA_DIR", root / "data")).resolve(),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            timezone=os.getenv("APP_TIMEZONE", "Asia/Seoul"),
            kamis_base_url=os.getenv(
                "KAMIS_BASE_URL",
                "https://www.kamis.or.kr/service/price/xml.do",
            ),
            kamis_cert_key=os.getenv("KAMIS_CERT_KEY"),
            kamis_cert_id=os.getenv("KAMIS_CERT_ID"),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            scheduler_hour=int(os.getenv("SCHEDULER_HOUR", "7")),
            scheduler_minute=int(os.getenv("SCHEDULER_MINUTE", "0")),
        )

    def require_kamis_credentials(self) -> tuple[str, str]:
        if not self.kamis_cert_key or not self.kamis_cert_id:
            raise ConfigurationError(
                "KAMIS_CERT_KEY and KAMIS_CERT_ID must be configured"
            )
        return self.kamis_cert_key, self.kamis_cert_id
```

- [ ] **Step 4: Write failing logging tests**

```python
def test_context_logger_masks_secrets(caplog):
    logger = ContextLogger(logging.getLogger("test"))
    logger.info(
        "kamis.request",
        "request started",
        cert_key="secret-value",
        run_id="run-1",
    )
    assert "secret-value" not in caplog.text
    assert "cert_key=***" in caplog.text
    assert "event=kamis.request" in caplog.text
```

- [ ] **Step 5: Run logging test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_logging.py -v`  
Expected: FAIL because `ContextLogger` does not exist.

- [ ] **Step 6: Implement structured context logger and repair existing logger**

```python
class ContextLogger:
    _secret_keys = {"cert_key", "api_key", "authorization", "password"}

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _message(self, event: str, message: str, context: Mapping[str, object]) -> str:
        safe = {
            key: "***" if key.lower() in self._secret_keys else value
            for key, value in context.items()
        }
        fields = " ".join(f"{key}={safe[key]!s}" for key in sorted(safe))
        return f"event={event} message={message!r}" + (f" {fields}" if fields else "")

    def info(self, event: str, message: str, **context: object) -> None:
        self._logger.info(self._message(event, message, context))

    def exception(
        self,
        event: str,
        message: str,
        error: BaseException,
        **context: object,
    ) -> None:
        self._logger.exception(
            self._message(
                event,
                message,
                {**context, "error_type": type(error).__name__, "error": str(error)},
            )
        )
```

Modify `LogManager` to read `settings.log_level`, remove both `print()` calls, and log cleanup failures through a bootstrap logger. Export `app_logger = ContextLogger(log_manager.logger)` from `log/__init__.py`.

- [ ] **Step 7: Add dependencies and ignore runtime data**

Run `.\.venv\Scripts\python.exe -m pip install fastapi httpx`, then run `.\.venv\Scripts\python.exe -m pip freeze` and update `requirements.txt` with the resolved exact versions. Add `data/raw/`, `data/normalized/`, and `data/runs/` to `.gitignore` while preserving `data/.gitkeep`.

- [ ] **Step 8: Run tests and quality checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_logging.py -v
.\.venv\Scripts\python.exe -m ruff check config log tests/test_config.py tests/test_logging.py
```

Expected: all tests PASS and Ruff exits 0.

- [ ] **Step 9: Commit**

```bash
git add config log tests requirements.txt .gitignore data/.gitkeep
git commit -m "feat: add runtime configuration and structured logging"
```

## Task 2: Domain Models and Validation

**Files:**
- Create: `app/__init__.py`
- Create: `app/domain/__init__.py`
- Create: `app/domain/models.py`
- Create: `app/core/errors.py`
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Produces: `ProductCatalogEntry.from_api(data: Mapping[str, object])`
- Produces: `PriceObservation.from_api(data, price_type, codes, collected_at)`
- Produces: `CollectionRun.start(source, requested_start, requested_end)`
- Produces enums: `PriceType`, `RunStatus`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_catalog_entry_normalizes_empty_arrays():
    entry = ProductCatalogEntry.from_api(
        {
            "itemcategorycode": "100",
            "itemcategoryname": "식량작물",
            "itemcode": "111",
            "itemname": "쌀",
            "kindcode": "01",
            "kindname": "20kg",
            "wholesale_unit": "kg",
            "wholesale_unitsize": "20",
            "retail_unit": "kg",
            "retail_unitsize": "20",
            "eco_unit": [],
            "eco_unitsize": [],
            "whole_productrankcode": "04",
            "retail_productrankcode": "04,05",
            "new_natreu_productrankcode": [],
        }
    )
    assert entry.eco_unit is None
    assert entry.wholesale_rank_codes == ("04",)
    assert entry.retail_rank_codes == ("04", "05")
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/test_models.py -v`  
Expected: FAIL because domain models do not exist.

- [ ] **Step 3: Implement frozen dataclasses and explicit validation**

Implement helper `optional_text(value)`, `split_codes(value)`, and dataclasses with `slots=True, frozen=True`. `PriceObservation` parses comma-separated price strings to `Decimal`, rejects negative values, and keeps missing prices as `None`. `CollectionRun` owns status transitions `running -> success|partial_failure|failed`.

- [ ] **Step 4: Add invalid-price and run-transition tests**

```python
def test_negative_price_is_rejected():
    with pytest.raises(DataValidationError, match="negative"):
        PriceObservation.parse_price("-1")


def test_finished_run_cannot_be_finished_twice():
    run = CollectionRun.start("kamis", date(2026, 9, 24), date(2026, 9, 24))
    finished = run.finish(RunStatus.SUCCESS, record_count=1, error_count=0)
    with pytest.raises(InvalidRunTransition):
        finished.finish(RunStatus.FAILED, record_count=0, error_count=1)
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/domain/test_models.py -v
git add app/domain app/core/errors.py tests/domain
git commit -m "feat: add KAMIS domain models"
```

## Task 3: KAMIS HTTP Client

**Files:**
- Create: `app/infrastructure/__init__.py`
- Create: `app/infrastructure/kamis_client.py`
- Test: `tests/infrastructure/test_kamis_client.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: `Settings`, `ProductCatalogEntry`, `PriceObservation`
- Produces: `KamisClient.fetch_catalog() -> list[ProductCatalogEntry]`
- Produces: `KamisClient.fetch_prices(query: PriceQuery) -> list[PriceObservation]`
- Produces: `PriceQuery(price_type, start_date, end_date, catalog_entry, rank_code, country_code, convert_kg)`

- [ ] **Step 1: Write failing catalog-client test with a real fake session**

```python
def test_fetch_catalog_parses_success_response(fake_session, settings):
    fake_session.queue_json(
        {"condition": [[[]]], "error_code": "000", "info": [CATALOG_ROW]}
    )
    client = KamisClient(settings, fake_session, app_logger)
    rows = client.fetch_catalog()
    assert rows[0].item_code == "111"
    assert fake_session.last_params == {
        "action": "productInfo",
        "p_returntype": "json",
    }
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_kamis_client.py -v`  
Expected: FAIL because `KamisClient` does not exist.

- [ ] **Step 3: Implement client request boundary**

```python
class KamisClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session,
        logger: ContextLogger,
    ) -> None:
        self._settings = settings
        self._session = session
        self._logger = logger

    def _get(self, action: str, params: dict[str, str]) -> dict[str, object]:
        started = perf_counter()
        safe_context = {"source": "kamis", "action": action}
        try:
            response = self._session.get(
                self._settings.kamis_base_url,
                params={"action": action, **params},
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            code = str(payload.get("error_code", payload.get("code", "000")))
            if code != "000":
                raise KamisApiError(code, self._extract_message(payload))
            self._logger.info(
                "kamis.request.succeeded",
                "KAMIS request completed",
                **safe_context,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return payload
        except Exception as error:
            self._logger.exception(
                "kamis.request.failed",
                "KAMIS request failed",
                error,
                **safe_context,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise
```

Use a tenacity retry policy only for connection errors, timeouts, and HTTP 429/5xx. Do not retry KAMIS codes 001, 200, or 900.

- [ ] **Step 4: Add auth-error redaction and date-limit tests**

```python
def test_auth_failure_does_not_log_credentials(fake_session, settings, caplog):
    fake_session.queue_json({"error_code": "900", "error_message": "Unauthenticated"})
    client = KamisClient(settings, fake_session, app_logger)
    with pytest.raises(KamisAuthenticationError):
        client.fetch_prices(PRICE_QUERY)
    assert settings.kamis_cert_key not in caplog.text


def test_price_query_rejects_more_than_one_year():
    with pytest.raises(DataValidationError, match="one year"):
        PriceQuery(
            price_type=PriceType.WHOLESALE,
            start_date=date(2025, 1, 1),
            end_date=date(2026, 1, 2),
            catalog_entry=CATALOG_ENTRY,
            rank_code="04",
            country_code=None,
            convert_kg=True,
        )
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/infrastructure/test_kamis_client.py -v
git add app/infrastructure/kamis_client.py tests/conftest.py tests/infrastructure
git commit -m "feat: add resilient KAMIS API client"
```

## Task 4: CSV Repositories

**Files:**
- Create: `app/infrastructure/csv_repository.py`
- Test: `tests/infrastructure/test_csv_repository.py`

**Interfaces:**
- Produces: `CatalogRepository.save_snapshot(rows, observed_date, run_id) -> Path`
- Produces: `CatalogRepository.search(filters) -> list[dict[str, object]]`
- Produces: `PriceRepository.upsert(rows, run_id) -> RepositoryWriteResult`
- Produces: `PriceRepository.search(filters) -> list[dict[str, object]]`
- Produces: `RunRepository.save(run) -> None`
- Produces: `RunRepository.get(run_id) -> CollectionRun | None`

- [ ] **Step 1: Write failing atomic-write and deduplication tests**

```python
def test_price_repository_upserts_duplicate_observations(tmp_path):
    repository = PriceRepository(tmp_path, app_logger)
    first = repository.upsert([PRICE_ROW], "run-1")
    second = repository.upsert([replace(PRICE_ROW, price_krw=Decimal("1010"))], "run-2")
    rows = repository.search(PriceFilters(item_code="111"))
    assert first.inserted == 1
    assert second.updated == 1
    assert rows[0]["price_krw"] == 1010
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_csv_repository.py -v`  
Expected: FAIL because repositories do not exist.

- [ ] **Step 3: Implement locked atomic CSV writes**

Write to a sibling `.tmp` file, flush and replace the target only after serialization succeeds. Use a process-local `threading.RLock`. Log `csv.write.started`, `csv.write.succeeded`, and `csv.write.failed` with path, run_id, inserted, updated, and duration_ms. Never log complete rows.

- [ ] **Step 4: Add malformed-existing-file test**

```python
def test_repository_preserves_existing_file_when_new_write_fails(tmp_path, monkeypatch):
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert([PRICE_ROW], "run-1")
    original = repository.path.read_bytes()
    monkeypatch.setattr(
        repository, "_serialize", Mock(side_effect=OSError("disk full"))
    )
    with pytest.raises(StorageError, match="disk full"):
        repository.upsert([PRICE_ROW], "run-2")
    assert repository.path.read_bytes() == original
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/infrastructure/test_csv_repository.py -v
git add app/infrastructure/csv_repository.py tests/infrastructure/test_csv_repository.py
git commit -m "feat: add atomic CSV repositories"
```

## Task 5: KAMIS Collection Service

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/collection_service.py`
- Test: `tests/services/test_collection_service.py`

**Interfaces:**
- Consumes: `KamisClient`, three repositories, `ContextLogger`
- Produces: `KamisCollectionService.collect(start_date, end_date) -> CollectionRun`
- Produces: `KamisCollectionService.split_backfill_period(start_date, end_date) -> tuple[DateRange, ...]`
- Produces: `KamisCollectionService.is_running -> bool`

- [ ] **Step 1: Write failing orchestration test**

```python
def test_collection_continues_after_one_item_fails(service_fixture):
    service_fixture.client.fail_for_item("222", TimeoutError("timeout"))
    run = service_fixture.service.collect(date(2026, 9, 24), date(2026, 9, 24))
    assert run.status is RunStatus.PARTIAL_FAILURE
    assert run.error_count == 1
    assert service_fixture.price_repository.count() > 0
    assert service_fixture.run_repository.get(run.run_id) == run
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/test_collection_service.py -v`  
Expected: FAIL because collection service does not exist.

- [ ] **Step 3: Implement collection workflow**

The service must log these lifecycle events:

```text
collection.started       run_id, start_date, end_date
catalog.collected        run_id, record_count, duration_ms
price.item.started       run_id, price_type, item_code, kind_code, rank_code
price.item.succeeded     run_id, record_count, duration_ms
price.item.failed        run_id, error_type, error, retryable
collection.completed     run_id, status, record_count, error_count, duration_ms
```

For each catalog entry, expand wholesale and retail rank codes separately. Catch errors at one `PriceQuery` boundary, append an error record to the run, and continue. Only catalog failure or storage failure marks the whole run failed.

- [ ] **Step 4: Test three-year chunking and locking**

```python
def test_three_year_backfill_is_split_without_gaps():
    ranges = KamisCollectionService.split_backfill_period(
        date(2023, 9, 25), date(2026, 9, 24)
    )
    assert all((part.end - part.start).days <= 365 for part in ranges)
    assert ranges[0].start == date(2023, 9, 25)
    assert ranges[-1].end == date(2026, 9, 24)
    assert all(
        left.end + timedelta(days=1) == right.start for left, right in pairwise(ranges)
    )


def test_second_collection_is_rejected_while_running(service_fixture):
    service_fixture.service.acquire_for_test()
    with pytest.raises(CollectionAlreadyRunning):
        service_fixture.service.collect(TODAY, TODAY)
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/services/test_collection_service.py -v
git add app/services/collection_service.py tests/services
git commit -m "feat: orchestrate KAMIS collection runs"
```

## Task 6: FastAPI Application and Routes

**Files:**
- Create: `app/core/container.py`
- Create: `app/api/__init__.py`
- Create: `app/api/dependencies.py`
- Create: `app/api/routes_health.py`
- Create: `app/api/routes_catalog.py`
- Create: `app/api/routes_prices.py`
- Create: `app/api/routes_collection.py`
- Create: `app/main.py`
- Test: `tests/api/test_routes.py`

**Interfaces:**
- Produces: `ApplicationContainer.build(settings) -> ApplicationContainer`
- Produces: `create_app(container: ApplicationContainer | None = None) -> FastAPI`
- HTTP: `GET /health`
- HTTP: `GET /api/v1/catalog`
- HTTP: `GET /api/v1/prices`
- HTTP: `POST /api/v1/collections/kamis`
- HTTP: `GET /api/v1/collections/{run_id}`

- [ ] **Step 1: Write failing route tests**

```python
def test_health_reports_service_and_data_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_filters_by_item_name(client, catalog_repository):
    catalog_repository.save_snapshot(CATALOG_ROWS, TODAY, "run-1")
    response = client.get("/api/v1/catalog", params={"item_name": "쌀"})
    assert response.status_code == 200
    assert response.json()["items"][0]["item_name"] == "쌀"


def test_concurrent_collection_returns_409(client, collection_service):
    collection_service.acquire_for_test()
    response = client.post(
        "/api/v1/collections/kamis",
        json={"start_date": "2026-09-24", "end_date": "2026-09-24"},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_routes.py -v`  
Expected: FAIL because the FastAPI app does not exist.

- [ ] **Step 3: Implement app factory and exception handlers**

```python
def create_app(container: ApplicationContainer | None = None) -> FastAPI:
    resolved = container or ApplicationContainer.build(Settings.from_env())
    app = FastAPI(title="KAMIS API", version="0.1.0")
    app.state.container = resolved
    app.include_router(health_router)
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(prices_router, prefix="/api/v1")
    app.include_router(collection_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app
```

Return paginated response objects containing `items`, `total`, `limit`, and `offset`. Validate date order and maximum page size 500. Map `CollectionAlreadyRunning` to 409, validation errors to 422, unknown run IDs to 404, and unexpected errors to 500 with a correlation ID. Log request completion with method, path, status_code, duration_ms, and correlation_id; do not log query-string secrets.

- [ ] **Step 4: Run route tests and commit**

```bash
python -m pytest tests/api/test_routes.py -v
git add app/core/container.py app/api app/main.py tests/api
git commit -m "feat: expose KAMIS collection through FastAPI"
```

## Task 7: CLI and Daily Scheduler

**Files:**
- Create: `app/cli.py`
- Create: `app/services/scheduler.py`
- Test: `tests/test_cli.py`
- Test: `tests/services/test_scheduler.py`

**Interfaces:**
- CLI: `python -m app.cli serve --host 127.0.0.1 --port 8000`
- CLI: `python -m app.cli collect-kamis --start YYYY-MM-DD --end YYYY-MM-DD`
- CLI: `python -m app.cli backfill-kamis --years 3`
- Produces: `DailyScheduler.start() -> None`, `DailyScheduler.shutdown() -> None`

- [ ] **Step 1: Write failing CLI exit-code test**

```python
def test_collect_command_returns_nonzero_on_failed_run(monkeypatch):
    monkeypatch.setattr(ApplicationContainer, "build", failed_container)
    assert main(["collect-kamis", "--start", "2026-09-24", "--end", "2026-09-24"]) == 1
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/services/test_scheduler.py -v`  
Expected: FAIL because CLI and scheduler do not exist.

- [ ] **Step 3: Implement argparse CLI and APScheduler adapter**

Use `BlockingScheduler(timezone=settings.timezone)` for the standalone scheduler command. Register one cron job with `max_instances=1`, `coalesce=True`, and `misfire_grace_time=3600`. CLI code logs `cli.command.started` and `cli.command.completed`; it never prints results.

- [ ] **Step 4: Add scheduler registration test**

```python
def test_scheduler_registers_single_daily_job(fake_scheduler, service, settings):
    scheduler = DailyScheduler(fake_scheduler, service, settings, app_logger)
    scheduler.start(paused=True)
    job = fake_scheduler.get_job("kamis-daily-collection")
    assert job.max_instances == 1
    assert str(job.trigger).startswith("cron[")
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/test_cli.py tests/services/test_scheduler.py -v
git add app/cli.py app/services/scheduler.py tests/test_cli.py tests/services/test_scheduler.py
git commit -m "feat: add KAMIS CLI and daily scheduler"
```

## Task 8: End-to-End Verification and Developer Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/dev/README.md`
- Create: `tests/integration/test_collection_to_api.py`

**Interfaces:**
- Validates the complete path from fake KAMIS response to CSV to FastAPI response.

- [ ] **Step 1: Write end-to-end test**

```python
def test_collection_results_are_queryable_from_api(integration_app, fake_kamis):
    run = integration_app.container.collection_service.collect(TODAY, TODAY)
    response = integration_app.client.get(
        "/api/v1/prices",
        params={"item_code": "111", "price_type": "retail"},
    )
    assert run.status is RunStatus.SUCCESS
    assert response.status_code == 200
    assert response.json()["items"][0]["item_name"] == "쌀"
```

- [ ] **Step 2: Verify RED before final wiring**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_collection_to_api.py -v`  
Expected: FAIL until test container wiring and repository paths are connected.

- [ ] **Step 3: Complete integration wiring and document commands**

README and development guide must include:

```powershell
.\.venv\Scripts\python.exe -m app.cli collect-kamis --start 2026-09-24 --end 2026-09-24
.\.venv\Scripts\python.exe -m app.cli backfill-kamis --years 3
.\.venv\Scripts\python.exe -m app.cli serve --host 127.0.0.1 --port 8000
```

Document Swagger UI at `http://127.0.0.1:8000/docs`, data directory layout, log event names, error investigation order, and credential rotation procedure.

- [ ] **Step 4: Run full verification**

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Expected: all commands exit 0 with no failed tests.

- [ ] **Step 5: Run opt-in live smoke test**

Run a single catalog request and one one-day price query using the configured `.env`. Log only action, status, duration, and record count. Confirm the log does not contain KAMIS_CERT_KEY or KAMIS_CERT_ID.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/dev/README.md tests/integration
git commit -m "docs: add backend operation and troubleshooting guide"
```

## Deferred Follow-up Plans

The following subsystems consume the interfaces above and should be planned separately after this backend is verified:

1. 네이버·쿠팡 적응형 상품 발견, 정책 검증, 상품 매칭과 15% 저가 이상치 계산
2. 원자재 선물·USD/KRW·KOSPI·KOSDAQ·미국 3대 지수 수집
3. 기준일 100, 변화율, Pearson·Spearman·시차·이동 상관 분석
4. 실제 사용자 대시보드와 검색 가능한 데이터 테이블
