# Coupang Codex Agent Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect the ten representative Coupang items through a repository-scoped Codex skill and the user's ordinary Chrome session, validate the generated CSV, and retain Playwright as a per-item fallback.

**Architecture:** FastAPI launches one non-interactive `codex exec` batch through a typed subprocess runner. The explicitly invoked repository skill runs a deterministic Windows UI Automation PowerShell script that writes a run-scoped raw CSV; Python validates and converts rows into `ShoppingOffer` objects, then the existing pricing and repository pipeline persists the results. An optional batch-source hook lets Coupang run once for all missing targets while preserving the existing per-item shopping-source interface for Naver and Playwright.

**Tech Stack:** Python 3.11, FastAPI, pytest, Codex CLI, PowerShell 5+, Windows UI Automation, CSV repositories

**Spec:** `docs/superpowers/specs/2026-09-26-coupang-codex-agent-collector-design.md`

## Global Constraints

- Preserve the existing Playwright Coupang collector and direct entrypoint as the fallback implementation.
- Invoke Codex once per batch, not once per item.
- Use the ordinary Chrome UI through Windows accessibility controls; do not bypass access controls or automate account login.
- Treat only `available` and confirmed `unavailable` rows as complete; retry `blocked` and `collection_failed` rows.
- Never log Codex credentials, cookies, full environment variables, or unbounded stderr.
- Use `log.logger.StructuredLogger`; do not add `print` calls to application code.
- Preserve the uncommitted user change in `app/web/dashboard.html`.
- Write tests before production code and observe each new test fail for the intended missing behavior.

## Review Focus

- Locked desktop or missing accessibility search field must fail clearly and trigger Playwright only for unresolved Coupang items.
- A malformed or path-escaping manifest/CSV path must be rejected before GUI interaction or repository writes.
- Different package sizes must be normalized to the KAMIS retail unit; non-convertible units must be excluded.
- Partial same-day data must invoke Codex only for missing Coupang keys and must not recollect completed Naver keys.
- Codex timeout or non-zero exit must capture bounded diagnostics, terminate cleanly, and preserve successful existing rows.

---

### Task 1: Define and validate the repository skill

**Files:**
- Create: `.agents/skills/coupang-ui-collector/SKILL.md`
- Create: `.agents/skills/coupang-ui-collector/agents/openai.yaml`
- Create: `.agents/skills/coupang-ui-collector/references/csv-schema.md`
- Create: `.agents/skills/coupang-ui-collector/scripts/collect_coupang_ui.ps1`
- Create: `tests/skills/test_coupang_ui_skill.py`

**Interfaces:**
- Consumes: JSON manifest path supplied as `-ManifestPath <absolute-path>`.
- Produces: raw CSV at the manifest's `output_csv` and a final JSON status containing `status`, `target_count`, `completed_count`, `failed_keys`, and `csv_path`.

- [ ] **Step 1: Establish the RED baseline for the skill**

Run a read-only, ephemeral Codex CLI probe before the skill exists:

```powershell
codex exec --ephemeral --sandbox read-only "Use `$coupang-ui-collector to validate a manifest. Do not browse or change files. Report whether the skill exists."
```

Expected: the agent reports that `$coupang-ui-collector` is unavailable. Save the bounded final message in the implementation log; do not commit rollout data.

- [ ] **Step 2: Write failing repository skill tests**

```python
def test_coupang_skill_declares_explicit_manifest_and_csv_contract() -> None:
    root = Path('.agents/skills/coupang-ui-collector')
    assert (root / 'SKILL.md').is_file()
    assert (root / 'scripts/collect_coupang_ui.ps1').is_file()
    assert '-ManifestPath' in (root / 'SKILL.md').read_text(encoding='utf-8')
    assert 'raw_accessible_name' in (
        root / 'references/csv-schema.md'
    ).read_text(encoding='utf-8')


