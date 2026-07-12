import asyncio
import hashlib
import os
import platform
import shutil
import signal
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from terrapanel.domain.errors import DomainValidationError, UnsupportedPlatformError

type LogEmitter = Callable[[str, str], None]

_SCRIPT_COMMIT = "d30c8441594cf857d5779aa551ec242efb1bb968"
_SCRIPT_SHA256 = "04649c407295852eec3830f5d5670662925082721abc430554d16fae4e70fbdc"
_SCRIPT_URL = (
    "https://raw.githubusercontent.com/tModLoader/tModLoader/"
    f"{_SCRIPT_COMMIT}/patches/tModLoader/Terraria/release_extras/"
    "DedicatedServerUtils/manage-tModLoaderServer.sh"
)
_REQUIRED_COMMANDS = ("bash", "curl", "tar", "unzip")


class OfficialGithubInstaller:
    async def install(
        self,
        root_dir: Path,
        version: str | None,
        emit: LogEmitter,
    ) -> None:
        self._validate_platform()
        missing = [command for command in _REQUIRED_COMMANDS if shutil.which(command) is None]
        if missing:
            raise DomainValidationError(
                "Missing required host commands: " + ", ".join(missing)
            )

        emit("system", "Downloading the verified tModLoader management script")
        script = root_dir / "manage-tModLoaderServer.sh"
        await asyncio.to_thread(self._download_script, script)
        command = self.build_command(root_dir, script, version)
        emit("system", "Installing tModLoader and its matching .NET runtime")
        await self._run(command, root_dir, emit)

    @staticmethod
    def build_command(
        root_dir: Path,
        script: Path,
        version: str | None,
    ) -> Sequence[str]:
        command = [
            "bash",
            str(script),
            "install-tml",
            "--github",
            "--folder",
            str(root_dir),
        ]
        if version is not None:
            command.extend(("--tmlversion", version))
        return tuple(command)

    @staticmethod
    def _validate_platform() -> None:
        machine = platform.machine().lower()
        if platform.system() != "Linux" or machine not in {"amd64", "x86_64"}:
            raise UnsupportedPlatformError(
                "Automatic tModLoader installation currently requires Linux x86_64, "
                f"got {platform.system()} {machine}"
            )

    @staticmethod
    def _download_script(destination: Path) -> None:
        request = urllib.request.Request(
            _SCRIPT_URL,
            headers={"User-Agent": "TerraPanel/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read(1024 * 1024)
        except OSError as error:
            raise DomainValidationError(
                f"Failed to download the official management script: {error}"
            ) from error

        digest = hashlib.sha256(content).hexdigest()
        if digest != _SCRIPT_SHA256:
            raise DomainValidationError(
                "The downloaded management script failed SHA-256 verification"
            )

        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o755)
        os.replace(temporary, destination)

    @staticmethod
    async def _run(command: Sequence[str], cwd: Path, emit: LogEmitter) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            raise DomainValidationError(
                f"Failed to launch the tModLoader installer: {error}"
            ) from error

        try:
            if process.stdout is not None:
                while line := await process.stdout.readline():
                    emit("stdout", line.decode(errors="replace").rstrip("\r\n"))
            exit_code = await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                OfficialGithubInstaller._terminate(process)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    OfficialGithubInstaller._kill(process)
                    await process.wait()
            raise

        if exit_code != 0:
            raise DomainValidationError(f"tModLoader installer exited with code {exit_code}")

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
