import os
import re

from terrapanel.domain.errors import DomainValidationError
from terrapanel.domain.server_content import ServerConfigPatch, ServerConfigView
from terrapanel.services.instance_service import InstanceService

_ACTIVE_SETTING = re.compile(r"^\s*([^#;\s][^=]*)=(.*)$")
_PATH_FIELDS = {"world", "worldpath", "banlist", "modpath"}


class ServerConfigService:
    def __init__(self, instances: InstanceService) -> None:
        self._instances = instances

    def read(self) -> ServerConfigView:
        instance = self._instances.require()
        values: dict[str, str] = {}
        for line in instance.config_file.read_text(encoding="utf-8").splitlines():
            match = _ACTIVE_SETTING.match(line)
            if match:
                values[match.group(1).strip().lower()] = match.group(2).strip()
        return ServerConfigView(values=values)

    def update(self, patch: ServerConfigPatch) -> ServerConfigView:
        raw_values = patch.model_dump(exclude_unset=True)
        return self.set_values(raw_values)

    def set_values(self, raw_values: dict[str, object]) -> ServerConfigView:
        instance = self._instances.require()
        normalized = {
            key.lower(): self._serialize_value(key.lower(), value)
            for key, value in raw_values.items()
        }
        lines = instance.config_file.read_text(encoding="utf-8").splitlines()
        seen: set[str] = set()
        updated: list[str] = []

        for line in lines:
            match = _ACTIVE_SETTING.match(line)
            if not match:
                updated.append(line)
                continue

            key = match.group(1).strip().lower()
            if key not in normalized:
                updated.append(line)
                continue

            seen.add(key)
            value = normalized[key]
            if value is not None:
                updated.append(f"{key}={value}")

        for key, value in normalized.items():
            if key not in seen and value is not None:
                updated.append(f"{key}={value}")

        temporary = instance.config_file.with_suffix(".tmp")
        temporary.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
        os.replace(temporary, instance.config_file)
        return self.read()

    def _serialize_value(self, key: str, value: object) -> str | None:
        if value is None:
            return None
        if key in _PATH_FIELDS:
            resolved = self._instances.resolve_in_root(str(value))
            if key == "world" and resolved.suffix.lower() != ".wld":
                raise DomainValidationError("The configured world must use the .wld extension")
            return str(resolved)
        if isinstance(value, bool):
            return "1" if value else "0"
        text = str(value)
        if any(character in text for character in ("\r", "\n", "\x00")):
            raise DomainValidationError(f"Configuration value for {key} must be a single line")
        return text
