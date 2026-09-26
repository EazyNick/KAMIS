from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import ShoppingOffer
from app.infrastructure.codex_cli import CodexCliRunner
from app.infrastructure.coupang_agent_csv import ShoppingAgentCsvParser
from app.infrastructure.shopping_sources import HtmlShoppingSource
from log.logger import StructuredLogger


class ShoppingAgentSource:
    """Collect one bounded agent batch, then expose the cached source interface."""

    block_is_global = False
    _safe_run_id = re.compile(r"^[A-Za-z0-9_-]+$")

    def __init__(
        self,
        platform: str,
        skill_name: str,
        project_root: Path,
        run_root: Path,
        runner: CodexCliRunner,
        parser: ShoppingAgentCsvParser,
        fallback: HtmlShoppingSource,
        logger: StructuredLogger,
        *,
        timeout_seconds: float,
        minimum_delay_ms: int = 2000,
        max_offers_per_target: int = 8,
    ) -> None:
        self.platform = platform
        self._skill_name = skill_name
        self._project_root = project_root.resolve()
        self._run_root = run_root.resolve()
        self._runner = runner
        self._parser = parser
        self._fallback = fallback
        self._logger = logger
        self._timeout_seconds = timeout_seconds
        self._minimum_delay_ms = minimum_delay_ms
        self._max_offers_per_target = max_offers_per_target
        self._offers: dict[tuple[str, str], list[ShoppingOffer]] = {}
        self._errors: dict[tuple[str, str], Exception] = {}
        self._prepared_date: date | None = None

    def prepare(
        self,
        entries: list[ProductCatalogEntry],
        observed_date: date,
        run_id: str,
    ) -> None:
        if not entries:
            return
        if len(entries) > 10:
            raise ValueError(f"{self.platform} agent batch cannot exceed 10 targets")
        if not self._safe_run_id.fullmatch(run_id):
            raise ValueError("run_id contains unsupported path characters")
        self._offers = {}
        self._errors = {}
        self._prepared_date = observed_date
        catalog = {(entry.item_code, entry.kind_code): entry for entry in entries}
        run_dir = self._run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        schema_path = run_dir / "result-schema.json"
        result_path = run_dir / "agent-result.json"
        csv_path = run_dir / "offers.csv"
        manifest = self._manifest(entries, observed_date, run_id, run_dir, csv_path)
        self._atomic_json(manifest_path, manifest)
        self._atomic_json(schema_path, self._result_schema())

        failed_keys = set(catalog)
        try:
            result = self._runner.run(
                (
                    f"Use ${self._skill_name} to collect the manifest at "
                    f'"{manifest_path}". Execute its deterministic script exactly once '
                    "and return only the required final JSON status."
                ),
                schema_path,
                result_path,
                self._timeout_seconds,
            )
            if result.exit_code == 0:
                parsed = self._parser.parse(csv_path, manifest, catalog)
                self._offers.update(parsed.offers_by_key)
                failed_keys = set(parsed.failed_keys)
                self._logger.info(  # noqa: PLE1205 - custom structured logger
                    f"{self.platform}_agent.parsed",
                    f"{self.platform} agent CSV was parsed",
                    run_id=run_id,
                    target_count=len(entries),
                    failed_count=len(failed_keys),
                    invalid_row_count=parsed.invalid_row_count,
                    csv_path=csv_path,
                )
            else:
                self._logger.error(  # noqa: PLE1205 - custom structured logger
                    f"{self.platform}_agent.failed",
                    f"{self.platform} Codex agent returned a non-zero exit code",
                    run_id=run_id,
                    exit_code=result.exit_code,
                    target_count=len(entries),
                )
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205
                f"{self.platform}_agent.failed",
                f"{self.platform} agent failed; Playwright fallback will run",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                run_id=run_id,
                target_count=len(entries),
            )

        for key in failed_keys:
            entry = catalog[key]
            try:
                self._offers.setdefault(key, []).extend(
                    self._fallback.search(entry, observed_date)
                )
            except Exception as error:  # noqa: BLE001 - per-key source boundary
                self._errors[key] = error
                self._offers.setdefault(key, [])

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
        key = (entry.item_code, entry.kind_code)
        if self._prepared_date != observed_date or key not in self._offers:
            raise RuntimeError(f"{self.platform} agent source was not prepared for {key}")
        if key in self._errors:
            raise self._errors[key]
        return list(self._offers[key])

    def _manifest(
        self,
        entries: list[ProductCatalogEntry],
        observed_date: date,
        run_id: str,
        run_dir: Path,
        csv_path: Path,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "observed_date": observed_date.isoformat(),
            "run_dir": str(run_dir),
            "output_csv": str(csv_path),
            "minimum_delay_ms": self._minimum_delay_ms,
            "max_offers_per_target": self._max_offers_per_target,
            "targets": [
                {
                    "item_code": entry.item_code,
                    "kind_code": entry.kind_code,
                    "item_name": entry.item_name,
                    "variety": entry.variety,
                    "comparison_unit": (
                        f"{entry.retail_unit_size or ''}{entry.retail_unit or ''}"
                    ),
                    "query": f"{entry.item_name} {entry.variety}".strip(),
                }
                for entry in entries
            ],
        }

    @staticmethod
    def _result_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "target_count",
                "completed_count",
                "failed_keys",
                "csv_path",
            ],
            "properties": {
                "status": {"enum": ["success", "partial", "failed"]},
                "target_count": {"type": "integer", "minimum": 0},
                "completed_count": {"type": "integer", "minimum": 0},
                "failed_keys": {"type": "array", "items": {"type": "string"}},
                "csv_path": {"type": "string"},
            },
        }

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class CoupangAgentSource(ShoppingAgentSource):
    """Backward-compatible Coupang agent source."""

    def __init__(
        self,
        project_root: Path,
        run_root: Path,
        runner: CodexCliRunner,
        parser: ShoppingAgentCsvParser,
        fallback: HtmlShoppingSource,
        logger: StructuredLogger,
        *,
        timeout_seconds: float,
        minimum_delay_ms: int = 2000,
        max_offers_per_target: int = 8,
    ) -> None:
        super().__init__(
            "coupang",
            "coupang-ui-collector",
            project_root,
            run_root,
            runner,
            parser,
            fallback,
            logger,
            timeout_seconds=timeout_seconds,
            minimum_delay_ms=minimum_delay_ms,
            max_offers_per_target=max_offers_per_target,
        )
