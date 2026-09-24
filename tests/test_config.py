from pathlib import Path

import pytest

from config.server_config import ConfigurationError, Settings


def test_settings_load_paths_relative_to_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()

    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.timezone == "Asia/Seoul"


def test_missing_kamis_credentials_raise_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAMIS_CERT_KEY", raising=False)
    monkeypatch.delenv("KAMIS_CERT_ID", raising=False)
    settings = Settings.from_env(load_environment_file=False)

    with pytest.raises(ConfigurationError, match="KAMIS_CERT_KEY"):
        settings.require_kamis_credentials()
