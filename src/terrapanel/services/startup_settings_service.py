import re
import shlex
from pathlib import Path

from terrapanel.domain.errors import ConflictError
from terrapanel.domain.startup import SpamCheckStatus
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.log_service import LogService
from terrapanel.services.server_config_service import ServerConfigService

_SECURE_ARGUMENT = re.compile(r"(?<![\w-])-secure(?![\w-])", re.IGNORECASE)
_SECURE_TRUE = {"1", "true", "yes", "on"}
_SECURE_FALSE = {"0", "false", "no", "off"}
_LOG_SOURCES = ("console", "server", "launch", "native")
_MAX_SCRIPT_INSPECTION_SIZE = 512 * 1024


class StartupSettingsService:
    def __init__(
        self,
        instances: InstanceService,
        server_config: ServerConfigService,
        logs: LogService,
    ) -> None:
        self._instances = instances
        self._server_config = server_config
        self._logs = logs

    def spam_check(self) -> SpamCheckStatus:
        instance = self._instances.require()
        config_path: str | None = None
        secure_value: str | None = None
        try:
            active_config = self._server_config.active_config_path()
        except ConflictError:
            pass
        else:
            config_path = active_config.relative_to(instance.root_dir).as_posix()
            secure_value = self._server_config.read().values.get("secure")

        secure_enabled = self._parse_secure(secure_value)
        script_path = self._instances.resolve_in_root(instance.launch_script, must_exist=True)
        inspected, secure_argument = self._inspect_launch_script(script_path)
        matches, sources = self._projectile_spam_matches()
        return SpamCheckStatus(
            config_path=config_path,
            secure_value=secure_value,
            secure_configured=secure_value is not None,
            secure_enabled=secure_enabled,
            launch_script_path=script_path.relative_to(instance.root_dir).as_posix(),
            launch_script_inspected=inspected,
            secure_launch_argument=secure_argument,
            projectile_spam_matches=matches,
            projectile_spam_sources=sources,
            protection_disabled=secure_enabled is False and not secure_argument,
        )

    def disable_spam_check(self) -> SpamCheckStatus:
        self._server_config.set_values({"secure": False})
        return self.spam_check()

    @staticmethod
    def _parse_secure(value: str | None) -> bool | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if normalized in _SECURE_TRUE:
            return True
        if normalized in _SECURE_FALSE:
            return False
        return None

    @staticmethod
    def _inspect_launch_script(path: Path) -> tuple[bool, bool]:
        try:
            if path.stat().st_size > _MAX_SCRIPT_INSPECTION_SIZE:
                return False, False
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError, UnicodeDecodeError:
            return False, False

        for line in lines:
            stripped = line.lstrip()
            if (
                not stripped
                or stripped.startswith(("#", "::"))
                or re.match(r"(?i)^rem(?:\s|$)", stripped)
            ):
                continue
            try:
                active = " ".join(shlex.split(line, comments=True, posix=True))
            except ValueError:
                active = line
            if _SECURE_ARGUMENT.search(active):
                return True, True
        return True, False

    def _projectile_spam_matches(self) -> tuple[int, list[str]]:
        matches = 0
        sources: list[str] = []
        for source in _LOG_SOURCES:
            view = self._logs.read(source, lines=2000)
            source_matches = sum(line.casefold().count("projectile spam") for line in view.lines)
            if source_matches:
                sources.append(source)
                matches += source_matches
        return matches, sources