def test_ui_script_uses_accessibility_value_pattern_not_screen_coordinates() -> None:
    script = Path(
        '.agents/skills/coupang-ui-collector/scripts/collect_coupang_ui.ps1'
    ).read_text(encoding='utf-8')
    assert 'ValuePattern' in script
    assert 'SetCursorPos' not in script
    assert 'mouse_event' not in script
```

- [ ] **Step 3: Run the tests and observe the missing-skill failure**

Run: `.venv\Scripts\python.exe -m pytest tests/skills/test_coupang_ui_skill.py -q`

Expected: FAIL because the skill files do not exist.

- [ ] **Step 4: Create the minimal skill and deterministic script**

The skill must instruct Codex to run exactly:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
  .agents\skills\coupang-ui-collector\scripts\collect_coupang_ui.ps1 `
  -ManifestPath <manifest-path>
```

The script must:

```powershell
param([Parameter(Mandatory=$true)][string]$ManifestPath)

# Resolve and validate manifest/output paths below the configured run directory.
# Open https://www.coupang.com/ only when no usable Coupang Chrome document exists.
# Find the Edit element whose accessible name is "쿠팡 상품 검색".
# Set each query with ValuePattern, send Enter, and wait for the document title/result
# marker to change without fixed coordinate clicks.
# Emit one CSV row per product ListItem and atomically move the temporary CSV.
```

Set `policy.allow_implicit_invocation: false` in `agents/openai.yaml` so the server prompt must mention the skill explicitly.

- [ ] **Step 5: Validate the skill and rerun tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/skills/test_coupang_ui_skill.py -q
python C:\Users\kkkyg\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\coupang-ui-collector
```

Expected: PASS and `Skill is valid!`.

- [ ] **Step 6: Forward-test explicit discovery**

Run:

```powershell
codex exec --ephemeral --sandbox read-only "Use `$coupang-ui-collector. Do not execute its script. State its required input and output contract."
```

Expected: the final answer names the JSON manifest and raw CSV contract without attempting a live collection.

- [ ] **Step 7: Commit the skill**

```powershell
git add .agents/skills/coupang-ui-collector tests/skills/test_coupang_ui_skill.py
git commit -m "feat: add coupang UI collection skill"
```

### Task 2: Add typed Codex CLI execution and configuration

**Files:**
- Create: `app/infrastructure/codex_cli.py`
- Modify: `config/server_config.py`
- Modify: `.env.example`
- Create: `tests/infrastructure/test_codex_cli.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `CodexCliRunner.run(prompt, schema_path, output_path, timeout_seconds) -> CodexCliResult`.
- `CodexCliResult` fields: `exit_code`, `stdout`, `stderr`, `duration_ms`, `last_message_path`.
- New settings: `coupang_agent_enabled`, `codex_executable`, `coupang_agent_timeout_seconds`, `coupang_agent_run_dir`.

- [ ] **Step 1: Write failing runner tests**

```python
def test_codex_runner_uses_argument_list_and_repository_workdir(tmp_path: Path) -> None:
    process = RecordingProcess(returncode=0)
    runner = CodexCliRunner(tmp_path, 'codex', app_logger, process_runner=process)
    result = runner.run('Use $coupang-ui-collector', tmp_path/'schema.json', tmp_path/'out.json', 30)
    assert process.command[:3] == ['codex', 'exec', '--ephemeral']
    assert '--output-schema' in process.command
    assert process.cwd == tmp_path
    assert result.exit_code == 0


def test_codex_runner_reports_timeout_without_secrets(tmp_path: Path) -> None:
    runner = CodexCliRunner(tmp_path, 'codex', app_logger, process_runner=TimeoutProcess())
    with pytest.raises(CodexCliTimeout):
        runner.run('prompt', tmp_path/'schema.json', tmp_path/'out.json', 1)
```

