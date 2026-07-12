from pathlib import Path
from typing import Protocol, cast

from fastapi.testclient import TestClient

from terrapanel.app import create_app
from terrapanel.config import Settings
from terrapanel.services.container import ServiceContainer


class _Response(Protocol):
    status_code: int
    content: bytes


def test_deletes_local_mod_through_api(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    mod = instance_root / "Mods" / "DeleteMe.tmod"
    mod.write_bytes(b"mod")

    with TestClient(create_app(app_settings, services)) as client:
        response = cast(_Response, client.delete("/api/v1/mods/local/DeleteMe"))

    assert response.status_code == 204
    assert not mod.exists()


def test_downloads_and_deletes_backup_through_api(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    (instance_root / "Worlds" / "Example.wld").write_bytes(b"world")
    backup = services.backups.create("download")

    with TestClient(create_app(app_settings, services)) as client:
        downloaded = cast(
            _Response,
            client.get(f"/api/v1/backups/{backup.id}/download"),
        )
        deleted = cast(_Response, client.delete(f"/api/v1/backups/{backup.id}"))
        missing = cast(
            _Response,
            client.get(f"/api/v1/backups/{backup.id}/download"),
        )

    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert deleted.status_code == 204
    assert missing.status_code == 404
