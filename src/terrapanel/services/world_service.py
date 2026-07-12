import os
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

from terrapanel.domain.errors import ConflictError, DomainValidationError, ResourceNotFoundError
from terrapanel.domain.process import ProcessSnapshot, ProcessState
from terrapanel.domain.server_content import ServerConfigView, WorldInfo
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.server_config_service import ServerConfigService

_COPY_CHUNK_SIZE = 1024 * 1024
_WORLD_SUFFIXES = (".wld", ".twld")
_DELETE_SUFFIXES = (
    ".wld",
    ".twld",
    ".wld.bak",
    ".twld.bak",
    ".wld.bak2",
    ".twld.bak2",
    ".wld.bak3",
    ".twld.bak3",
)


class _ProcessStatus(Protocol):
    def snapshot(self) -> ProcessSnapshot: ...


class WorldService:
    def __init__(
        self,
        instances: InstanceService,
        server_config: ServerConfigService,
        process: _ProcessStatus,
        *,
        max_upload_size: int,
    ) -> None:
        self._instances = instances
        self._server_config = server_config
        self._process = process
        self._max_upload_size = max_upload_size

    def list(self) -> list[WorldInfo]:
        instance = self._instances.require()
        worlds_dir = instance.root_dir / "Worlds"
        selected = self._selected_world()
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
                    path=world.relative_to(instance.root_dir).as_posix(),
                    has_mod_data=has_mod_data,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    selected=world == selected,
                )
            )
        return worlds

    def select(self, path: str) -> ServerConfigView:
        self._require_stopped()
        instance = self._instances.require()
        world = self._instances.resolve_in_root(path, must_exist=True)
        if world.suffix.lower() != ".wld" or world.parent != instance.root_dir / "Worlds":
            raise ResourceNotFoundError(
                "World must be a .wld file in the instance Worlds directory"
            )
        return self._server_config.set_values({"world": world})

    def upload(
        self,
        files: Sequence[tuple[str | None, BinaryIO]],
        *,
        replace: bool = False,
    ) -> WorldInfo:
        self._require_stopped()
        if not 1 <= len(files) <= 2:
            raise DomainValidationError("Upload one .wld and an optional matching .twld file")

        worlds_dir = self._instances.resolve_in_root("Worlds")
        worlds_dir.mkdir(parents=True, exist_ok=True)
        uploads: dict[str, tuple[str, BinaryIO]] = {}
        for filename, source in files:
            safe_name, suffix = self._validate_filename(filename)
            if suffix in uploads:
                raise DomainValidationError(f"Only one {suffix} file can be uploaded")
            uploads[suffix] = (safe_name, source)
        if ".wld" not in uploads:
            raise DomainValidationError("A .wld world file is required")

        world_name = Path(uploads[".wld"][0]).stem
        if any(
            Path(filename).stem.casefold() != world_name.casefold()
            for filename, _ in uploads.values()
        ):
            raise DomainValidationError("The .wld and .twld filenames must match")

        token = uuid4().hex
        temporary: dict[str, Path] = {}
        total_size = 0
        try:
            for suffix, (_filename, source) in uploads.items():
                path = worlds_dir / f".upload-{token}{suffix}.tmp"
                total_size = self._copy_upload(source, path, total_size)
                temporary[suffix] = path
            self._validate_world_file(temporary[".wld"])
            self._replace_world_pair(world_name, worlds_dir, temporary, replace=replace)
        finally:
            for path in temporary.values():
                path.unlink(missing_ok=True)

        return next(
            world for world in self.list() if world.name.casefold() == world_name.casefold()
        )

    def delete(self, name: str) -> list[str]:
        self._require_stopped()
        self._validate_world_name(name)
        instance = self._instances.require()
        worlds_dir = instance.root_dir / "Worlds"
        world = self._instances.resolve_in_root(worlds_dir / f"{name}.wld", must_exist=True)
        if world.parent != worlds_dir or not world.is_file():
            raise ResourceNotFoundError(f"World does not exist: {name}")
        if world == self._selected_world():
            raise ConflictError("Select another world before deleting the active world")

        deleted: list[str] = []
        for suffix in _DELETE_SUFFIXES:
            candidate = worlds_dir / f"{name}{suffix}"
            if not candidate.exists():
                continue
            file = self._instances.resolve_in_root(candidate, must_exist=True)
            if not file.is_file() or file.parent != worlds_dir:
                raise DomainValidationError(f"World companion is not a regular file: {file.name}")
            file.unlink()
            deleted.append(file.name)
        return deleted

    def _replace_world_pair(
        self,
        name: str,
        worlds_dir: Path,
        temporary: dict[str, Path],
        *,
        replace: bool,
    ) -> None:
        targets = {suffix: worlds_dir / f"{name}{suffix}" for suffix in _WORLD_SUFFIXES}
        if not replace and any(target.exists() for target in targets.values()):
            raise ConflictError(f"A world is already installed: {name}")

        backups: dict[str, Path] = {}
        installed: list[Path] = []
        token = uuid4().hex
        try:
            for suffix, target in targets.items():
                if target.exists():
                    existing = self._instances.resolve_in_root(target, must_exist=True)
                    backup = worlds_dir / f".replace-{token}{suffix}.bak"
                    os.replace(existing, backup)
                    backups[suffix] = backup
            for suffix, source in temporary.items():
                target = self._instances.resolve_in_root(targets[suffix])
                os.replace(source, target)
                installed.append(target)
        except Exception:
            for target in installed:
                target.unlink(missing_ok=True)
            for suffix, backup in backups.items():
                if backup.exists():
                    os.replace(backup, targets[suffix])
            raise
        else:
            for backup in backups.values():
                backup.unlink(missing_ok=True)

    def _copy_upload(self, source: BinaryIO, destination: Path, current_size: int) -> int:
        size = current_size
        try:
            with destination.open("xb") as output:
                while chunk := source.read(_COPY_CHUNK_SIZE):
                    size += len(chunk)
                    if size > self._max_upload_size:
                        raise DomainValidationError(
                            f"World files exceed the {self._max_upload_size} byte upload limit"
                        )
                    output.write(chunk)
        except OSError as error:
            raise DomainValidationError(f"Cannot store uploaded world: {error}") from error
        if size == current_size:
            raise DomainValidationError("Uploaded world files cannot be empty")
        return size

    @staticmethod
    def _validate_world_file(path: Path) -> None:
        try:
            with path.open("rb") as file:
                header = file.read(4)
        except OSError as error:
            raise DomainValidationError(f"Cannot read uploaded .wld file: {error}") from error
        if len(header) != 4:
            raise DomainValidationError("The uploaded .wld file is truncated")
        version = struct.unpack("<i", header)[0]
        if not 1 <= version <= 10000:
            raise DomainValidationError("The uploaded .wld version header is invalid")

    @staticmethod
    def _validate_filename(filename: str | None) -> tuple[str, str]:
        if not filename:
            raise DomainValidationError("Each uploaded world file must have a filename")
        if len(filename) > 255 or any(character in filename for character in ("/", "\\", "\x00")):
            raise DomainValidationError("The uploaded world filename is not safe")
        path = Path(filename)
        suffix = path.suffix.lower()
        if suffix not in _WORLD_SUFFIXES:
            raise DomainValidationError("Only .wld and .twld world files can be uploaded")
        WorldService._validate_world_name(path.stem)
        return filename, suffix

    @staticmethod
    def _validate_world_name(name: str) -> None:
        if not name or len(name) > 120 or any(
            character in name for character in ("/", "\\", "\r", "\n", "\x00")
        ):
            raise DomainValidationError("The world name is not safe")

    def _selected_world(self) -> Path | None:
        value = self._server_config.read().values.get("world")
        if not value:
            return None
        try:
            return self._instances.resolve_in_root(value)
        except DomainValidationError:
            return None

    def _require_stopped(self) -> None:
        if self._process.snapshot().state not in {ProcessState.STOPPED, ProcessState.FAILED}:
            raise ConflictError("Stop the tModLoader server before managing worlds")