- [ ] **Step 2: Run targeted tests and observe import failure**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_codex_cli.py tests/test_config.py -q`

Expected: FAIL because `app.infrastructure.codex_cli` and agent settings do not exist.

- [ ] **Step 3: Implement the minimal runner and settings**

```python
@dataclass(frozen=True, slots=True)
class CodexCliResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    last_message_path: Path


class CodexCliRunner:
    def run(
        self,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        timeout_seconds: float,
    ) -> CodexCliResult:
        command = [
            self._executable,
            'exec',
            '--ephemeral',
            '--sandbox',
            'workspace-write',
            '--output-schema',
            str(schema_path),
            '-o',
            str(output_path),
            prompt,
        ]
        started = perf_counter()
        completed = self._process_runner(
            command,
            cwd=self._project_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CodexCliResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
            round((perf_counter() - started) * 1000),
            output_path,
        )
```

Inject `subprocess.run` as the default process runner and never pass `shell=True`. Convert `subprocess.TimeoutExpired` into `CodexCliTimeout`. Bound logged stderr to 4,000 characters and redact values following `CODEX_API_KEY=`, `OPENAI_API_KEY=`, `KAMIS_CERT_KEY=`, and JSON fields named `access_token` or `refresh_token`.

Add defaults:

```dotenv
COUPANG_AGENT_ENABLED=true
CODEX_EXECUTABLE=codex
COUPANG_AGENT_TIMEOUT_SECONDS=600
COUPANG_AGENT_RUN_DIR=data/runs/coupang-agent
```

- [ ] **Step 4: Run runner and config tests**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_codex_cli.py tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the runner**

```powershell
git add app/infrastructure/codex_cli.py config/server_config.py .env.example tests/infrastructure/test_codex_cli.py tests/test_config.py
git commit -m "feat: add Codex CLI batch runner"
```

### Task 3: Parse and validate the agent CSV

**Files:**
- Create: `app/infrastructure/coupang_agent_csv.py`
- Create: `tests/infrastructure/test_coupang_agent_csv.py`
- Create: `tests/fixtures/coupang_agent_offers.csv`

**Interfaces:**
- Produces: `CoupangAgentCsvParser.parse(path, manifest, catalog_by_key) -> CoupangCsvResult`.
- `CoupangCsvResult` fields: `offers_by_key`, `failed_keys`, `invalid_row_count`, `errors`.
- Converts package quantity into multiples of the catalog retail unit before constructing `ShoppingOffer`.

- [ ] **Step 1: Write failing validation and normalization tests**

```python
def test_parser_normalizes_rice_10kg_to_one_kamis_retail_unit(tmp_path: Path) -> None:
    result = parser.parse(csv_with(title='국내산 쌀, 10kg, 1개', displayed_price='34900', quantity='10', unit='kg'), manifest, catalog)
    offer = result.offers_by_key[('111', '10')][0]
    assert offer.quantity == Decimal('1')
    assert offer.unit == 'kamis_retail_unit'
    assert offer.unit_price == Decimal('34900')


def test_parser_rejects_seedling_and_nonconvertible_apple_weight(tmp_path: Path) -> None:
    result = parser.parse(csv_with_rows([
        row('211', '03', '가을 배추 모종 15개', '9220', '15', '개'),
        row('411', '05', '후지 사과 5kg', '25000', '5', 'kg'),
    ]), manifest, catalog)
    assert result.offers_by_key[('211', '03')][0].match_status is MatchStatus.REJECTED
    assert result.offers_by_key[('411', '05')][0].match_status is MatchStatus.REJECTED


def test_parser_rejects_manifest_mismatch_and_csv_formula(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError):
        parser.parse(csv_with(title='=HYPERLINK("bad")'), manifest, catalog)
```

- [ ] **Step 2: Run parser tests and observe import failure**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_coupang_agent_csv.py -q`

Expected: FAIL because the parser does not exist.

- [ ] **Step 3: Implement schema, matching, unit conversion, and deduplication**

