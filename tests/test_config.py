from pathlib import Path

import pytest
import yaml

from terrapanel.config import load_settings


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
  data_dir: data
  servers_dir: data/servers
  backups_dir: data/backups
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TERRAPANEL_HTTP__PORT", "9090")
    monkeypatch.setenv("TERRAPANEL_MODS__MAX_UPLOAD_SIZE", "10485760")

    settings = load_settings(config_file)

    assert settings.environment == "production"
    assert settings.http.bind_address == "127.0.0.1"
    assert settings.http.port == 9090
    assert settings.mods.max_upload_size == 10 * 1024 * 1024


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
        "${TERRAPANEL_DATA_PATH:-terrapanel-data}:/var/lib/terrapanel"
    ]
    assert "TERRAPANEL_STORAGE__DATA_DIR=/var/lib/terrapanel" in dockerfile
    assert "TERRAPANEL_STORAGE__SERVERS_DIR=/var/lib/terrapanel/servers" in dockerfile
    assert "TERRAPANEL_STORAGE__BACKUPS_DIR=/var/lib/terrapanel/backups" in dockerfile
