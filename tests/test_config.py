from pathlib import Path

import pytest
import yaml

from terrapanel.config import StorageSettings, load_settings


def test_yaml_configuration_with_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
environment: production
http:
  bind_address: 127.0.0.1
  port: 8080
storage:
  root_dir: data
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TERRAPANEL_HTTP__PORT", "9090")
    monkeypatch.setenv("TERRAPANEL_MODS__MAX_UPLOAD_SIZE", "10485760")
    monkeypatch.setenv("TERRAPANEL_WORLDS__MAX_UPLOAD_SIZE", "20971520")

    settings = load_settings(config_file)

    assert settings.environment == "production"
    assert settings.http.bind_address == "127.0.0.1"
    assert settings.http.port == 9090
    assert settings.mods.max_upload_size == 10 * 1024 * 1024
    assert settings.worlds.max_upload_size == 20 * 1024 * 1024


def test_storage_root_derives_all_managed_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("storage:\n  root_dir: configured\n", encoding="utf-8")
    override = tmp_path / "terrapanel-data"
    monkeypatch.setenv("TERRAPANEL_STORAGE__ROOT_DIR", str(override))

    settings = load_settings(config_file)

    assert settings.storage.root_dir == override
    assert settings.storage.data_dir == override
    assert settings.storage.servers_dir == override / "servers"
    assert settings.storage.backups_dir == override / "backups"


def test_legacy_storage_directories_remain_explicit_overrides() -> None:
    storage = StorageSettings(
        data_dir=Path("state"),
        servers_dir=Path("instances"),
        backups_dir=Path("archives"),
    )

    assert storage.root_dir == Path("data")
    assert storage.data_dir == Path("state")
    assert storage.servers_dir == Path("instances")
    assert storage.backups_dir == Path("archives")


def test_explicit_missing_configuration_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.yaml")


def test_non_mapping_configuration_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_settings(config_file)


def test_docker_data_mount_and_storage_paths_are_stable() -> None:
    project_root = Path(__file__).parents[1]
    compose = yaml.safe_load((project_root / "compose.yaml").read_text(encoding="utf-8"))
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")

    assert compose["services"]["terrapanel"]["volumes"] == [
        "${TERRAPANEL_DATA_PATH:-terrapanel-data}:/data"
    ]
    assert "TERRAPANEL_STORAGE__ROOT_DIR=/data" in dockerfile
    assert 'VOLUME ["/data"]' in dockerfile
    assert "/var/lib/terrapanel" not in dockerfile
