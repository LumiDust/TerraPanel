import json
import os
import subprocess
from pathlib import Path

import pytest

from terrapanel.config import Settings
from terrapanel.domain.errors import DomainValidationError
from terrapanel.domain.instance import InstanceAssociation
from terrapanel.services.container import ServiceContainer


def test_associates_official_directory_layout(
    app_settings: Settings,
    services: ServiceContainer,
    instance_root: Path,
) -> None:
    instance = services.instances.require()

    assert instance.name == "Test Server"
    assert instance.root_dir == instance_root.resolve()
    assert instance.launch_script == instance_root / "server" / "start-tModLoaderServer.sh"
    assert instance.config_file.is_file()
    assert (instance_root / "Mods").is_dir()
    assert (instance_root / "Worlds").is_dir()
    assert (app_settings.storage.data_dir / "instance.json").is_file()


def test_rejects_association_outside_server_root(
    tmp_path: Path, services: ServiceContainer
) -> None:
    outside = tmp_path.parent / "outside-instance"
    outside.mkdir(exist_ok=True)

    with pytest.raises(DomainValidationError):
        services.instances.associate(InstanceAssociation(root_dir=str(outside)))


def test_rejects_incomplete_installation(
    app_settings: Settings, services: ServiceContainer
) -> None:
    root = app_settings.storage.servers_dir / "incomplete"
    root.mkdir()

    with pytest.raises(DomainValidationError, match="installation is incomplete"):
        services.instances.associate(InstanceAssociation(root_dir="incomplete"))


def test_rejects_tampered_persisted_paths(
    app_settings: Settings,
    services: ServiceContainer,
    instance_root: Path,
) -> None:
    metadata_file = app_settings.storage.data_dir / "instance.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["config_file"] = str(instance_root.parent / "outside-config.txt")
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(DomainValidationError, match="stored instance paths"):
        services.instances.require()


def test_rejects_managed_directory_symlink(
    tmp_path: Path,
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    root = app_settings.storage.servers_dir / "linked"
    outside_install = tmp_path / "outside-install"
    outside_install.mkdir()
    (outside_install / "start-tModLoaderServer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (outside_install / "tModLoader.dll").write_bytes(b"assembly")
    root.mkdir()
    _link_directory(root / "server", outside_install)

    with pytest.raises(DomainValidationError, match="Symbolic links"):
        services.instances.associate(InstanceAssociation(root_dir="linked"))


def test_revalidates_managed_paths_after_association(
    tmp_path: Path,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    worlds = instance_root / "Worlds"
    worlds.rmdir()
    outside_worlds = tmp_path / "outside-worlds"
    outside_worlds.mkdir()
    _link_directory(worlds, outside_worlds)

    with pytest.raises(DomainValidationError, match="Symbolic links"):
        services.instances.require()


def _link_directory(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"Symbolic links are unavailable: {error}")

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        pytest.skip("Neither symbolic links nor directory junctions are available")