Implement strict row validation, Korean unit aliases, target-unit conversion, forbidden product keywords (`모종`, `씨앗`, `냉동`, `다진`, `주스용`), duplicate product IDs, public/all-member discount handling, and shipping certainty. Keep rejected offers with `exclusion_reason` so decisions remain auditable.

```python
@dataclass(frozen=True, slots=True)
class CoupangCsvResult:
    offers_by_key: dict[tuple[str, str], list[ShoppingOffer]]
    failed_keys: frozenset[tuple[str, str]]
    invalid_row_count: int
    errors: Sequence[str]


def target_quantity(
    offered_quantity: Decimal,
    offered_unit: str,
    entry: ProductCatalogEntry,
) -> Decimal:
    target_size = Decimal(entry.retail_unit_size)
    source_size, source_unit = normalize_measure(offered_quantity, offered_unit)
    normalized_target_size, target_unit = normalize_measure(
        target_size, entry.retail_unit
    )
    if source_unit != target_unit:
        raise DataValidationError('offer unit cannot convert to KAMIS retail unit')
    return source_size / normalized_target_size
```

Reject a row before conversion when its manifest date/run/key differs, any required cell starts with a spreadsheet formula prefix, a decimal is negative, or its key is not in `catalog_by_key`. Use `csv.DictReader` with `utf-8-sig`, deduplicate by `(item_code, kind_code, product_id)`, and convert restricted discounts to the non-member displayed price only when that price is separately present; otherwise reject the row as `restricted_discount_only`.

- [ ] **Step 4: Run parser and domain pricing tests**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_coupang_agent_csv.py tests/domain/test_online_pricing.py -q`

Expected: PASS.

- [ ] **Step 5: Commit CSV validation**

```powershell
git add app/infrastructure/coupang_agent_csv.py tests/infrastructure/test_coupang_agent_csv.py tests/fixtures/coupang_agent_offers.csv
git commit -m "feat: validate coupang agent CSV data"
```

### Task 4: Add one-shot agent batch source with Playwright fallback

**Files:**
- Create: `app/infrastructure/coupang_agent_source.py`
- Modify: `app/services/online_collection.py`
- Modify: `app/infrastructure/online_repository.py`
- Modify: `app/core/container.py`
- Create: `tests/infrastructure/test_coupang_agent_source.py`
- Modify: `tests/services/test_online_collection.py`
- Modify: `tests/infrastructure/test_online_repository.py`

**Interfaces:**
- Adds optional `prepare(entries, observed_date, run_id) -> None` behavior to batch-capable sources.
- `CoupangAgentSource.search(entry, observed_date) -> list[ShoppingOffer]` returns cached agent or fallback results.
- Repository produces `completed_platform_keys(observed_date: date) -> set[tuple[str, str, str]]` and `summary_for_date(observed_date: date, platform: str, item_code: str, kind_code: str) -> dict[str, str] | None`.

- [ ] **Step 1: Write failing one-shot and partial-fallback tests**

```python
def test_agent_source_invokes_codex_once_for_ten_entries() -> None:
    source.prepare(TEN_ENTRIES, TODAY, 'run-1')
    for entry in TEN_ENTRIES:
        source.search(entry, TODAY)
    assert runner.calls == 1


def test_agent_source_falls_back_only_for_failed_keys() -> None:
    source.prepare(TEN_ENTRIES, TODAY, 'run-1')
    assert fallback.searched_keys == {('211', '03'), ('411', '05')}


def test_online_collection_skips_completed_platform_item_keys(tmp_path: Path) -> None:
    repository.save_completed('naver', '111', '10', TODAY)
    service.collect(catalog, TODAY, 'run-2')
    assert ('naver', '111', '10') not in searched
```

- [ ] **Step 2: Run targeted tests and observe failures**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_coupang_agent_source.py tests/services/test_online_collection.py tests/infrastructure/test_online_repository.py -q`

