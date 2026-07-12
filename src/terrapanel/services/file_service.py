import os
import shutil
import stat
import zipfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import uuid4

from terrapanel.domain.errors import ConflictError, DomainValidationError, ResourceNotFoundError
from terrapanel.domain.files import (
    ArchiveExtractResult,
    ArchivePreview,
    DirectoryListing,
    FileEntry,
)
from terrapanel.domain.process import ProcessSnapshot, ProcessState
from terrapanel.services.instance_service import InstanceService

_COPY_CHUNK_SIZE = 1024 * 1024
_INTERNAL_PREFIXES = (".upload-", ".extract-", ".extract-backup-")


class _ProcessStatus(Protocol):
    def snapshot(self) -> ProcessSnapshot: ...


@dataclass(frozen=True, slots=True)
class _ArchiveMember:
    info: zipfile.ZipInfo
    relative: Path
    target: Path
    directory: bool


@dataclass(frozen=True, slots=True)
class _ArchivePlan:
    archive: Path
    destination: Path
    destination_relative: str
    members: tuple[_ArchiveMember, ...]
    preview: ArchivePreview


class FileService:
    def __init__(
        self,
        instances: InstanceService,
        process: _ProcessStatus,
        *,
        max_upload_size: int,
        max_archive_entries: int,
        max_expanded_size: int,
    ) -> None:
        self._instances = instances
        self._process = process
        self._max_upload_size = max_upload_size
        self._max_archive_entries = max_archive_entries
        self._max_expanded_size = max_expanded_size

    def list(self, directory: str = "") -> DirectoryListing:
        instance = self._instances.require()
        relative = self._relative(directory, allow_root=True)
        current = self._instances.resolve_in_root(relative)
        if not current.exists():
            raise ResourceNotFoundError(f"Directory does not exist: {directory or '/'}")
        if not current.is_dir():
            raise DomainValidationError(f"Path is not a directory: {directory}")

        entries = [
            self._entry(candidate, instance.root_dir)
            for candidate in current.iterdir()
            if not candidate.name.startswith(_INTERNAL_PREFIXES)
        ]
        entries.sort(key=lambda entry: (entry.kind != "directory", entry.name.casefold()))
        relative_posix = self._as_posix(current.relative_to(instance.root_dir))
        parent = PurePosixPath(relative_posix).parent.as_posix() if relative_posix else None
        if parent == ".":
            parent = ""
        return DirectoryListing(path=relative_posix, parent=parent, entries=entries)

    def create_directory(self, path: str) -> FileEntry:
        self._require_stopped()
        instance = self._instances.require()
        relative = self._relative(path, allow_root=False)
        target = self._instances.resolve_in_root(relative)
        if target.exists():
            raise ConflictError(f"A file or directory already exists: {path}")
        try:
            target.mkdir(parents=True)
        except OSError as error:
            raise DomainValidationError(f"Cannot create directory: {error}") from error
        self._instances.resolve_in_root(target, must_exist=True)
        return self._entry(target, instance.root_dir)

    async def upload(
        self,
        directory: str,
        filename: str,
        chunks: AsyncIterable[bytes],
        *,
        replace: bool = False,
        declared_size: int | None = None,
    ) -> FileEntry:
        self._require_stopped()
        instance = self._instances.require()
        safe_name = self._filename(filename)
        relative_directory = self._relative(directory, allow_root=True)
        parent = self._instances.resolve_in_root(relative_directory, must_exist=True)
        if not parent.is_dir():
            raise DomainValidationError("The upload destination is not a directory")
        if declared_size is not None and declared_size > self._max_upload_size:
            raise DomainValidationError(
                f"The file exceeds the {self._max_upload_size} byte upload limit"
            )

        target = self._instances.resolve_in_root(parent / safe_name)
        if target.exists():
            existing = self._instances.resolve_in_root(target, must_exist=True)
            if not existing.is_file():
                raise ConflictError(f"The upload target is not a regular file: {safe_name}")
            if not replace:
                raise ConflictError(f"A file already exists: {safe_name}")

        temporary = parent / f".upload-{uuid4().hex}.tmp"
        size = 0
        try:
            with temporary.open("xb") as output:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self._max_upload_size:
                        raise DomainValidationError(
                            f"The file exceeds the {self._max_upload_size} byte upload limit"
                        )
                    output.write(chunk)
            if size == 0:
                raise DomainValidationError("Uploaded files cannot be empty")
            os.replace(temporary, target)
        except DomainValidationError:
            raise
        except OSError as error:
            raise DomainValidationError(f"Cannot store uploaded file: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)
        return self._entry(target, instance.root_dir)

    def download_path(self, path: str) -> Path:
        relative = self._relative(path, allow_root=False)
        target = self._instances.resolve_in_root(relative)
        if not target.exists():
            raise ResourceNotFoundError(f"File does not exist: {path}")
        target = self._instances.resolve_in_root(target, must_exist=True)
        if not target.is_file():
            raise DomainValidationError(f"Path is not a regular file: {path}")
        return target

    def move(self, source: str, destination: str, *, replace: bool = False) -> FileEntry:
        self._require_stopped()
        instance = self._instances.require()
        source_relative = self._relative(source, allow_root=False)
        destination_relative = self._relative(destination, allow_root=False)
        source_path = self._instances.resolve_in_root(source_relative)
        if not source_path.exists():
            raise ResourceNotFoundError(f"Path does not exist: {source}")
        source_path = self._instances.resolve_in_root(source_path, must_exist=True)
        if not (source_path.is_file() or source_path.is_dir()):
            raise DomainValidationError("Only regular files and directories can be moved")

        destination_path = self._instances.resolve_in_root(destination_relative)
        parent = self._instances.resolve_in_root(destination_path.parent, must_exist=True)
        if not parent.is_dir():
            raise DomainValidationError("The destination parent is not a directory")
        if source_path.is_dir():
            try:
                destination_path.relative_to(source_path)
            except ValueError:
                pass
            else:
                raise DomainValidationError("A directory cannot be moved inside itself")

        if destination_path.exists():
            destination_path = self._instances.resolve_in_root(
                destination_path, must_exist=True
            )
            if not replace:
                raise ConflictError(f"The destination already exists: {destination}")
            if not source_path.is_file() or not destination_path.is_file():
                raise ConflictError("Replacing directories is not supported")
        try:
            os.replace(source_path, destination_path)
        except OSError as error:
            raise DomainValidationError(f"Cannot move path: {error}") from error
        return self._entry(destination_path, instance.root_dir)

    def delete(self, path: str, *, recursive: bool = False) -> None:
        self._require_stopped()
        relative = self._relative(path, allow_root=False)
        parent_relative = relative.parent
        parent = self._instances.resolve_in_root(parent_relative, must_exist=True)
        target = parent / relative.name
        if not target.exists() and not target.is_symlink():
            raise ResourceNotFoundError(f"Path does not exist: {path}")
        try:
            if target.is_symlink() or target.is_junction() or target.is_file():
                target.unlink()
            elif target.is_dir():
                if recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
            else:
                raise DomainValidationError("Unsupported file type")
        except OSError as error:
            if target.is_dir() and not recursive:
                raise ConflictError("Directory is not empty; confirm recursive deletion") from error
            raise DomainValidationError(f"Cannot delete path: {error}") from error

    def inspect_archive(self, path: str, destination: str = "") -> ArchivePreview:
        return self._archive_plan(path, destination).preview

    def extract_archive(
        self,
        path: str,
        destination: str = "",
        *,
        replace: bool = False,
    ) -> ArchiveExtractResult:
        self._require_stopped()
        instance = self._instances.require()
        plan = self._archive_plan(path, destination)
        if plan.preview.conflicts and not replace:
            raise ConflictError(
                f"Archive extraction has {len(plan.preview.conflicts)} existing file conflicts"
            )
        if shutil.disk_usage(instance.root_dir).free < plan.preview.expanded_size:
            raise ConflictError("Not enough free disk space to extract the archive")

        token = uuid4().hex
        stage = self._instances.resolve_in_root(f".extract-{token}")
        backup = self._instances.resolve_in_root(f".extract-backup-{token}")
        installed: list[Path] = []
        backups: list[tuple[Path, Path]] = []
        try:
            stage.mkdir()
            self._extract_to_stage(plan, stage)
            for member in plan.members:
                if member.directory:
                    member.target.mkdir(parents=True, exist_ok=True)
                    continue
                member.target.parent.mkdir(parents=True, exist_ok=True)
                if member.target.exists():
                    relative_target = member.target.relative_to(instance.root_dir)
                    backup_target = backup / relative_target
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(member.target, backup_target)
                    backups.append((backup_target, member.target))
                staged = stage / member.relative
                os.replace(staged, member.target)
                installed.append(member.target)
        except Exception as error:
            for target in reversed(installed):
                target.unlink(missing_ok=True)
            for stored, target in reversed(backups):
                if stored.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stored, target)
            if isinstance(error, OSError):
                raise DomainValidationError(
                    f"Cannot install extracted archive files: {error}"
                ) from error
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)

        return ArchiveExtractResult(
            destination=plan.destination_relative,
            files=plan.preview.files,
            directories=plan.preview.directories,
            bytes_written=plan.preview.expanded_size,
        )

    def _archive_plan(self, path: str, destination: str) -> _ArchivePlan:
        instance = self._instances.require()
        archive = self.download_path(path)
        if archive.suffix.casefold() != ".zip":
            raise DomainValidationError("Only .zip archives can be inspected or extracted")
        destination_relative = self._relative(destination, allow_root=True)
        destination_path = self._instances.resolve_in_root(
            destination_relative, must_exist=True
        )
        if not destination_path.is_dir():
            raise DomainValidationError("The archive destination is not a directory")

        members: list[_ArchiveMember] = []
        conflicts: list[str] = []
        top_level: set[str] = set()
        seen: set[str] = set()
        archive_kinds: dict[str, bool] = {}
        expanded_size = 0
        compressed_size = 0
        files = 0
        directories = 0
        try:
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                if len(infos) > self._max_archive_entries:
                    raise DomainValidationError(
                        f"Archive exceeds the {self._max_archive_entries} entry limit"
                    )
                for info in infos:
                    relative = self._archive_relative(info)
                    key = relative.as_posix().casefold()
                    if key in seen:
                        raise DomainValidationError(
                            f"Archive contains duplicate paths: {relative.as_posix()}"
                        )
                    seen.add(key)
                    top_level.add(relative.parts[0])
                    target = self._instances.resolve_in_root(destination_path / relative)
                    directory = info.is_dir()
                    self._validate_archive_tree(relative, directory, archive_kinds)
                    self._validate_existing_parents(destination_path, relative)
                    archive_kinds[key] = directory
                    if directory:
                        directories += 1
                        if target.exists() and not target.is_dir():
                            raise ConflictError(
                                f"Archive directory conflicts with a file: "
                                f"{target.relative_to(instance.root_dir).as_posix()}"
                            )
                    else:
                        files += 1
                        expanded_size += info.file_size
                        compressed_size += info.compress_size
                        if expanded_size > self._max_expanded_size:
                            raise DomainValidationError(
                                f"Archive exceeds the {self._max_expanded_size} byte "
                                "expanded size limit"
                            )
                        if target.exists():
                            if not target.is_file():
                                raise ConflictError(
                                    f"Archive file conflicts with a directory: "
                                    f"{target.relative_to(instance.root_dir).as_posix()}"
                                )
                            conflicts.append(target.relative_to(instance.root_dir).as_posix())
                    members.append(
                        _ArchiveMember(
                            info=info,
                            relative=relative,
                            target=target,
                            directory=directory,
                        )
                    )
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
            raise DomainValidationError(f"Cannot read ZIP archive: {error}") from error

        preview = ArchivePreview(
            path=archive.relative_to(instance.root_dir).as_posix(),
            files=files,
            directories=directories,
            expanded_size=expanded_size,
            compressed_size=compressed_size,
            top_level=sorted(top_level, key=str.casefold),
            conflicts=conflicts,
        )
        return _ArchivePlan(
            archive=archive,
            destination=destination_path,
            destination_relative=self._as_posix(
                destination_path.relative_to(instance.root_dir)
            ),
            members=tuple(members),
            preview=preview,
        )

    @staticmethod
    def _validate_archive_tree(
        relative: Path,
        directory: bool,
        archive_kinds: dict[str, bool],
    ) -> None:
        parts = relative.as_posix().casefold().split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            if archive_kinds.get(ancestor) is False:
                raise DomainValidationError(
                    f"Archive path uses a file as a directory: {relative.as_posix()}"
                )
        key = "/".join(parts)
        if not directory and any(existing.startswith(f"{key}/") for existing in archive_kinds):
            raise DomainValidationError(
                f"Archive path conflicts with an existing directory tree: {relative.as_posix()}"
            )

    @staticmethod
    def _validate_existing_parents(destination: Path, relative: Path) -> None:
        current = destination
        for part in relative.parts[:-1]:
            current /= part
            if current.exists() and not current.is_dir():
                raise ConflictError(
                    f"Archive path uses an existing file as a directory: {current.name}"
                )

    def _extract_to_stage(self, plan: _ArchivePlan, stage: Path) -> None:
        total = 0
        try:
            with zipfile.ZipFile(plan.archive) as package:
                for member in plan.members:
                    staged = stage / member.relative
                    if member.directory:
                        staged.mkdir(parents=True, exist_ok=True)
                        continue
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member.info) as source, staged.open("xb") as output:
                        written = 0
                        while chunk := source.read(_COPY_CHUNK_SIZE):
                            written += len(chunk)
                            total += len(chunk)
                            if total > self._max_expanded_size:
                                raise DomainValidationError(
                                    "Archive expanded data exceeded the configured limit"
                                )
                            output.write(chunk)
                    if written != member.info.file_size:
                        raise DomainValidationError(
                            f"Archive entry size changed while extracting: "
                            f"{member.relative.as_posix()}"
                        )
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            raise DomainValidationError(f"Cannot extract ZIP archive: {error}") from error

    @staticmethod
    def _archive_relative(info: zipfile.ZipInfo) -> Path:
        if info.flag_bits & 0x1:
            raise DomainValidationError(f"Encrypted ZIP entries are not supported: {info.filename}")
        name = info.filename.replace("\\", "/")
        raw_parts = name.split("/")
        if (
            not name
            or name.startswith("/")
            or any(part in {"", ".", ".."} for part in raw_parts[:-1])
            or any(part == ".." for part in raw_parts)
            or (raw_parts and ":" in raw_parts[0])
            or "\x00" in name
        ):
            raise DomainValidationError(f"Archive entry path is not safe: {info.filename}")
        if raw_parts[-1] == "":
            raw_parts = raw_parts[:-1]
        if not raw_parts:
            raise DomainValidationError("Archive contains an empty entry path")
        if any(len(part) > 255 for part in raw_parts):
            raise DomainValidationError(f"Archive entry name is too long: {info.filename}")

        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        allowed = {0, stat.S_IFREG, stat.S_IFDIR}
        if file_type not in allowed:
            raise DomainValidationError(
                f"Archive links and special files are not supported: {info.filename}"
            )
        return Path(*raw_parts)

    def _entry(self, path: Path, root: Path) -> FileEntry:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ResourceNotFoundError(f"Cannot inspect path: {path.name}") from error
        if path.is_symlink() or path.is_junction():
            kind = "symlink"
            size: int | None = None
        elif path.is_dir():
            kind = "directory"
            size = None
        elif path.is_file():
            kind = "file"
            size = metadata.st_size
        else:
            kind = "other"
            size = None
        return FileEntry(
            name=path.name,
            path=path.relative_to(root).as_posix(),
            kind=kind,
            size=size,
            modified_at=datetime.fromtimestamp(metadata.st_mtime, tz=UTC),
            archive=kind == "file" and path.suffix.casefold() == ".zip",
        )

    @staticmethod
    def _relative(value: str | Path, *, allow_root: bool) -> Path:
        text = str(value).replace("\\", "/")
        if len(text) > 1024 or any(character in text for character in ("\r", "\n", "\x00")):
            raise DomainValidationError("Path is not safe")
        pure = PurePosixPath(text)
        parts = pure.parts
        if pure.is_absolute() or (parts and ":" in parts[0]) or ".." in parts:
            raise DomainValidationError("Path must stay inside the server instance root")
        normalized = Path(*[part for part in parts if part not in {"", "."}])
        if not allow_root and not normalized.parts:
            raise DomainValidationError("The instance root cannot be modified")
        if any(len(part) > 255 for part in normalized.parts):
            raise DomainValidationError("A path component is too long")
        return normalized

    @staticmethod
    def _filename(value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or len(value) > 255
            or any(character in value for character in ("/", "\\", "\r", "\n", "\x00"))
        ):
            raise DomainValidationError("The uploaded filename is not safe")
        return value

    @staticmethod
    def _as_posix(path: Path) -> str:
        value = path.as_posix()
        return "" if value == "." else value

    def _require_stopped(self) -> None:
        if self._process.snapshot().state not in {ProcessState.STOPPED, ProcessState.FAILED}:
            raise ConflictError("Stop the tModLoader server before changing files")
