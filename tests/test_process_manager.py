import asyncio
import sys
from pathlib import Path

import pytest

from terrapanel.domain.errors import DomainValidationError
from terrapanel.domain.instance import InstanceRecord
from terrapanel.domain.process import ProcessState
from terrapanel.services.container import ServiceContainer
from terrapanel.services.process_manager import ProcessManager


def test_process_lifecycle_and_console(
    tmp_path: Path,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    fake_server = tmp_path / "fake_server.py"
    fake_server.write_text(
        """
import sys

print("READY", flush=True)
for line in sys.stdin:
    command = line.strip()
    print(f"ECHO:{command}", flush=True)
    if command == "exit":
        break
""".strip(),
        encoding="utf-8",
    )

    def command_builder(_instance: InstanceRecord) -> tuple[str, ...]:
        return sys.executable, "-u", str(fake_server)

    manager = ProcessManager(services.instances, command_builder)

    async def exercise() -> None:
        started = await manager.start()
        assert started.state is ProcessState.RUNNING
        await _wait_for_console(manager, "READY")
        await manager.send_command("say hello")
        await _wait_for_console(manager, "ECHO:say hello")

        with pytest.raises(DomainValidationError):
            await manager.send_command("first\nsecond")

        stopped = await manager.stop(timeout_seconds=2)
        assert stopped.state is ProcessState.STOPPED
        await _wait_for_console(manager, "ECHO:exit")

    asyncio.run(exercise())
    assert "ECHO:say hello" in (instance_root / "logs" / "console.log").read_text()


async def _wait_for_console(manager: ProcessManager, expected: str) -> None:
    for _attempt in range(100):
        if any(expected in entry.text for entry in manager.console(limit=1000)):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Console output not received: {expected}")


def test_start_failure_is_reported(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    manager = ProcessManager(
        services.instances,
        lambda _instance: ("definitely-not-a-terrapanel-command",),
    )

    async def exercise() -> None:
        with pytest.raises(DomainValidationError, match="Failed to start"):
            await manager.start()
        assert manager.snapshot().state is ProcessState.FAILED

    asyncio.run(exercise())


def test_unexpected_process_exit_is_failed(
    tmp_path: Path,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    fake_server = tmp_path / "failing_server.py"
    fake_server.write_text(
        "import sys\nprint('CRASH', flush=True)\nsys.exit(7)\n",
        encoding="utf-8",
    )
    manager = ProcessManager(
        services.instances,
        lambda _instance: (sys.executable, "-u", str(fake_server)),
    )

    async def exercise() -> None:
        await manager.start()
        await _wait_for_console(manager, "Server exited with code 7")
        snapshot = manager.snapshot()
        assert snapshot.state is ProcessState.FAILED
        assert snapshot.exit_code == 7

    asyncio.run(exercise())
