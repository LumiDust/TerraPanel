from pathlib import Path
from typing import Protocol, cast

from fastapi.testclient import TestClient

from terrapanel.app import create_app
from terrapanel.config import Settings, StorageSettings


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


def test_health_endpoint_and_directory_initialization(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        storage=StorageSettings(
            data_dir=tmp_path,
            servers_dir=tmp_path / "servers",
            backups_dir=tmp_path / "backups",
        ),
    )

    with TestClient(create_app(settings)) as client:
        response = cast(
            _Response,
            client.get("/api/v1/health"),  # pyright: ignore[reportUnknownMemberType]
        )
        frontend = cast(
            _Response,
            client.get("/"),  # pyright: ignore[reportUnknownMemberType]
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "terrapanel",
        "version": "0.1.0",
    }
    assert (tmp_path / "servers").is_dir()
    assert (tmp_path / "backups").is_dir()
    assert frontend.status_code == 200
