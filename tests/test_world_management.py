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
from terrapanel.services.world_service import WorldService


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


def test_uploads_selects_and_deletes_world_companions(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    uploaded = services.worlds.upload(
        [
            ("Imported.wld", io.BytesIO(_world_bytes(b"main"))),
            ("Imported.twld", io.BytesIO(b"mod data")),
        ]
    )

    assert uploaded.name == "Imported"
    assert uploaded.path == "Worlds/Imported.wld"
    assert uploaded.has_mod_data is True
    assert uploaded.selected is False

    services.worlds.select(uploaded.path)
    assert services.worlds.list()[0].selected is True
    with pytest.raises(ConflictError, match="active world"):
        services.worlds.delete("Imported")

    other = instance_root / "Worlds" / "Other.wld"
    other.write_bytes(_world_bytes(b"other"))
    services.worlds.select("Worlds/Other.wld")
    (instance_root / "Worlds" / "Imported.wld.bak").write_bytes(b"backup")
    backups = instance_root / "Worlds" / "Backups"
    backups.mkdir()
    history = backups / "2026-07-12-Imported.zip"
    history.write_bytes(b"history")

    deleted = services.worlds.delete("Imported")

    assert deleted == ["Imported.wld", "Imported.twld", "Imported.wld.bak"]
    assert history.is_file()


def test_world_upload_replace_removes_stale_mod_data_and_rejects_bad_files(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    services.worlds.upload(
        [
            ("Replace.wld", io.BytesIO(_world_bytes(b"old"))),
            ("Replace.twld", io.BytesIO(b"old mod data")),
        ]
    )
    with pytest.raises(ConflictError, match="already installed"):
        services.worlds.upload([("Replace.wld", io.BytesIO(_world_bytes(b"new")))])

    replaced = services.worlds.upload(
        [("Replace.wld", io.BytesIO(_world_bytes(b"new")))],
        replace=True,
    )

    assert replaced.has_mod_data is False
    assert (instance_root / "Worlds" / "Replace.wld").read_bytes() == _world_bytes(b"new")
    assert not (instance_root / "Worlds" / "Replace.twld").exists()

    with pytest.raises(DomainValidationError, match="version header"):
        services.worlds.upload([("Broken.wld", io.BytesIO(b"NOPE"))])
    with pytest.raises(DomainValidationError, match="filenames must match"):
        services.worlds.upload(
            [
                ("One.wld", io.BytesIO(_world_bytes())),
                ("Two.twld", io.BytesIO(b"mod")),
            ]
        )
    assert not list((instance_root / "Worlds").glob(".upload-*.tmp"))


def test_world_upload_enforces_size_and_stopped_state(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    assert instance_root.is_dir()
    limited = WorldService(
        services.instances,
        services.server_config,
        services.process,
        max_upload_size=8,
    )
    with pytest.raises(DomainValidationError, match="upload limit"):
        limited.upload([("Large.wld", io.BytesIO(_world_bytes(b"large")))])

    running = WorldService(
        services.instances,
        services.server_config,
        _RunningProcess(),
        max_upload_size=1024,
    )
    with pytest.raises(ConflictError, match="Stop the tModLoader server"):
        running.upload([("Running.wld", io.BytesIO(_world_bytes()))])


def test_world_management_api(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    with TestClient(create_app(app_settings, services)) as client:
        uploaded = cast(
            _Response,
            client.post(
                "/api/v1/worlds/upload",
                files=[
                    ("files", ("ApiWorld.wld", _world_bytes(b"api"), "application/octet-stream")),
                    ("files", ("ApiWorld.twld", b"mod data", "application/octet-stream")),
                ],
            ),
        )
        selected = cast(
            _Response,
            client.post(
                "/api/v1/worlds/select",
                json={"path": "Worlds/ApiWorld.wld"},
            ),
        )
        active_delete = cast(_Response, client.delete("/api/v1/worlds/ApiWorld"))

    assert uploaded.status_code == 201
    assert cast(dict[str, object], uploaded.json())["has_mod_data"] is True
    assert selected.status_code == 200
    assert active_delete.status_code == 409
    assert (instance_root / "Worlds" / "ApiWorld.wld").is_file()


class _RunningProcess:
    def snapshot(self) -> ProcessSnapshot:
        return ProcessSnapshot(state=ProcessState.RUNNING, pid=1234)


def _world_bytes(payload: bytes = b"world") -> bytes:
    return struct.pack("<i", 279) + payload
