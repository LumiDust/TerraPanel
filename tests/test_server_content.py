import json
from pathlib import Path

import pytest

from terrapanel.domain.errors import DomainValidationError, ResourceNotFoundError
from terrapanel.domain.server_content import ServerConfigPatch
from terrapanel.services.container import ServiceContainer


def test_selects_world_and_preserves_unknown_config(
    instance_root: Path, services: ServiceContainer
) -> None:
    world = instance_root / "Worlds" / "Example.wld"
    world.write_bytes(b"world")
    world.with_suffix(".twld").write_bytes(b"mod world")
    with services.instances.require().config_file.open("a", encoding="utf-8") as file:
        file.write("customsetting=preserved\n")

    worlds = services.worlds.list()
    view = services.worlds.select("Worlds/Example.wld")

    assert len(worlds) == 1
    assert worlds[0].has_mod_data is True
    assert view.values["world"] == str(world.resolve())
    assert view.values["customsetting"] == "preserved"


def test_rejects_config_path_outside_instance(
    tmp_path: Path, instance_root: Path, services: ServiceContainer
) -> None:
    outside = tmp_path.parent / "outside.wld"

    with pytest.raises(DomainValidationError):
        services.server_config.update(ServerConfigPatch(world=str(outside)))


def test_enables_and_disables_local_mod(instance_root: Path, services: ServiceContainer) -> None:
    (instance_root / "Mods" / "ExampleMod.tmod").write_bytes(b"mod")

    mods = services.mods.list()
    enabled = services.mods.enable("ExampleMod")
    updated = services.mods.list()
    disabled = services.mods.disable("ExampleMod")

    assert mods[0].enabled is False
    assert enabled == ["ExampleMod"]
    assert updated[0].enabled is True
    assert disabled == []
    assert json.loads((instance_root / "Mods" / "enabled.json").read_text()) == []


def test_rejects_enabling_missing_mod(instance_root: Path, services: ServiceContainer) -> None:
    with pytest.raises(ResourceNotFoundError):
        services.mods.enable("MissingMod")