Expected: FAIL because batch preparation and platform-key completion queries do not exist.

- [ ] **Step 3: Implement the batch source and completion-aware service**

The source must create a run directory, atomically write the manifest and JSON schema, call the runner once, parse the CSV, and call the existing `CoupangShoppingSource` only for failed or missing keys. `OnlineCollectionService` must call `prepare` once with only pending keys for that platform and reuse stored summaries for already-completed keys when recomputing combined averages.

Use this optional protocol and preparation sequence:

```python
class BatchShoppingSourceProtocol(ShoppingSourceProtocol, Protocol):
    def prepare(
        self,
        entries: list[ProductCatalogEntry],
        observed_date: date,
        run_id: str,
    ) -> None:
        raise NotImplementedError


for source in self._sources:
    pending = [
        entry
        for entry in selected_catalog
        if (source.platform, entry.item_code, entry.kind_code) not in completed
    ]
    prepare = getattr(source, 'prepare', None)
    if prepare is not None and pending:
        prepare(pending, observed_date, run_id)
```

The concrete `CoupangAgentSource.prepare` writes its manifest with `Path.replace`, calls `CodexCliRunner.run`, parses valid rows, and then iterates only `failed_keys` through the injected Playwright source. Cache both returned offers and per-key exceptions so `search` remains compatible with the existing source-isolation logic.

- [ ] **Step 4: Run batch, repository, and daily pipeline tests**

Run: `.venv\Scripts\python.exe -m pytest tests/infrastructure/test_coupang_agent_source.py tests/services/test_online_collection.py tests/infrastructure/test_online_repository.py tests/services/test_daily_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit batch integration**

```powershell
git add app/infrastructure/coupang_agent_source.py app/services/online_collection.py app/infrastructure/online_repository.py app/core/container.py tests/infrastructure/test_coupang_agent_source.py tests/services/test_online_collection.py tests/infrastructure/test_online_repository.py
git commit -m "feat: collect coupang through Codex agent first"
```

### Task 5: Add manual FastAPI and Python entrypoints

**Files:**
- Create: `app/collectors/coupang_agent.py`
- Modify: `app/api/routes_collection.py`
- Modify: `app/core/container.py`
- Modify: `tests/collectors/test_entrypoints.py`
- Modify: `tests/api/test_routes.py`

**Interfaces:**
- Produces: `run_coupang_agent(observed_date, target=None) -> OnlineCollectionResult`.
- Adds: `POST /api/v1/collections/coupang-agent` with `observed_date` and optional `item`.

- [ ] **Step 1: Write failing CLI and API tests**

```python
def test_coupang_agent_entrypoint_accepts_date_and_item(monkeypatch) -> None:
    assert coupang_agent.main(['--date', '2026-09-26', '--item', '111:10']) == 0


def test_coupang_agent_endpoint_returns_collection_result(client) -> None:
    response = client.post('/api/v1/collections/coupang-agent', json={
        'observed_date': '2026-09-26', 'item': '111:10'
    })
    assert response.status_code == 200
    assert response.json()['target_count'] == 1
```

- [ ] **Step 2: Run entrypoint tests and observe missing route/module failures**

Run: `.venv\Scripts\python.exe -m pytest tests/collectors/test_entrypoints.py tests/api/test_routes.py -q`

Expected: FAIL because the module and route do not exist.

- [ ] **Step 3: Implement shared service entrypoints**

Use the container's configured agent source/service rather than duplicating construction. Return HTTP 409 for an active collection and HTTP 503 when agent collection is disabled or unavailable. Include `if __name__ == '__main__': raise SystemExit(main())`.

- [ ] **Step 4: Run API and entrypoint tests**

Run: `.venv\Scripts\python.exe -m pytest tests/collectors/test_entrypoints.py tests/api/test_routes.py tests/test_direct_entrypoint.py -q`

Expected: PASS.

- [ ] **Step 5: Commit entrypoints**

```powershell
git add app/collectors/coupang_agent.py app/api/routes_collection.py app/core/container.py tests/collectors/test_entrypoints.py tests/api/test_routes.py
git commit -m "feat: expose coupang agent collection controls"
```

### Task 6: Document, verify, and live-test the complete workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/dev/README.md`
- Create: `tests/integration/test_coupang_agent_pipeline.py`

