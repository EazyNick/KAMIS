from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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
    shopping_headless: bool = True

    @classmethod
    def from_env(cls, *, load_environment_file: bool = True) -> Settings:
        project_root = Path(__file__).resolve().parents[1]
        if load_environment_file:
            load_dotenv(project_root / ".env")
        data_dir_value = os.getenv("DATA_DIR")
        data_dir = Path(data_dir_value) if data_dir_value else project_root / "data"
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
                else None
            ),
            shopping_headless=os.getenv("SHOPPING_HEADLESS", "true").casefold()
            not in {"0", "false", "no"},
        )

    def require_kamis_credentials(self) -> tuple[str, str]:
        if not self.kamis_cert_key or not self.kamis_cert_id:
            raise ConfigurationError(
                "KAMIS_CERT_KEY and KAMIS_CERT_ID must be configured"
            )
        return self.kamis_cert_key, self.kamis_cert_id


settings = Settings.from_env()
