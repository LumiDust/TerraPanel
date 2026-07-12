import os
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class HttpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bind_address: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: Path = Path("data")
    data_dir: Path = Path("data")
    servers_dir: Path = Path("data/servers")
    backups_dir: Path = Path("data/backups")

    @model_validator(mode="after")
    def derive_directories(self) -> Self:
        if "data_dir" not in self.model_fields_set:
            self.data_dir = self.root_dir
        if "servers_dir" not in self.model_fields_set:
            self.servers_dir = self.root_dir / "servers"
        if "backups_dir" not in self.model_fields_set:
            self.backups_dir = self.root_dir / "backups"
        return self


class ModSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_upload_size: int = Field(
        default=256 * 1024 * 1024,
        ge=1024 * 1024,
        le=2 * 1024 * 1024 * 1024,
    )


class WorldSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_upload_size: int = Field(
        default=512 * 1024 * 1024,
        ge=1024 * 1024,
        le=4 * 1024 * 1024 * 1024,
    )


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "production", "test"] = "development"
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = "info"
    http: HttpSettings = Field(default_factory=HttpSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    mods: ModSettings = Field(default_factory=ModSettings)
    worlds: WorldSettings = Field(default_factory=WorldSettings)

    def prepare_directories(self) -> None:
        for path in (
            self.storage.data_dir,
            self.storage.servers_dir,
            self.storage.backups_dir,
        ):
            path.expanduser().resolve().mkdir(parents=True, exist_ok=True)


class _HttpOverrides(BaseModel):
    bind_address: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


class _StorageOverrides(BaseModel):
    root_dir: Path | None = None
    data_dir: Path | None = None
    servers_dir: Path | None = None
    backups_dir: Path | None = None


class _ModOverrides(BaseModel):
    max_upload_size: int | None = Field(
        default=None,
        ge=1024 * 1024,
        le=2 * 1024 * 1024 * 1024,
    )


class _WorldOverrides(BaseModel):
    max_upload_size: int | None = Field(
        default=None,
        ge=1024 * 1024,
        le=4 * 1024 * 1024 * 1024,
    )


class _EnvironmentOverrides(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TERRAPANEL_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "production", "test"] | None = None
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] | None = None
    http: _HttpOverrides = Field(default_factory=_HttpOverrides)
    storage: _StorageOverrides = Field(default_factory=_StorageOverrides)
    mods: _ModOverrides = Field(default_factory=_ModOverrides)
    worlds: _WorldOverrides = Field(default_factory=_WorldOverrides)


def load_settings(config_file: str | Path | None = None) -> Settings:
    configured_path = config_file or os.environ.get("TERRAPANEL_CONFIG_FILE")
    path = Path(configured_path) if configured_path else Path("config.yaml")

    if not path.exists():
        if configured_path:
            raise FileNotFoundError(f"Configuration file does not exist: {path}")
        settings = Settings()
    else:
        with path.open(encoding="utf-8") as file:
            content: object = yaml.safe_load(file)

        if content is None:
            content = {}
        if not isinstance(content, dict):
            raise ValueError(f"Configuration root must be a mapping: {path}")

        settings = Settings.model_validate(content)

    overrides = _EnvironmentOverrides()
    updates: dict[str, object] = {}
    if overrides.environment is not None:
        updates["environment"] = overrides.environment
    if overrides.log_level is not None:
        updates["log_level"] = overrides.log_level

    http_updates = overrides.http.model_dump(exclude_none=True)
    if http_updates:
        updates["http"] = settings.http.model_copy(update=http_updates)

    storage_updates = overrides.storage.model_dump(exclude_none=True)
    if storage_updates:
        storage_values = settings.storage.model_dump()
        if "root_dir" in storage_updates:
            for field in ("data_dir", "servers_dir", "backups_dir"):
                if field not in storage_updates:
                    storage_values.pop(field, None)
        storage_values.update(storage_updates)
        updates["storage"] = StorageSettings.model_validate(storage_values)

    mod_updates = overrides.mods.model_dump(exclude_none=True)
    if mod_updates:
        updates["mods"] = settings.mods.model_copy(update=mod_updates)

    world_updates = overrides.worlds.model_dump(exclude_none=True)
    if world_updates:
        updates["worlds"] = settings.worlds.model_copy(update=world_updates)

    return settings.model_copy(update=updates)
