from app.infrastructure.coupang_agent_csv import (
    CoupangCsvResult,
    ShoppingAgentCsvParser,
)


class NaverAgentCsvParser(ShoppingAgentCsvParser):
    """Validate Naver UI-agent rows using the shared shopping policy."""

    def __init__(self) -> None:
        super().__init__("naver")


__all__ = ["CoupangCsvResult", "NaverAgentCsvParser"]
