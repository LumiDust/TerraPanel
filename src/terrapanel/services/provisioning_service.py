import asyncio
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from terrapanel.domain.errors import ConflictError
from terrapanel.domain.instance import InstanceAssociation, InstanceRecord
from terrapanel.domain.process import ConsoleEntry, ProcessSnapshot
from terrapanel.domain.provisioning import (
    ProvisionRequest,
    ProvisionSnapshot,
    ProvisionStage,
    ProvisionState,
    UpdateRequest,
)
from terrapanel.repository.provision_repository import ProvisionRepository
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.official_installer import LogEmitter
from terrapanel.services.process_manager import ProcessManager
from terrapanel.services.server_config_service import ServerConfigService


class Installer(Protocol):
    async def install(
        self,
        root_dir: Path,
        version: str | None,
        emit: LogEmitter,
    ) -> None: ...


class ProvisioningService:
    def __init__(
        self,
        instances: InstanceService,
        server_config: ServerConfigService,
        process: ProcessManager,
        installer: Installer,
        repository: ProvisionRepository,
        *,
        history_limit: int = 2000,
    ) -> None:
        self._instances = instances
        self._server_config = server_config
        self._process = process
        self._installer = installer
        self._repository = repository
        self._history: deque[ConsoleEntry] = deque(maxlen=history_limit)
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._snapshot = self._restore_snapshot()

    def snapshot(self) -> ProvisionSnapshot:
        return self._snapshot

    def logs(self, *, after_sequence: int = 0, limit: int = 500) -> list[ConsoleEntry]:
        bounded_limit = max(1, min(limit, 1000))
        return [entry for entry in self._history if entry.sequence > after_sequence][
            -bounded_limit:
        ]

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def provision(self, request: ProvisionRequest) -> ProvisionSnapshot:
        async with self._lock:
            self._require_available()
            if self._instances.get() is not None:
                raise ConflictError(
                    "An instance is already configured; remove it or use the update operation"
                )
            root_dir = self._instances.prepare_root(request.root_dir)
            self._begin(
                operation="install",
                name=request.name,
                root_dir=root_dir,
                version=request.version,
            )
            self._task = asyncio.create_task(self._run_provision(request, root_dir))
            return self.snapshot()

    async def update(self, request: UpdateRequest) -> ProvisionSnapshot:
        async with self._lock:
            self._require_available()
            instance = self._instances.require()
            self._begin(
                operation="update",
                name=instance.name,
                root_dir=instance.root_dir,
                version=request.version,
            )
            self._task = asyncio.create_task(self._run_update(request, instance))
            return self.snapshot()

    async def cancel(self) -> ProvisionSnapshot:
        async with self._lock:
            task = self._task
            if task is None or task.done():
                raise ConflictError("No installation or update task is running")
            task.cancel()

        with suppress(asyncio.CancelledError):
            await task
        return self.snapshot()

    async def close(self) -> None:
        if self.is_running():
            await self.cancel()

    async def _run_provision(self, request: ProvisionRequest, root_dir: Path) -> None:
        try:
            self._set_stage(ProvisionStage.INSTALLING)
            await self._installer.install(root_dir, request.version, self._record)

            self._set_stage(ProvisionStage.ASSOCIATING)
            instance = self._instances.associate(
                InstanceAssociation(name=request.name, root_dir=str(root_dir))
            )

            self._set_stage(ProvisionStage.CONFIGURING)
            self._server_config.set_values(
                {
                    "world": root_dir / "Worlds" / f"{request.world_name}.wld",
                    "autocreate": request.world_size,
                    "worldname": request.world_name,
                    "difficulty": request.difficulty,
                    "maxplayers": request.max_players,
                    "port": request.port,
                    "password": request.password,
                    "motd": request.motd,
                    "secure": request.secure,
                    "upnp": request.upnp,
                }
            )

            process: ProcessSnapshot | None = None
            if request.start_after_install:
                self._set_stage(ProvisionStage.STARTING)
                process = await self._process.start()
            self._succeed(instance, process)
        except asyncio.CancelledError:
            self._cancelled()
            raise
        except Exception as error:
            self._fail(error)

    async def _run_update(self, request: UpdateRequest, instance: InstanceRecord) -> None:
        try:
            self._set_stage(ProvisionStage.INSTALLING)
            await self._installer.install(instance.root_dir, request.version, self._record)
            self._set_stage(ProvisionStage.ASSOCIATING)
            updated = self._instances.associate(
                InstanceAssociation(name=instance.name, root_dir=str(instance.root_dir))
            )
            process: ProcessSnapshot | None = None
            if request.start_after_update:
                self._set_stage(ProvisionStage.STARTING)
                process = await self._process.start()
            self._succeed(updated, process)
        except asyncio.CancelledError:
            self._cancelled()
            raise
        except Exception as error:
            self._fail(error)

    def _require_available(self) -> None:
        if self.is_running():
            raise ConflictError("An installation or update task is already running")
        if self._process.is_running():
            raise ConflictError("Stop the tModLoader server before installation or update")

    def _begin(
        self,
        *,
        operation: Literal["install", "update"],
        name: str,
        root_dir: Path,
        version: str | None,
    ) -> None:
        self._history.clear()
        self._sequence = 0
        self._snapshot = ProvisionSnapshot(
            state=ProvisionState.RUNNING,
            stage=ProvisionStage.PREPARING,
            operation=operation,
            name=name,
            root_dir=str(root_dir),
            version=version,
            started_at=datetime.now(UTC),
        )
        self._save()
        self._record("system", f"Starting {operation} task")

    def _set_stage(self, stage: ProvisionStage) -> None:
        self._snapshot = self._snapshot.model_copy(update={"stage": stage})
        self._save()

    def _succeed(
        self,
        instance: InstanceRecord,
        process: ProcessSnapshot | None,
    ) -> None:
        self._record("system", "Provisioning task completed")
        self._snapshot = self._snapshot.model_copy(
            update={
                "state": ProvisionState.SUCCEEDED,
                "stage": ProvisionStage.COMPLETE,
                "finished_at": datetime.now(UTC),
                "instance": instance,
                "process": process,
                "error": None,
            }
        )
        self._save()

    def _fail(self, error: Exception) -> None:
        self._record("system", f"Provisioning failed: {error}")
        self._snapshot = self._snapshot.model_copy(
            update={
                "state": ProvisionState.FAILED,
                "finished_at": datetime.now(UTC),
                "error": str(error),
            }
        )
        self._save()

    def _cancelled(self) -> None:
        self._record("system", "Provisioning task cancelled")
        self._snapshot = self._snapshot.model_copy(
            update={
                "state": ProvisionState.CANCELLED,
                "finished_at": datetime.now(UTC),
                "error": None,
            }
        )
        self._save()

    def _record(self, stream: str, text: str) -> None:
        self._sequence += 1
        self._history.append(
            ConsoleEntry(
                sequence=self._sequence,
                timestamp=datetime.now(UTC),
                stream=stream,
                text=text,
            )
        )

    def _save(self) -> None:
        self._repository.save(self._snapshot)

    def _restore_snapshot(self) -> ProvisionSnapshot:
        stored = self._repository.get()
        if stored is None:
            return ProvisionSnapshot()
        if stored.state is ProvisionState.RUNNING:
            stored = stored.model_copy(
                update={
                    "state": ProvisionState.FAILED,
                    "finished_at": datetime.now(UTC),
                    "error": (
                        "The previous provisioning task was interrupted by application restart"
                    ),
                }
            )
            self._repository.save(stored)
        return stored
