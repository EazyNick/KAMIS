from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_ONLINE_TARGET_KEYS = (
    ("111", "10"),  # 쌀 / 10kg
    ("152", "00"),  # 감자
    ("211", "03"),  # 배추 / 가을
    ("231", "03"),  # 무 / 가을
    ("245", "00"),  # 양파
    ("258", "01"),  # 깐마늘
    ("225", "00"),  # 토마토
    ("411", "05"),  # 사과 / 후지
    ("412", "01"),  # 배 / 신고
    ("611", "05"),  # 고등어 / 국산 신선·냉장
)


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


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
    shopping_user_data_dir: Path | None = None
    shopping_headless: bool = False
    shopping_browser_channel: str | None = "chrome"
    shopping_request_interval_seconds: float = 5.0
    coupang_agent_enabled: bool = True
    codex_executable: str = "codex"
    codex_sandbox_mode: str = "danger-full-access"
    coupang_agent_timeout_seconds: float = 600.0
    coupang_agent_run_dir: Path = Path("data/runs/coupang-agent")
    online_target_keys: frozenset[tuple[str, str]] = frozenset(
        DEFAULT_ONLINE_TARGET_KEYS
    )

    @classmethod
    def from_env(cls, *, load_environment_file: bool = True) -> Settings:
        project_root = Path(__file__).resolve().parents[1]
        if load_environment_file:
            load_dotenv(project_root / ".env")
        data_dir_value = os.getenv("DATA_DIR")
        data_dir = Path(data_dir_value) if data_dir_value else project_root / "data"
        online_target_keys = cls._parse_online_targets(os.getenv("ONLINE_TARGETS", ""))
        return cls(
            project_root=project_root,
            data_dir=data_dir.resolve(),
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
            shopping_user_data_dir=(
                Path(value).resolve()
                if (value := os.getenv("SHOPPING_USER_DATA_DIR"))
                else (data_dir / "browser-profile").resolve()
            ),
            shopping_headless=os.getenv("SHOPPING_HEADLESS", "false").casefold()
            not in {"0", "false", "no"},
            shopping_browser_channel=(
                value
                if (value := os.getenv("SHOPPING_BROWSER_CHANNEL", "chrome").strip())
                else None
            ),
            shopping_request_interval_seconds=float(
                os.getenv("SHOPPING_REQUEST_INTERVAL_SECONDS", "5")
            ),
            coupang_agent_enabled=os.getenv(
                "COUPANG_AGENT_ENABLED", "true"
            ).casefold()
            not in {"0", "false", "no"},
            codex_executable=os.getenv("CODEX_EXECUTABLE", "codex").strip()
            or "codex",
            codex_sandbox_mode=os.getenv(
                "CODEX_SANDBOX_MODE", "danger-full-access"
            ).strip(),
            coupang_agent_timeout_seconds=float(
                os.getenv("COUPANG_AGENT_TIMEOUT_SECONDS", "600")
            ),
            coupang_agent_run_dir=(
                Path(value) if Path(value).is_absolute() else project_root / value
            ).resolve()
            if (value := os.getenv("COUPANG_AGENT_RUN_DIR", "data/runs/coupang-agent"))
            else (project_root / "data/runs/coupang-agent").resolve(),
            online_target_keys=online_target_keys,
        )

    @staticmethod
    def _parse_online_targets(value: str) -> frozenset[tuple[str, str]]:
        if not value.strip():
            return frozenset(DEFAULT_ONLINE_TARGET_KEYS)
        try:
            targets = frozenset(
                tuple(part.strip() for part in token.split(":"))
                for token in value.split(",")
            )
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                "ONLINE_TARGETS must use item_code:kind_code pairs"
            ) from error
        if (
            len(targets) != 10
            or any(len(pair) != 2 for pair in targets)
            or any(not code.isdigit() for pair in targets for code in pair)
        ):
            raise ConfigurationError(
                "ONLINE_TARGETS must contain exactly 10 unique numeric "
                "item_code:kind_code pairs"
            )
        return frozenset((pair[0], pair[1]) for pair in targets)

    def require_kamis_credentials(self) -> tuple[str, str]:
        if not self.kamis_cert_key or not self.kamis_cert_id:
            raise ConfigurationError(
                "KAMIS_CERT_KEY and KAMIS_CERT_ID must be configured"
            )
        return self.kamis_cert_key, self.kamis_cert_id


settings = Settings.from_env()
