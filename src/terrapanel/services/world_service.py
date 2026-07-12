from datetime import UTC, datetime

from terrapanel.domain.errors import ResourceNotFoundError
from terrapanel.domain.server_content import ServerConfigView, WorldInfo
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.server_config_service import ServerConfigService


class WorldService:
    def __init__(self, instances: InstanceService, server_config: ServerConfigService) -> None:
        self._instances = instances
        self._server_config = server_config

    def list(self) -> list[WorldInfo]:
        instance = self._instances.require()
        worlds_dir = instance.root_dir / "Worlds"
        worlds: list[WorldInfo] = []
        for candidate in sorted(worlds_dir.glob("*.wld"), key=lambda path: path.name.lower()):
            world = self._instances.resolve_in_root(candidate, must_exist=True)
            if not world.is_file() or world.parent != worlds_dir:
                continue
            mod_data = world.with_suffix(".twld")
            has_mod_data = False
            if mod_data.exists():
                has_mod_data = self._instances.resolve_in_root(
                    mod_data, must_exist=True
                ).is_file()
            stat = world.stat()
            worlds.append(
                WorldInfo(
                    name=world.stem,
                    path=str(world.relative_to(instance.root_dir)),
                    has_mod_data=has_mod_data,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        return worlds

    def select(self, path: str) -> ServerConfigView:
        instance = self._instances.require()
        world = self._instances.resolve_in_root(path, must_exist=True)
        if world.suffix.lower() != ".wld" or world.parent != instance.root_dir / "Worlds":
            raise ResourceNotFoundError(
                "World must be a .wld file in the instance Worlds directory"
            )
        return self._server_config.set_values({"world": world})
