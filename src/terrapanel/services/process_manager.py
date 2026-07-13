import asyncio
import logging
import os
import platform
import signal
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from terrapanel.domain.errors import (
    ConflictError,
    DomainValidationError,
    UnsupportedPlatformError,
)
from terrapanel.domain.instance import InstanceRecord
from terrapanel.domain.process import ConsoleEntry, ProcessSnapshot, ProcessState
from terrapanel.services.instance_service import InstanceService

type CommandBuilder = Callable[[InstanceRecord], Sequence[str]]
type ConfigFileResolver = Callable[[], Path]

_LOGGER = logging.getLogger("uvicorn.error")


def build_linux_launch_command(instance: InstanceRecord) -> Sequence[str]:
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"amd64", "x86_64"}:
        raise UnsupportedPlatformError(
            "tModLoader server execution currently requires Linux x86_64, "
            f"got {platform.system()} {machine}"
        )

    return (
        "bash",
        str(instance.launch_script),
        "-nosteam",
        "-config",
        str(instance.config_file),
        "-tmlsavedirectory",
        str(instance.root_dir),
        "-steamworkshopfolder",
        str(instance.root_dir / "steamapps" / "workshop"),
    )


class ProcessManager:
    def __init__(
        self,
        instances: InstanceService,
        command_builder: CommandBuilder = build_linux_launch_command,
        *,
        config_file_resolver: ConfigFileResolver | None = None,
        history_limit: int = 2000,
    ) -> None:
        self._instances = instances
        self._command_builder = command_builder
        self._config_file_resolver = config_file_resolver
        self._history: deque[ConsoleEntry] = deque(maxlen=history_limit)
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._state = ProcessState.STOPPED
        self._started_at: datetime | None = None
        self._exit_code: int | None = None
        self._stop_requested = False
        self._console_log: Path | None = None

    async def start(self) -> ProcessSnapshot:
        async with self._lock:
            if self._is_running():
                raise ConflictError("The tModLoader server is already running")

            instance = self._instances.require()
            launch_instance = instance
            if self._config_file_resolver is not None:
                launch_instance = instance.model_copy(
                    update={"config_file": self._config_file_resolver()}
                )
            command = tuple(self._command_builder(launch_instance))
            if not command:
                raise DomainValidationError("The launch command is empty")

            self._state = ProcessState.STARTING
            self._exit_code = None
            self._stop_requested = False
            self._console_log = self._instances.resolve_in_root("logs/console.log")
            self._console_log.parent.mkdir(parents=True, exist_ok=True)
            self._record("system", "Starting tModLoader server")

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=instance.install_dir,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
            except OSError as error:
                self._state = ProcessState.FAILED
                self._record("system", f"Failed to start server: {error}")
                raise DomainValidationError(f"Failed to start tModLoader: {error}") from error

            self._process = process
            self._started_at = datetime.now(UTC)
            self._state = ProcessState.RUNNING
            self._reader_task = asyncio.create_task(self._read_output(process))
            return self.snapshot()

    async def stop(self, *, timeout_seconds: float = 30.0) -> ProcessSnapshot:
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None:
                self._state = ProcessState.STOPPED
                return self.snapshot()

            self._state = ProcessState.STOPPING
            self._stop_requested = True
            self._record("system", "Stopping tModLoader server")
            await self._write_command(process, "exit")

            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            except TimeoutError:
                self._record("system", "Graceful stop timed out; sending SIGTERM")
                self._terminate(process)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    self._record("system", "SIGTERM timed out; killing process")
                    self._kill(process)
                    await process.wait()

            self._exit_code = process.returncode
            self._state = ProcessState.STOPPED
            if self._reader_task is not None:
                await asyncio.wait_for(asyncio.shield(self._reader_task), timeout=2.0)
            return self.snapshot()

    async def send_command(self, command: str) -> None:
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None:
                raise ConflictError("The tModLoader server is not running")
            await self._write_command(process, command)

    def snapshot(self) -> ProcessSnapshot:
        process = self._process
        if (
            process is not None
            and process.returncode is not None
            and self._state
            in {
                ProcessState.RUNNING,
                ProcessState.STARTING,
            }
        ):
            self._exit_code = process.returncode
            self._state = ProcessState.FAILED if process.returncode else ProcessState.STOPPED

        return ProcessSnapshot(
            state=self._state,
            pid=process.pid if process is not None and process.returncode is None else None,
            started_at=self._started_at,
            exit_code=self._exit_code,
        )

    def console(self, *, after_sequence: int = 0, limit: int = 500) -> list[ConsoleEntry]:
        bounded_limit = max(1, min(limit, 1000))
        return [entry for entry in self._history if entry.sequence > after_sequence][
            -bounded_limit:
        ]

    def is_running(self) -> bool:
        return self._is_running()

    async def close(self) -> None:
        if self._is_running():
            await self.stop(timeout_seconds=10.0)

    def _is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _write_command(self, process: asyncio.subprocess.Process, command: str) -> None:
        if not command.strip():
            raise DomainValidationError("Console command cannot be blank")
        if any(character in command for character in ("\r", "\n", "\x00")):
            raise DomainValidationError("Console command must contain exactly one line")
        if len(command) > 2048:
            raise DomainValidationError("Console command is too long")
        if process.stdin is None or process.stdin.is_closing():
            raise ConflictError("The server console is not available")

        process.stdin.write(f"{command}\n".encode())
        await process.stdin.drain()

    async def _read_output(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is not None:
            while line := await process.stdout.readline():
                self._record("stdout", line.decode(errors="replace").rstrip("\r\n"))

        exit_code = await process.wait()
        if self._process is process:
            self._exit_code = exit_code
            if self._stop_requested or exit_code == 0:
                self._state = ProcessState.STOPPED
            else:
                self._state = ProcessState.FAILED
            self._record("system", f"Server exited with code {exit_code}")

    def _record(self, stream: str, text: str) -> None:
        self._sequence += 1
        entry = ConsoleEntry(
            sequence=self._sequence,
            timestamp=datetime.now(UTC),
            stream=stream,
            text=text,
        )
        self._history.append(entry)
        _LOGGER.info("[server:%s] %s", stream, text)

        if self._console_log is not None:
            with self._console_log.open("a", encoding="utf-8") as file:
                file.write(f"{entry.timestamp.isoformat()} [{stream}] {text}\n")

    @staticmethod
    def _terminate(process: asyncio.subprocess.Process) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
