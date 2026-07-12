from collections import deque
from pathlib import Path

from terrapanel.domain.errors import DomainValidationError
from terrapanel.domain.server_content import LogView
from terrapanel.services.instance_service import InstanceService

_LOG_PATHS = {
    "console": Path("logs/console.log"),
    "server": Path("server/tModLoader-Logs/server.log"),
    "launch": Path("server/tModLoader-Logs/Launch.log"),
    "native": Path("server/tModLoader-Logs/Natives.log"),
}


class LogService:
    def __init__(self, instances: InstanceService) -> None:
        self._instances = instances

    def read(self, source: str, *, lines: int = 300) -> LogView:
        relative = _LOG_PATHS.get(source)
        if relative is None:
            raise DomainValidationError(f"Unknown log source: {source}")
        instance = self._instances.require()
        path = self._instances.resolve_in_root(relative)
        if not path.exists():
            return LogView(source=source, path=str(relative), lines=[])

        limit = max(1, min(lines, 2000))
        tail: deque[str] = deque(maxlen=limit)
        with path.open(encoding="utf-8", errors="replace") as file:
            for line in file:
                tail.append(line.rstrip("\r\n"))
        return LogView(
            source=source, path=str(path.relative_to(instance.root_dir)), lines=list(tail)
        )
