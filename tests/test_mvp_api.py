import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

from fastapi.testclient import TestClient

from terrapanel.app import create_app
from terrapanel.config import Settings
from terrapanel.domain.instance import InstanceRecord
from terrapanel.services.backup_service import BackupService
from terrapanel.services.container import ServiceContainer
from terrapanel.services.process_manager import ProcessManager


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


class _Client(Protocol):
    def get(self, url: str, **kwargs: object) -> _Response: ...

    def post(self, url: str, **kwargs: object) -> _Response: ...

    def patch(self, url: str, **kwargs: object) -> _Response: ...

    def put(self, url: str, **kwargs: object) -> _Response: ...

    def delete(self, url: str, **kwargs: object) -> _Response: ...


def test_mvp_api_flow(
    tmp_path: Path,
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    world = instance_root / "Worlds" / "ApiWorld.wld"
    world.write_bytes(b"api world")
    (instance_root / "Mods" / "ApiMod.tmod").write_bytes(b"api mod")

    fake_server = tmp_path / "api_fake_server.py"
    fake_server.write_text(
        """
import sys

print("API_READY", flush=True)
for line in sys.stdin:
    command = line.strip()
    print(f"API:{command}", flush=True)
    if command == "exit":
        break
""".strip(),
        encoding="utf-8",
    )

    def command_builder(_instance: InstanceRecord) -> tuple[str, ...]:
        return sys.executable, "-u", str(fake_server)

    process = ProcessManager(services.instances, command_builder)
    test_services = replace(
        services,
        process=process,
        backups=BackupService(services.instances, process, app_settings.storage.backups_dir),
    )

    with TestClient(create_app(app_settings, test_services)) as raw_client:
        client = cast(_Client, raw_client)

        instance_response = client.get("/api/v1/instance")
        assert instance_response.status_code == 200

        config_response = client.patch(
            "/api/v1/server-config",
            json={"maxplayers": 16, "port": 7778},
        )
        assert config_response.status_code == 200

        world_response = client.post("/api/v1/worlds/select", json={"path": "Worlds/ApiWorld.wld"})
        assert world_response.status_code == 200

        mod_response = client.post("/api/v1/mods/enable", json={"name": "ApiMod"})
        assert mod_response.status_code == 200

        backup_response = client.post("/api/v1/backups", json={"label": "api"})
        assert backup_response.status_code == 201

        start_response = client.post("/api/v1/instance/start")
        assert start_response.status_code == 200
        command_response = client.post("/api/v1/instance/console", json={"command": "say API"})
        assert command_response.status_code == 202
        _wait_for_api_console(client, "API:say API")

        assert client.post("/api/v1/backups", json={"label": "running"}).status_code == 409
        backup_id = str(cast(dict[str, object], backup_response.json())["id"])
        assert client.post(f"/api/v1/backups/{backup_id}/restore").status_code == 409
        assert client.delete("/api/v1/instance").status_code == 409
        assert (
            client.put(
                "/api/v1/instance",
                json={"name": "Changed", "root_dir": str(instance_root)},
            ).status_code
            == 409
        )

        stop_response = client.post("/api/v1/instance/stop?timeout_seconds=2")
        assert stop_response.status_code == 200
        _wait_for_api_console(client, "API:exit")


def test_associates_instance_through_api(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    root = app_settings.storage.servers_dir / "api-association"
    install = root / "server"
    install.mkdir(parents=True)
    (install / "start-tModLoaderServer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (install / "tModLoader.dll").write_bytes(b"assembly")

    with TestClient(create_app(app_settings, services)) as raw_client:
        client = cast(_Client, raw_client)
        response = client.put(
            "/api/v1/instance",
            json={"name": "API Association", "root_dir": "api-association"},
        )

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    assert payload["name"] == "API Association"
    assert Path(str(payload["root_dir"])) == root.resolve()


def _wait_for_api_console(client: _Client, expected: str) -> None:
    for _attempt in range(100):
        response = client.get("/api/v1/instance/console?limit=1000")
        entries = cast(list[dict[str, object]], response.json())
        if any(expected in str(entry.get("text")) for entry in entries):
            return
        time.sleep(0.01)
    raise AssertionError(f"Console output not received through API: {expected}")
