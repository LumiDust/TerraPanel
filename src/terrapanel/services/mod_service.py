import hashlib
import json
import os
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from io import BufferedIOBase
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast
from uuid import uuid4

from terrapanel.domain.errors import ConflictError, DomainValidationError, ResourceNotFoundError
from terrapanel.domain.process import ProcessSnapshot, ProcessState
from terrapanel.domain.server_content import ModInfo
from terrapanel.services.instance_service import InstanceService

_COPY_CHUNK_SIZE = 1024 * 1024
_INTERNAL_NAME_PATTERN = re.compile(r"^[\w.-]{1,120}$")


@dataclass(frozen=True, slots=True)
class _TmodMetadata:
    name: str
    version: str
    tmodloader_version: str


class _ProcessStatus(Protocol):
    def snapshot(self) -> ProcessSnapshot: ...


class ModService:
    def __init__(
        self,
        instances: InstanceService,
        process: _ProcessStatus,
        *,
        max_upload_size: int,
    ) -> None:
        self._instances = instances
        self._process = process
        self._max_upload_size = max_upload_size

    def list(self) -> list[ModInfo]:
        instance = self._instances.require()
        enabled = self._read_enabled(self._instances.resolve_in_root("Mods/enabled.json"))
        mods: list[ModInfo] = []

        sources: tuple[tuple[Literal["local", "workshop"], Path, str], ...] = (
            ("local", instance.root_dir / "Mods", "*.tmod"),
            (
                "workshop",
                instance.root_dir / "steamapps" / "workshop" / "content" / "1281930",
                "**/*.tmod",
            ),
        )
        for source, root, pattern in sources:
            if not root.exists():
                continue
            for candidate in sorted(root.glob(pattern), key=lambda path: str(path).lower()):
                file = self._instances.resolve_in_root(candidate, must_exist=True)
                if not file.is_file():
                    continue
                name = self._read_installed_name(file)
                mods.append(
                    ModInfo(
                        name=name,
                        source=source,
                        file=file.relative_to(instance.root_dir).as_posix(),
                        size=file.stat().st_size,
                        enabled=name in enabled,
                    )
                )
        return mods

    def enable(self, name: str) -> list[str]:
        available = {mod.name for mod in self.list()}
        if name not in available:
            raise ResourceNotFoundError(f"Mod is not installed: {name}")
        enabled = self.enabled_names()
        enabled.add(name)
        return self._write_enabled(enabled)

    def disable(self, name: str) -> list[str]:
        enabled = self.enabled_names()
        enabled.discard(name)
        return self._write_enabled(enabled)

    def upload(self, filename: str | None, source: BinaryIO, *, replace: bool = False) -> ModInfo:
        self._validate_upload_filename(filename)
        if self._process.snapshot().state not in {ProcessState.STOPPED, ProcessState.FAILED}:
            raise ConflictError("Stop the tModLoader server before uploading a mod")

        instance = self._instances.require()
        mods_dir = self._instances.resolve_in_root("Mods")
        mods_dir.mkdir(parents=True, exist_ok=True)
        temporary = mods_dir / f".upload-{uuid4().hex}.tmp"

        try:
            size = self._copy_upload(source, temporary)
            metadata = self._inspect_tmod(temporary)
            target = self._instances.resolve_in_root(Path("Mods") / f"{metadata.name}.tmod")
            if target.exists() and not replace:
                raise ConflictError(f"A local mod is already installed: {metadata.name}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        return ModInfo(
            name=metadata.name,
            source="local",
            file=target.relative_to(instance.root_dir).as_posix(),
            size=size,
            enabled=metadata.name in self.enabled_names(),
        )

    def delete_local(self, name: str) -> None:
        if self._process.snapshot().state not in {ProcessState.STOPPED, ProcessState.FAILED}:
            raise ConflictError("Stop the tModLoader server before deleting a mod")
        if not _INTERNAL_NAME_PATTERN.fullmatch(name):
            raise DomainValidationError("The mod name is not supported")

        local = next(
            (mod for mod in self.list() if mod.source == "local" and mod.name == name),
            None,
        )
        if local is None:
            raise ResourceNotFoundError(f"Local mod is not installed: {name}")

        target = self._instances.resolve_in_root(local.file, must_exist=True)
        temporary = target.with_name(f".delete-{uuid4().hex}.tmp")
        original_enabled = self.enabled_names()
        updated_enabled = original_enabled - {name}
        os.replace(target, temporary)
        try:
            self._write_enabled(updated_enabled)
            temporary.unlink()
        except Exception:
            if temporary.exists():
                os.replace(temporary, target)
            with suppress(Exception):
                self._write_enabled(original_enabled)
            raise

    def enabled_names(self) -> set[str]:
        return self._read_enabled(self._instances.resolve_in_root("Mods/enabled.json"))

    def _write_enabled(self, enabled: set[str]) -> list[str]:
        path = self._instances.resolve_in_root("Mods/enabled.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        values = sorted(enabled, key=str.lower)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return values

    def _copy_upload(self, source: BinaryIO, destination: Path) -> int:
        size = 0
        try:
            with destination.open("xb") as output:
                while chunk := source.read(_COPY_CHUNK_SIZE):
                    size += len(chunk)
                    if size > self._max_upload_size:
                        raise DomainValidationError(
                            f"The .tmod file exceeds the {self._max_upload_size} byte upload limit"
                        )
                    output.write(chunk)
        except OSError as error:
            raise DomainValidationError(f"Cannot store uploaded mod: {error}") from error
        if size == 0:
            raise DomainValidationError("The uploaded .tmod file is empty")
        return size

    @staticmethod
    def _inspect_tmod(path: Path) -> _TmodMetadata:
        try:
            with path.open("rb") as file:
                if file.read(4) != b"TMOD":
                    raise DomainValidationError("The uploaded file does not have a TMOD header")
                tmodloader_version = ModService._read_string(
                    file, "tModLoader version", max_bytes=80
                )
                expected_hash = ModService._read_exact(file, 20, "SHA-1 hash")
                ModService._read_exact(file, 256, "signature")
                data_length = struct.unpack(
                    "<i", ModService._read_exact(file, 4, "data length")
                )[0]
                hash_start = file.tell()
                if data_length < 0 or data_length != path.stat().st_size - hash_start:
                    raise DomainValidationError("The uploaded .tmod data length is invalid")

                name = ModService._read_string(file, "mod name", max_bytes=120)
                version = ModService._read_string(file, "mod version", max_bytes=80)
                if not _INTERNAL_NAME_PATTERN.fullmatch(name):
                    raise DomainValidationError("The .tmod internal name is not supported")

                file.seek(hash_start)
                digest = hashlib.sha1(usedforsecurity=False)
                while chunk := file.read(_COPY_CHUNK_SIZE):
                    digest.update(chunk)
                if digest.digest() != expected_hash:
                    raise DomainValidationError("The uploaded .tmod SHA-1 hash does not match")
        except DomainValidationError:
            raise
        except (OSError, UnicodeDecodeError, struct.error) as error:
            raise DomainValidationError(f"Cannot read uploaded .tmod file: {error}") from error

        return _TmodMetadata(
            name=name,
            version=version,
            tmodloader_version=tmodloader_version,
        )

    @staticmethod
    def _read_installed_name(path: Path) -> str:
        try:
            with path.open("rb") as file:
                if file.read(4) != b"TMOD":
                    return path.stem
                ModService._read_string(file, "tModLoader version", max_bytes=80)
                ModService._read_exact(file, 20, "SHA-1 hash")
                ModService._read_exact(file, 256, "signature")
                ModService._read_exact(file, 4, "data length")
                name = ModService._read_string(file, "mod name", max_bytes=120)
        except (DomainValidationError, OSError, UnicodeDecodeError, struct.error):
            return path.stem
        return name if _INTERNAL_NAME_PATTERN.fullmatch(name) else path.stem

    @staticmethod
    def _read_string(file: BufferedIOBase, label: str, *, max_bytes: int) -> str:
        length = 0
        for index in range(5):
            byte = ModService._read_exact(file, 1, f"{label} length")[0]
            length |= (byte & 0x7F) << (index * 7)
            if byte & 0x80 == 0:
                break
        else:
            raise DomainValidationError(f"The .tmod {label} length is invalid")
        if length > max_bytes:
            raise DomainValidationError(f"The .tmod {label} is too long")
        return ModService._read_exact(file, length, label).decode("utf-8")

    @staticmethod
    def _read_exact(file: BufferedIOBase, length: int, label: str) -> bytes:
        value = file.read(length)
        if len(value) != length:
            raise DomainValidationError(f"The .tmod {label} is truncated")
        return value

    @staticmethod
    def _validate_upload_filename(filename: str | None) -> None:
        if not filename:
            raise DomainValidationError("The uploaded mod must have a filename")
        if len(filename) > 255 or any(character in filename for character in ("/", "\\", "\x00")):
            raise DomainValidationError("The uploaded mod filename is not safe")
        if Path(filename).suffix.lower() != ".tmod":
            raise DomainValidationError("Only .tmod files can be uploaded")

    @staticmethod
    def _read_enabled(path: Path) -> set[str]:
        if not path.exists():
            return set()
        try:
            content: object = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise DomainValidationError(f"Cannot read enabled.json: {error}") from error
        if not isinstance(content, list):
            raise DomainValidationError("enabled.json must be a JSON array of mod names")
        items = cast(list[object], content)
        if not all(isinstance(item, str) for item in items):
            raise DomainValidationError("enabled.json must be a JSON array of mod names")
        return {item for item in items if isinstance(item, str)}
