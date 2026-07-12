import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

import pytest
from fastapi.testclient import TestClient

from terrapanel.app import create_app
from terrapanel.config import Settings
from terrapanel.domain.errors import ConflictError, DomainValidationError
from terrapanel.domain.provisioning import (
    ProvisionRequest,
    ProvisionSnapshot,
    ProvisionStage,
    ProvisionState,
    UpdateRequest,
)
from terrapanel.repository.provision_repository import ProvisionRepository
from terrapanel.services.container import ServiceContainer
from terrapanel.services.official_installer import LogEmitter, OfficialGithubInstaller
from terrapanel.services.provisioning_service import ProvisioningService


class _FakeInstaller:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str | None]] = []

    async def install(
        self,
        root_dir: Path,
        version: str | None,
        emit: LogEmitter,
    ) -> None:
        self.calls.append((root_dir, version))
        emit("stdout", "fake download complete")
        install = root_dir / "server"
        install.mkdir(parents=True, exist_ok=True)
        (install / "start-tModLoaderServer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (install / "tModLoader.dll").write_bytes(b"assembly")


class _BlockingInstaller:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def install(
        self,
        root_dir: Path,
        version: str | None,
        emit: LogEmitter,
    ) -> None:
        del root_dir, version, emit
        self.started.set()
        await asyncio.Event().wait()


class _FailingInstaller:
    async def install(
        self,
        root_dir: Path,
        version: str | None,
        emit: LogEmitter,
    ) -> None:
        del root_dir, version, emit
        raise DomainValidationError("download failed")


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


def _service(
    app_settings: Settings,
    services: ServiceContainer,
    installer: _FakeInstaller | _BlockingInstaller | _FailingInstaller,
) -> ProvisioningService:
    return ProvisioningService(
        services.instances,
        services.server_config,
        services.process,
        installer,
        ProvisionRepository(app_settings.storage.data_dir / "test-provisioning.json"),
    )


async def _wait_for_completion(service: ProvisioningService) -> ProvisionSnapshot:
    for _attempt in range(200):
        if not service.is_running():
            return service.snapshot()
        await asyncio.sleep(0.005)
    raise AssertionError("Provisioning task did not complete")


def test_provisions_associates_and_configures_instance(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    installer = _FakeInstaller()
    service = _service(app_settings, services, installer)
    request = ProvisionRequest(
        name="Installed Server",
        root_dir="installed",
        version="v2026.07.1.0",
        world_name="NewWorld",
        world_size=2,
        difficulty=3,
        max_players=12,
        port=7788,
        start_after_install=False,
    )

    async def exercise() -> None:
        accepted = await service.provision(request)
        assert accepted.state is ProvisionState.RUNNING
        completed = await _wait_for_completion(service)
        assert completed.state is ProvisionState.SUCCEEDED
        assert completed.instance is not None

    asyncio.run(exercise())
    instance = services.instances.require()
    assert instance.name == "Installed Server"
    assert installer.calls == [(instance.root_dir, "v2026.07.1.0")]
    values = services.server_config.read().values
    assert values["world"] == str(instance.root_dir / "Worlds" / "NewWorld.wld")
    assert values["worldname"] == "NewWorld"
    assert values["autocreate"] == "2"
    assert values["difficulty"] == "3"
    assert values["maxplayers"] == "12"
    assert values["port"] == "7788"
    assert any("fake download" in entry.text for entry in service.logs())


def test_rejects_parallel_task_and_supports_cancel(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    installer = _BlockingInstaller()
    service = _service(app_settings, services, installer)
    request = ProvisionRequest(root_dir="blocked", start_after_install=False)

    async def exercise() -> None:
        await service.provision(request)
        await installer.started.wait()
        with pytest.raises(ConflictError, match="already running"):
            await service.provision(request)
        cancelled = await service.cancel()
        assert cancelled.state is ProvisionState.CANCELLED

    asyncio.run(exercise())


def test_persists_failed_task(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    repository = ProvisionRepository(app_settings.storage.data_dir / "failed-provisioning.json")
    service = ProvisioningService(
        services.instances,
        services.server_config,
        services.process,
        _FailingInstaller(),
        repository,
    )

    async def exercise() -> None:
        await service.provision(
            ProvisionRequest(root_dir="failed", start_after_install=False)
        )
        completed = await _wait_for_completion(service)
        assert completed.state is ProvisionState.FAILED
        assert completed.error == "download failed"

    asyncio.run(exercise())
    restored = ProvisioningService(
        services.instances,
        services.server_config,
        services.process,
        _FailingInstaller(),
        repository,
    )
    assert restored.snapshot().state is ProvisionState.FAILED


def test_restores_snapshot_with_current_instance_paths(
    app_settings: Settings,
    services: ServiceContainer,
    instance_root: Path,
) -> None:
    current = services.instances.require()
    legacy_root = Path("/var/lib/terrapanel/servers/primary")
    legacy = current.model_copy(
        update={
            "root_dir": legacy_root,
            "install_dir": legacy_root / "server",
            "launch_script": legacy_root / "server" / "start-tModLoaderServer.sh",
            "config_file": legacy_root / "serverconfig.txt",
        }
    )
    repository = ProvisionRepository(app_settings.storage.data_dir / "restored-paths.json")
    repository.save(
        ProvisionSnapshot(
            state=ProvisionState.SUCCEEDED,
            stage=ProvisionStage.COMPLETE,
            operation="install",
            root_dir=legacy_root.as_posix(),
            instance=legacy,
        )
    )

    restored = ProvisioningService(
        services.instances,
        services.server_config,
        services.process,
        _FailingInstaller(),
        repository,
    )

    assert restored.snapshot().instance == current
    assert restored.snapshot().root_dir == str(instance_root.resolve())
    assert repository.get() == restored.snapshot()


def test_updates_existing_instance(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    installer = _FakeInstaller()
    service = _service(app_settings, services, installer)

    async def exercise() -> None:
        await service.update(
            UpdateRequest(version="v2026.07.2.0", start_after_update=False)
        )
        completed = await _wait_for_completion(service)
        assert completed.state is ProvisionState.SUCCEEDED

    asyncio.run(exercise())
    assert installer.calls == [(instance_root.resolve(), "v2026.07.2.0")]


def test_official_installer_builds_allowlisted_command(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    script = root / "manage-tModLoaderServer.sh"
    assert OfficialGithubInstaller.build_command(root, script, "v2026.07.1.0") == (
        "bash",
        str(script),
        "install-tml",
        "--github",
        "--folder",
        str(root),
        "--tmlversion",
        "v2026.07.1.0",
    )


def test_provisioning_api_accepts_and_reports_task(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    provisioning = _service(app_settings, services, _FakeInstaller())
    test_services = replace(services, provisioning=provisioning)
    with TestClient(create_app(app_settings, test_services)) as client:
        response = cast(
            _Response,
            client.post(
                "/api/v1/provisioning",
                json={
                    "name": "API Installed",
                    "root_dir": "api-installed",
                    "world_name": "ApiWorld",
                    "start_after_install": False,
                },
            ),
        )
        assert response.status_code == 202
        for _attempt in range(100):
            status_response = cast(_Response, client.get("/api/v1/provisioning"))
            payload = cast(dict[str, object], status_response.json())
            if payload["state"] != "running":
                break
            import time

            time.sleep(0.01)
        else:
            raise AssertionError("API provisioning task did not complete")

    assert payload["state"] == "succeeded"
    assert services.instances.require().name == "API Installed"


def test_provisioning_api_blocks_conflicting_operations(
    app_settings: Settings,
    services: ServiceContainer,
) -> None:
    provisioning = _service(app_settings, services, _BlockingInstaller())
    test_services = replace(services, provisioning=provisioning)
    with TestClient(create_app(app_settings, test_services)) as client:
        accepted = client.post(
            "/api/v1/provisioning",
            json={"root_dir": "blocking-api", "start_after_install": False},
        )
        assert accepted.status_code == 202
        assert client.post("/api/v1/instance/start").status_code == 409
        assert client.delete("/api/v1/instance").status_code == 409
        assert client.post("/api/v1/backups", json={"label": "blocked"}).status_code == 409
        cancelled = client.post("/api/v1/provisioning/cancel")
        assert cancelled.status_code == 200
        assert cast(dict[str, object], cancelled.json())["state"] == "cancelled"
