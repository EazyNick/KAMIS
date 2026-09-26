from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import CodexCliTimeout
from app.infrastructure.codex_cli import CodexCliRunner
from log import app_logger


class RecordingProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.command: list[str] = []
        self.cwd: Path | None = None
        self.kwargs: dict[str, object] = {}

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        self.command = command
        self.cwd = kwargs["cwd"]  # type: ignore[assignment]
        self.kwargs = kwargs
        return SimpleNamespace(returncode=self.returncode, stdout="ok", stderr="")


class TimeoutProcess:
    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])


def test_codex_runner_uses_argument_list_and_repository_workdir(
    tmp_path: Path,
) -> None:
    process = RecordingProcess(returncode=0)
    runner = CodexCliRunner(
        tmp_path,
        "codex",
        app_logger,
        process_runner=process,
        executable_resolver=lambda value: value,
    )

    result = runner.run(
        "Use $coupang-ui-collector",
        tmp_path / "schema.json",
        tmp_path / "out.json",
        30,
    )

    assert process.command[:3] == ["codex", "exec", "--ephemeral"]
    assert "--output-schema" in process.command
    assert "workspace-write" in process.command
    assert process.cwd == tmp_path
    assert process.kwargs.get("shell") is None
    assert process.kwargs["encoding"] == "utf-8"
    assert process.kwargs["errors"] == "replace"
    assert result.exit_code == 0
    assert result.last_message_path == tmp_path / "out.json"


def test_codex_runner_reports_timeout_without_secrets(tmp_path: Path) -> None:
    runner = CodexCliRunner(
        tmp_path,
        "codex",
        app_logger,
        process_runner=TimeoutProcess(),
        executable_resolver=lambda value: value,
    )

    with pytest.raises(CodexCliTimeout, match="1"):
        runner.run("prompt", tmp_path / "schema.json", tmp_path / "out.json", 1)


def test_codex_runner_redacts_and_bounds_logged_stderr(tmp_path: Path) -> None:
    class RecordingLogger:
        def __init__(self) -> None:
            self.context: dict[str, object] = {}

        def info(self, event: str, message: str, **context: object) -> None:
            self.context = context

        def error(self, event: str, message: str, **context: object) -> None:
            self.context = context

        def exception(
            self,
            event: str,
            message: str,
            error: BaseException,
            **context: object,
        ) -> None:
            self.context = context

    logger = RecordingLogger()
    process = RecordingProcess(returncode=1)

    def secret_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        process(command, **kwargs)
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "OPENAI_API_KEY=secret "
                '{"access_token":"token-value"}'
                + "x" * 5000
            ),
        )

    result = CodexCliRunner(
        tmp_path,
        "codex",
        logger,  # type: ignore[arg-type]
        process_runner=secret_process,
        executable_resolver=lambda value: value,
    ).run("prompt", tmp_path / "schema.json", tmp_path / "out.json", 30)

    assert result.exit_code == 1
    logged_stderr = str(logger.context["stderr"])
    assert "secret" not in logged_stderr
    assert "token-value" not in logged_stderr
    assert len(logged_stderr) <= 4000


def test_codex_runner_resolves_windows_command_shim(tmp_path: Path) -> None:
    process = RecordingProcess(returncode=0)
    runner = CodexCliRunner(
        tmp_path,
        "codex",
        app_logger,
        process_runner=process,
        executable_resolver=lambda value: r"C:\tools\codex.CMD",
    )

    runner.run("prompt", tmp_path / "schema.json", tmp_path / "out.json", 30)

    assert process.command[0] == r"C:\tools\codex.CMD"


def test_codex_runner_uses_configured_ui_sandbox(tmp_path: Path) -> None:
    process = RecordingProcess(returncode=0)
    runner = CodexCliRunner(
        tmp_path,
        "codex",
        app_logger,
        process_runner=process,
        executable_resolver=lambda value: value,
        sandbox_mode="danger-full-access",
    )

    runner.run("prompt", tmp_path / "schema.json", tmp_path / "out.json", 30)

    sandbox_index = process.command.index("--sandbox")
    assert process.command[sandbox_index + 1] == "danger-full-access"
