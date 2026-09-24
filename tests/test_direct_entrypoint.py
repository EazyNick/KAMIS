from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import uvicorn

from app import main as main_module


def test_main_file_can_be_loaded_outside_project_import_path(tmp_path: Path) -> None:
    main_file = Path(__file__).resolve().parents[1] / "app" / "main.py"
    script = (
        "import runpy; "
        f"runpy.run_path({str(main_file)!r}, run_name='entrypoint_import_check')"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_direct_main_starts_uvicorn(monkeypatch) -> None:
    calls: list[tuple[object, str, int]] = []

    def fake_run(application: object, *, host: str, port: int) -> None:
        calls.append((application, host, port))

    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert main_module.main() == 0
    assert calls == [(main_module.app, "127.0.0.1", 8000)]