**Interfaces:**
- Documents clone/install/authentication, desktop prerequisites, server startup behavior, manual command, endpoint, logs, CSV paths, and fallback behavior.

- [ ] **Step 1: Write a failing integration test for missing-only behavior**

```python
def test_pipeline_collects_only_missing_coupang_rows_and_persists_csv(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    repository.save_daily(
        [],
        [PlatformPriceSummary('coupang', '111', '10', Decimal('33000'), 5, 5, (), ())],
        TODAY,
        'seed-run',
    )
    runner = FixtureCodexRunner('tests/fixtures/coupang_agent_offers.csv')
    source = build_agent_source(tmp_path, repository, runner)
    service = OnlineCollectionService(
        [source], repository, OnlinePriceCalculator(), app_logger,
        target_keys=set(DEFAULT_ONLINE_TARGET_KEYS),
    )

    result = service.collect(TEN_CATALOG_ENTRIES, TODAY, 'run-2', include_combined=False)

    assert runner.calls == 1
    assert runner.manifest_target_count == 9
    assert result.error_count == 0
    assert len({
        (row['item_code'], row['kind_code'])
        for row in repository.summaries_for_date(TODAY)
        if row['platform'] == 'coupang'
    }) == 10
```

- [ ] **Step 2: Run the integration test and observe the incomplete documentation/integration failure**

Run: `.venv\Scripts\python.exe -m pytest tests/integration/test_coupang_agent_pipeline.py -q`

Expected: FAIL until the assembled container and fixture paths match the complete workflow.

- [ ] **Step 3: Complete integration wiring and documentation**

README commands must include:

```powershell
codex login
.\.venv\Scripts\python.exe -m app.collectors.coupang_agent --date 2026-09-26 --item 111:10
.\.venv\Scripts\python.exe app\main.py
```

Document that Windows must remain logged in and unlocked, ordinary Chrome is used, Playwright remains the fallback, Codex usage is incurred, and raw agent CSVs are stored under `data/runs/coupang-agent/<run-id>/`.

- [ ] **Step 4: Run static and complete automated verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check app tests config log
.venv\Scripts\python.exe -m mypy app config log
git diff --check
```

Expected: all tests pass; lint, type checks, and whitespace checks pass. If a configured tool is unavailable, record the exact command and error instead of claiming it passed.

- [ ] **Step 5: Run one live Codex/Chrome collection**

Run one target first:

```powershell
.\.venv\Scripts\python.exe -m app.collectors.coupang_agent --date 2026-09-26 --item 111:10
```

Verify from the resulting CSV and normalized rows:

- query started from the Coupang homepage search input;
- at least five raw candidates were captured when the page exposed them;
- wrong sizes and restricted discounts have explicit exclusion reasons;
- the stored 10 kg rice unit price equals the package comparison price, not a per-kilogram mismatch;
- structured logs identify Codex execution, CSV validation, and fallback usage.

Then run the missing-target batch only if the one-target result is valid.

- [ ] **Step 6: Commit documentation and integration coverage**

```powershell
git add README.md docs/dev/README.md tests/integration/test_coupang_agent_pipeline.py
git commit -m "docs: explain coupang agent collection workflow"
```

- [ ] **Step 7: Review commits and push**

```powershell
git status --short
git log --oneline -8
git push
```

Expected: only the pre-existing `app/web/dashboard.html` user modification remains uncommitted; all feature commits are pushed.
