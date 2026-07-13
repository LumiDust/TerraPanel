import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import cast

from terrapanel.domain.errors import ConflictError, DomainValidationError
from terrapanel.domain.server_content import ServerConfigPatch, ServerConfigView
from terrapanel.services.instance_service import InstanceService

_ACTIVE_SETTING = re.compile(r"^\s*([^#;\s][^=]*)=(.*)$")
_PATH_FIELDS = {"world", "worldpath", "banlist", "modpath"}
_PROFILE_DIRECTORY = "WorldConfigs"
_SELECTION_FILE = "active.json"


class ServerConfigService:
    def __init__(self, instances: InstanceService) -> None:
        self._instances = instances
        self._lock = RLock()

    def read(self) -> ServerConfigView:
        with self._lock:
            active = self._active_profile(migrate=True)
            path = active[1] if active is not None else self._instances.require().config_file
            return self._read_path(path)

    def update(self, patch: ServerConfigPatch) -> ServerConfigView:
        raw_values = patch.model_dump(exclude_unset=True)
        if {"world", "worldname"} & raw_values.keys():
            raise DomainValidationError("Use the world management API to change worlds")
        return self.set_values(raw_values)

    def set_values(self, raw_values: dict[str, object]) -> ServerConfigView:
        with self._lock:
            return self._set_values_in_path(self.active_config_path(), raw_values)

    def selected_world(self) -> Path | None:
        with self._lock:
            active = self._active_profile(migrate=True)
            return active[0] if active is not None else None

    def active_config_path(self) -> Path:
        with self._lock:
            active = self._active_profile(migrate=True)
            if active is None:
                raise ConflictError("Select or import a world before starting the server")
            return active[1]

    def select_world(self, world: str | Path) -> ServerConfigView:
        with self._lock:
            selected = self._validate_world_path(world, must_exist=False)
            profile = self._profile_path(selected)
            if selected.exists():
                profile = self._ensure_profile(selected)
            elif not profile.exists():
                raise DomainValidationError("The selected world does not exist")
            self._set_values_in_path(
                profile,
                {"world": selected, "worldname": selected.stem},
            )
            self._write_selection(selected)
            return self._read_path(profile)

    def world_profile_exists(self, world: str | Path) -> bool:
        with self._lock:
            target = self._validate_world_path(world, must_exist=False)
            profile = self._profile_path(target)
            if not profile.exists():
                return False
            managed = self._instances.resolve_in_root(profile, must_exist=True)
            if not managed.is_file():
                raise DomainValidationError(
                    f"World configuration is not a regular file: {managed.name}"
                )
            return True

    def world_profiles(self) -> list[tuple[Path, Path, ServerConfigView]]:
        with self._lock:
            profiles: list[tuple[Path, Path, ServerConfigView]] = []
            for candidate in sorted(
                self._profile_directory().glob("*.txt"),
                key=lambda path: path.name.casefold(),
            ):
                managed = self._instances.resolve_in_root(candidate, must_exist=True)
                if not managed.is_file():
                    continue
                view = self._read_path(managed)
                configured = view.values.get("world")
                if not configured:
                    continue
                try:
                    world = self._validate_world_path(configured, must_exist=False)
                except DomainValidationError:
                    continue
                if self._profile_path(world) != managed:
                    continue
                profiles.append((world, managed, view))
            return profiles

    def create_world_profile(
        self,
        world: str | Path,
        values: dict[str, object] | None = None,
        *,
        select: bool = False,
    ) -> ServerConfigView:
        with self._lock:
            target = self._validate_world_path(world, must_exist=False)
            profile = self._ensure_profile(target)
            updates = dict(values or {})
            updates.update({"world": target, "worldname": target.stem})
            view = self._set_values_in_path(profile, updates)
            if select:
                self._write_selection(target)
            return view

    def ensure_world_profile(self, world: str | Path) -> ServerConfigView:
        with self._lock:
            target = self._validate_world_path(world, must_exist=True)
            profile = self._profile_path(target)
            if profile.exists():
                managed = self._instances.resolve_in_root(profile, must_exist=True)
                if not managed.is_file():
                    raise DomainValidationError(
                        f"World configuration is not a regular file: {managed.name}"
                    )
                return self._read_path(managed)
            profile = self._ensure_profile(target)
            return self._set_values_in_path(
                profile,
                {"world": target, "worldname": target.stem},
            )

    def delete_world_profile(self, world: str | Path) -> None:
        with self._lock:
            target = self._validate_world_path(world, must_exist=False)
            active = self._active_profile(migrate=False)
            if active is not None and active[0] == target:
                self._selection_path().unlink(missing_ok=True)

            profile = self._profile_path(target)
            if profile.exists():
                managed = self._instances.resolve_in_root(profile, must_exist=True)
                if not managed.is_file():
                    raise DomainValidationError(
                        f"World configuration is not a regular file: {managed.name}"
                    )
                managed.unlink()

    def _active_profile(self, *, migrate: bool) -> tuple[Path, Path] | None:
        selection = self._selection_path()
        if migrate and not selection.exists():
            self._migrate_legacy_profile()
        if not selection.exists():
            return None

        managed_selection = self._instances.resolve_in_root(selection, must_exist=True)
        if not managed_selection.is_file():
            raise DomainValidationError("The active world selection is not a regular file")
        try:
            raw_payload: object = json.loads(
                managed_selection.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise DomainValidationError("The active world selection is invalid") from error
        if not isinstance(raw_payload, dict):
            raise DomainValidationError("The active world selection is invalid")
        payload = cast(dict[str, object], raw_payload)
        relative_world = payload.get("world")
        if not isinstance(relative_world, str):
            raise DomainValidationError("The active world selection is invalid")

        world = self._validate_world_path(relative_world, must_exist=False)
        profile = self._profile_path(world)
        if not profile.exists():
            raise DomainValidationError(
                f"The active world configuration does not exist: {profile.name}"
            )
        managed_profile = self._instances.resolve_in_root(profile, must_exist=True)
        if not managed_profile.is_file():
            raise DomainValidationError(
                f"The active world configuration is not a regular file: {profile.name}"
            )
        return world, managed_profile

    def _migrate_legacy_profile(self) -> None:
        instance = self._instances.require()
        values = self._read_path(instance.config_file).values
        configured = values.get("world")
        if not configured:
            return
        try:
            world = self._validate_world_path(configured, must_exist=True)
        except (DomainValidationError, FileNotFoundError):
            return
        profile = self._ensure_profile(world)
        self._set_values_in_path(profile, {"world": world, "worldname": world.stem})
        self._write_selection(world)

    def _ensure_profile(self, world: Path) -> Path:
        profile = self._profile_path(world)
        if profile.exists():
            managed = self._instances.resolve_in_root(profile, must_exist=True)
            if not managed.is_file():
                raise DomainValidationError(
                    f"World configuration is not a regular file: {managed.name}"
                )
            return managed

        template = self._instances.require().config_file
        temporary = profile.with_suffix(f"{profile.suffix}.tmp")
        temporary.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        os.replace(temporary, profile)
        return self._instances.resolve_in_root(profile, must_exist=True)

    def _profile_path(self, world: Path) -> Path:
        return self._instances.resolve_in_root(
            self._profile_directory() / f"{world.stem}.txt"
        )

    def _profile_directory(self) -> Path:
        directory = self._instances.resolve_in_root(_PROFILE_DIRECTORY)
        directory.mkdir(parents=True, exist_ok=True)
        managed = self._instances.resolve_in_root(directory, must_exist=True)
        if not managed.is_dir():
            raise DomainValidationError("WorldConfigs is not a directory")
        return managed

    def _selection_path(self) -> Path:
        return self._instances.resolve_in_root(self._profile_directory() / _SELECTION_FILE)

    def _write_selection(self, world: Path) -> None:
        instance = self._instances.require()
        payload = {
            "version": 1,
            "world": world.relative_to(instance.root_dir).as_posix(),
        }
        selection = self._selection_path()
        temporary = selection.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, selection)

    def _validate_world_path(self, candidate: str | Path, *, must_exist: bool) -> Path:
        instance = self._instances.require()
        world = self._instances.resolve_in_root(candidate, must_exist=must_exist)
        if world.suffix.lower() != ".wld" or world.parent != instance.root_dir / "Worlds":
            raise DomainValidationError(
                "World must be a .wld file in the instance Worlds directory"
            )
        if world.exists() and not world.is_file():
            raise DomainValidationError("The selected world is not a regular file")
        return world

    def _read_path(self, path: Path) -> ServerConfigView:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _ACTIVE_SETTING.match(line)
            if match:
                values[match.group(1).strip().lower()] = match.group(2).strip()
        return ServerConfigView(values=values)

    def _set_values_in_path(
        self,
        path: Path,
        raw_values: dict[str, object],
    ) -> ServerConfigView:
        normalized = {
            key.lower(): self._serialize_value(key.lower(), value)
            for key, value in raw_values.items()
        }
        lines = path.read_text(encoding="utf-8").splitlines()
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

        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return self._read_path(path)

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
