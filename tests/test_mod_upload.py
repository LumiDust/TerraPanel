import hashlib
import io
import struct
from pathlib import Path
from typing import Protocol, cast

import pytest
from fastapi.testclient import TestClient

from terrapanel.app import create_app
from terrapanel.config import Settings
from terrapanel.domain.errors import ConflictError, DomainValidationError
from terrapanel.domain.process import ProcessSnapshot, ProcessState
from terrapanel.services.container import ServiceContainer
from terrapanel.services.mod_service import ModService


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


def test_uploads_valid_tmod_using_internal_name(
    instance_root: Path, services: ServiceContainer
) -> None:
    package = _make_tmod("CanonicalMod", version="2.1")

    uploaded = services.mods.upload("renamed-package.tmod", io.BytesIO(package))

    assert uploaded.name == "CanonicalMod"
    assert uploaded.file == "Mods/CanonicalMod.tmod"
    assert uploaded.enabled is False
    assert (instance_root / uploaded.file).read_bytes() == package
    assert services.mods.list() == [uploaded]


def test_rejects_invalid_hash_and_cleans_temporary_file(
    instance_root: Path, services: ServiceContainer
) -> None:
    package = bytearray(_make_tmod("BrokenMod"))
    package[-1] ^= 0xFF

    with pytest.raises(DomainValidationError, match="SHA-1"):
        services.mods.upload("BrokenMod.tmod", io.BytesIO(package))

    assert not list((instance_root / "Mods").glob(".upload-*.tmp"))
    assert not (instance_root / "Mods" / "BrokenMod.tmod").exists()


def test_enforces_size_conflict_replace_and_process_state(
    instance_root: Path, services: ServiceContainer
) -> None:
    package = _make_tmod("ReplaceMod", version="1.0")
    services.mods.upload("ReplaceMod.tmod", io.BytesIO(package))

    with pytest.raises(ConflictError, match="already installed"):
        services.mods.upload("ReplaceMod.tmod", io.BytesIO(package))

    replacement = _make_tmod("ReplaceMod", version="2.0")
    services.mods.upload("ReplaceMod.tmod", io.BytesIO(replacement), replace=True)
    assert (instance_root / "Mods" / "ReplaceMod.tmod").read_bytes() == replacement

    limited = ModService(services.instances, services.process, max_upload_size=8)
    with pytest.raises(DomainValidationError, match="upload limit"):
        limited.upload("LargeMod.tmod", io.BytesIO(_make_tmod("LargeMod")))

    running = ModService(services.instances, _RunningProcess(), max_upload_size=len(package))
    with pytest.raises(ConflictError, match="Stop the tModLoader server"):
        running.upload("RunningMod.tmod", io.BytesIO(_make_tmod("RunningMod")))


def test_upload_api_supports_explicit_replace(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    package = _make_tmod("ApiUploadMod")

    with TestClient(create_app(app_settings, services)) as client:
        created = cast(
            _Response,
            client.post(
                "/api/v1/mods/upload",
                files={"file": ("incoming.tmod", package, "application/octet-stream")},
            ),
        )
        conflict = cast(
            _Response,
            client.post(
                "/api/v1/mods/upload",
                files={"file": ("incoming.tmod", package, "application/octet-stream")},
            ),
        )
        replaced = cast(
            _Response,
            client.post(
                "/api/v1/mods/upload?replace=true",
                files={"file": ("incoming.tmod", package, "application/octet-stream")},
            ),
        )
        invalid_extension = cast(
            _Response,
            client.post(
                "/api/v1/mods/upload",
                files={"file": ("incoming.zip", package, "application/zip")},
            ),
        )

    assert created.status_code == 201
    assert cast(dict[str, object], created.json())["name"] == "ApiUploadMod"
    assert conflict.status_code == 409
    assert replaced.status_code == 201
    assert invalid_extension.status_code == 422
    assert (instance_root / "Mods" / "ApiUploadMod.tmod").is_file()


class _RunningProcess:
    def snapshot(self) -> ProcessSnapshot:
        return ProcessSnapshot(state=ProcessState.RUNNING, pid=1234)


def _make_tmod(name: str, *, version: str = "1.0") -> bytes:
    payload = _dotnet_string(name) + _dotnet_string(version) + struct.pack("<i", 0)
    digest = hashlib.sha1(payload, usedforsecurity=False).digest()
    return (
        b"TMOD"
        + _dotnet_string("2026.5.3.0")
        + digest
        + bytes(256)
        + struct.pack("<i", len(payload))
        + payload
    )


def _dotnet_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    length = len(encoded)
    prefix = bytearray()
    while length >= 0x80:
        prefix.append((length & 0x7F) | 0x80)
        length >>= 7
    prefix.append(length)
    return bytes(prefix) + encoded
