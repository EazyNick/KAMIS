from pathlib import Path

from app.infrastructure.codex_cli import CodexCliRunner
from app.infrastructure.coupang_agent_csv import ShoppingAgentCsvParser
from app.infrastructure.coupang_agent_source import ShoppingAgentSource
from app.infrastructure.shopping_sources import HtmlShoppingSource
from log.logger import StructuredLogger


class NaverAgentSource(ShoppingAgentSource):
    """Run the Naver UI skill once and cache per-item results."""

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
            "naver",
            "naver-ui-collector",
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
