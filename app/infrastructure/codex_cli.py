from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.errors import CodexCliTimeout
from log import StructuredLogger

ProcessRunner = Callable[..., Any]
ExecutableResolver = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class CodexCliResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    last_message_path: Path


class CodexCliRunner:
    """Run a bounded, non-interactive Codex process from the repository root."""

    _environment_secret = re.compile(
        r"(?i)\b(CODEX_API_KEY|OPENAI_API_KEY|KAMIS_CERT_KEY)=([^\s]+)"
    )
    _json_secret = re.compile(
        r'(?i)("(?:access_token|refresh_token)"\s*:\s*)"[^"]*"'
    )

    def __init__(
        self,
        project_root: Path,
        executable: str,
        logger: StructuredLogger,
        *,
        process_runner: ProcessRunner = subprocess.run,
        executable_resolver: ExecutableResolver = shutil.which,
        sandbox_mode: str = "workspace-write",
    ) -> None:
        self._project_root = project_root.resolve()
        self._executable = executable
        self._logger = logger
        self._process_runner = process_runner
        self._executable_resolver = executable_resolver
        self._sandbox_mode = sandbox_mode

    def run(
        self,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        timeout_seconds: float,
    ) -> CodexCliResult:
        resolved_executable = self._executable_resolver(self._executable)
        command = [
            resolved_executable or self._executable,
            "exec",
            "--ephemeral",
            "--sandbox",
            self._sandbox_mode,
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            prompt,
        ]
        started = perf_counter()
        self._logger.info(  # noqa: PLE1205 - custom structured logger
            "codex_cli.started",
            "Codex CLI process started",
            executable=self._executable,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        )
        try:
            completed = self._process_runner(
                command,
                cwd=self._project_root,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            duration_ms = round((perf_counter() - started) * 1000)
            self._logger.exception(  # noqa: PLE1205
                "codex_cli.timeout",
                "Codex CLI process exceeded its deadline",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                duration_ms=duration_ms,
                output_path=output_path,
                timeout_seconds=timeout_seconds,
            )
            raise CodexCliTimeout(timeout_seconds) from error

        duration_ms = round((perf_counter() - started) * 1000)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        log_method = self._logger.info if completed.returncode == 0 else self._logger.error
        log_method(
            "codex_cli.completed",
            "Codex CLI process completed",
            duration_ms=duration_ms,
            exit_code=completed.returncode,
            output_path=output_path,
            stderr=self._safe_log_text(stderr),
        )
        return CodexCliResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            last_message_path=output_path,
        )

    @classmethod
    def _safe_log_text(cls, value: str) -> str:
        redacted = cls._environment_secret.sub(r"\1=***", value)
        redacted = cls._json_secret.sub(r'\1"***"', redacted)
        return redacted[:4000]
