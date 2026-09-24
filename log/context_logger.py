from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import ClassVar


class ContextLogger:
    """Small adapter that emits consistent, searchable key-value log messages."""

    _secret_keys: ClassVar[set[str]] = {
        "authorization",
        "cert_id",
        "cert_key",
        "kamis_cert_id",
        "kamis_cert_key",
        "password",
        "secret",
        "token",
    }

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _message(self, event: str, message: str, context: Mapping[str, object]) -> str:
        safe = {
            key: "***" if key.lower() in self._secret_keys else value
            for key, value in context.items()
        }
        fields = " ".join(f"{key}={safe[key]!s}" for key in sorted(safe))
        prefix = f"event={event} message={message!r}"
        return f"{prefix} {fields}" if fields else prefix

    def debug(self, event: str, message: str, **context: object) -> None:
        self._logger.debug(self._message(event, message, context))

    def info(self, event: str, message: str, **context: object) -> None:
        self._logger.info(self._message(event, message, context))

    def warning(self, event: str, message: str, **context: object) -> None:
        self._logger.warning(self._message(event, message, context))

    def error(self, event: str, message: str, **context: object) -> None:
        self._logger.error(self._message(event, message, context))

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
                {
                    **context,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
        )
