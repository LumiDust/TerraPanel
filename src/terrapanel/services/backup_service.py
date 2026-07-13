import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from terrapanel.domain.errors import ConflictError, DomainValidationError, ResourceNotFoundError
from terrapanel.domain.server_content import BackupInfo
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.process_manager import ProcessManager

_SINGLE_FILES = ("serverconfig.txt", "banlist.txt")
_MOD_FILES = ("enabled.json", "install.txt")
_PROFILE_DIRECTORY = "WorldConfigs"
_SELECTION_FILE = "active.json"


class BackupService:
    def __init__(
        self,
        instances: InstanceService,
        process: ProcessManager,
        backups_dir: Path,
    ) -> None:
        self._instances = instances
        self._process = process
        self._backups_dir = backups_dir.expanduser().resolve()

    def list(self) -> list[BackupInfo]:
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        backups: list[BackupInfo] = []
        for path in sorted(self._backups_dir.glob("*.zip"), reverse=True):
            try:
                with zipfile.ZipFile(path) as archive:
                    world_files = sum(
                        1
                        for item in archive.infolist()
                        if item.filename.startswith("Worlds/") and item.filename.endswith(".wld")
                    )
            except zipfile.BadZipFile:
                world_files = 0
            stat_result = path.stat()
            backups.append(
                BackupInfo(
                    id=path.stem,
                    created_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
                    size=stat_result.st_size,
                    world_files=world_files,
                )
            )
        return backups

    def create(self, label: str | None = None) -> BackupInfo:
        self._require_stopped()
        instance = self._instances.require()
        world_files = [
            self._instances.resolve_in_root(path, must_exist=True)
            for path in (instance.root_dir / "Worlds").rglob("*")
            if path.is_file()
        ]
        if not any(path.suffix.lower() == ".wld" for path in world_files):
            raise DomainValidationError(
                "At least one .wld world is required before creating a backup"
            )

        self._backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC)
        suffix = f"-{label}" if label else ""
        backup_id = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}{suffix}"
        destination = self._backups_dir / f"{backup_id}.zip"
        temporary = destination.with_suffix(".tmp")
        written: list[str] = []

        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file in world_files:
                    relative = file.relative_to(instance.root_dir).as_posix()
                    archive.write(file, relative)
                    written.append(relative)

                profile_directory = instance.root_dir / _PROFILE_DIRECTORY
                for file in profile_directory.glob("*"):
                    if not file.is_file():
                        continue
                    managed = self._instances.resolve_in_root(file, must_exist=True)
                    relative = managed.relative_to(instance.root_dir).as_posix()
                    archive.write(managed, relative)
                    written.append(relative)

                for name in _SINGLE_FILES:
                    file = instance.root_dir / name
                    if file.is_file():
                        file = self._instances.resolve_in_root(file, must_exist=True)
                        archive.write(file, name)
                        written.append(name)

                for name in _MOD_FILES:
                    file = instance.root_dir / "Mods" / name
                    if file.is_file():
                        file = self._instances.resolve_in_root(file, must_exist=True)
                        relative = f"Mods/{name}"
                        archive.write(file, relative)
                        written.append(relative)

                manifest = {
                    "format": 1,
                    "created_at": timestamp.isoformat(),
                    "instance_id": instance.id,
                    "files": written,
                }
                archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")

            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return next(backup for backup in self.list() if backup.id == backup_id)

    def restore(self, backup_id: str) -> BackupInfo:
        self._require_stopped()
        archive_path = self.archive_path(backup_id)

        instance = self._instances.require()
        with tempfile.TemporaryDirectory(
            prefix=".restore-", dir=instance.root_dir
        ) as temporary_name:
            temporary_root = Path(temporary_name)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    self._extract_validated(archive, temporary_root)
            except zipfile.BadZipFile as error:
                raise DomainValidationError(f"Backup archive is invalid: {backup_id}") from error

            restored_worlds = temporary_root / "Worlds"
            if not any(restored_worlds.glob("*.wld")):
                raise DomainValidationError("Backup does not contain a .wld world")

            current_worlds = instance.root_dir / "Worlds"
            previous_worlds = instance.root_dir / f".Worlds-before-restore-{uuid4().hex}"
            current_profiles = instance.root_dir / _PROFILE_DIRECTORY
            previous_profiles = instance.root_dir / f".WorldConfigs-before-restore-{uuid4().hex}"
            restored_profiles = temporary_root / _PROFILE_DIRECTORY
            if current_worlds.exists():
                os.replace(current_worlds, previous_worlds)
            if current_profiles.exists():
                os.replace(current_profiles, previous_profiles)

            try:
                os.replace(restored_worlds, current_worlds)
                if restored_profiles.exists():
                    os.replace(restored_profiles, current_profiles)
                for name in _SINGLE_FILES:
                    self._copy_if_present(temporary_root / name, instance.root_dir / name)
                for name in _MOD_FILES:
                    self._copy_if_present(
                        temporary_root / "Mods" / name,
                        instance.root_dir / "Mods" / name,
                    )
            except Exception:
                if current_worlds.exists():
                    shutil.rmtree(current_worlds)
                if previous_worlds.exists():
                    os.replace(previous_worlds, current_worlds)
                if current_profiles.exists():
                    shutil.rmtree(current_profiles)
                if previous_profiles.exists():
                    os.replace(previous_profiles, current_profiles)
                raise
            else:
                if previous_worlds.exists():
                    shutil.rmtree(previous_worlds)
                if previous_profiles.exists():
                    shutil.rmtree(previous_profiles)

        return next(backup for backup in self.list() if backup.id == backup_id)

    def archive_path(self, backup_id: str) -> Path:
        if not backup_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in backup_id
        ):
            raise DomainValidationError("Invalid backup identifier")

        archive_path = self._backups_dir / f"{backup_id}.zip"
        if archive_path.is_symlink() or archive_path.is_junction():
            raise DomainValidationError(f"Backup path cannot be a link: {backup_id}")
        if not archive_path.is_file():
            raise ResourceNotFoundError(f"Backup does not exist: {backup_id}")
        return archive_path

    def delete(self, backup_id: str) -> None:
        archive_path = self.archive_path(backup_id)
        try:
            archive_path.unlink()
        except OSError as error:
            raise DomainValidationError(f"Cannot delete backup {backup_id}: {error}") from error

    def _extract_validated(self, archive: zipfile.ZipFile, destination: Path) -> None:
        for item in archive.infolist():
            relative = PurePosixPath(item.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise DomainValidationError(f"Unsafe path in backup: {item.filename}")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise DomainValidationError(
                    f"Symbolic links are not allowed in backups: {item.filename}"
                )
            if not self._is_allowed(relative):
                raise DomainValidationError(f"Unexpected file in backup: {item.filename}")

            target = destination.joinpath(*relative.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    @staticmethod
    def _is_allowed(relative: PurePosixPath) -> bool:
        if relative.as_posix() in {"manifest.json", *_SINGLE_FILES}:
            return True
        if relative.parts and relative.parts[0] == "Worlds":
            return True
        if len(relative.parts) == 1 and relative.parts[0] == _PROFILE_DIRECTORY:
            return True
        if len(relative.parts) == 2 and relative.parts[0] == _PROFILE_DIRECTORY:
            return relative.suffix == ".txt" or relative.name == _SELECTION_FILE
        return (
            len(relative.parts) == 2
            and relative.parts[0] == "Mods"
            and relative.parts[1] in _MOD_FILES
        )

    @staticmethod
    def _copy_if_present(source: Path, destination: Path) -> None:
        if not source.is_file():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    def _require_stopped(self) -> None:
        if self._process.is_running():
            raise ConflictError("Stop the tModLoader server before backup or restore")
