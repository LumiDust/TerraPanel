from pathlib import Path

import pytest

from terrapanel.config import Settings, StorageSettings
from terrapanel.domain.instance import InstanceAssociation
from terrapanel.services.container import ServiceContainer, build_services


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        storage=StorageSettings(
            data_dir=tmp_path / "data",
            servers_dir=tmp_path / "servers",
            backups_dir=tmp_path / "backups",
        ),
    )


@pytest.fixture
def services(app_settings: Settings) -> ServiceContainer:
    app_settings.prepare_directories()
    return build_services(app_settings)


@pytest.fixture
def instance_root(app_settings: Settings, services: ServiceContainer) -> Path:
    root = app_settings.storage.servers_dir / "primary"
    install = root / "server"
    install.mkdir(parents=True)
    (install / "start-tModLoaderServer.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (install / "tModLoader.dll").write_bytes(b"test assembly")
    services.instances.associate(InstanceAssociation(name="Test Server", root_dir="primary"))
    return root
