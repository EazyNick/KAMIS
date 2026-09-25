from pathlib import Path

import pytest

from config.server_config import (
    DEFAULT_ONLINE_TARGET_KEYS,
    ConfigurationError,
    Settings,
)


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


def test_shopping_browser_settings_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHOPPING_USER_DATA_DIR", str(tmp_path / "browser-profile"))
    monkeypatch.setenv("SHOPPING_HEADLESS", "false")
    configured = Settings.from_env(load_environment_file=False)
    assert configured.shopping_user_data_dir == (tmp_path / "browser-profile").resolve()
    assert configured.shopping_headless is False


def test_online_collection_defaults_to_ten_representative_kamis_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ONLINE_TARGETS", raising=False)
    monkeypatch.delenv("SHOPPING_USER_DATA_DIR", raising=False)

    configured = Settings.from_env(load_environment_file=False)

    assert configured.online_target_keys == frozenset(DEFAULT_ONLINE_TARGET_KEYS)
    assert len(configured.online_target_keys) == 10
    assert (
        configured.shopping_user_data_dir
        == (tmp_path / "data/browser-profile").resolve()
    )
    assert configured.shopping_request_interval_seconds == 5


def test_online_targets_must_contain_exactly_ten_unique_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONLINE_TARGETS", "111:10,152:00")

    with pytest.raises(ConfigurationError, match="exactly 10"):
        Settings.from_env(load_environment_file=False)
