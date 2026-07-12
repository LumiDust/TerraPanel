from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from terrapanel.domain.instance import InstanceRecord
from terrapanel.domain.process import ProcessSnapshot


class ProvisionState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProvisionStage(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    INSTALLING = "installing"
    ASSOCIATING = "associating"
    CONFIGURING = "configuring"
    STARTING = "starting"
    COMPLETE = "complete"


class ProvisionRequest(BaseModel):
    name: str = Field(default="Primary Server", min_length=1, max_length=80)
    root_dir: str = Field(default="primary", min_length=1, max_length=240)
    version: str | None = Field(default=None, pattern=r"^v[0-9]+(?:\.[0-9]+){2,3}$")
    world_name: str = Field(default="TerraPanel", min_length=1, max_length=120)
    world_size: int = Field(default=1, ge=1, le=3)
    difficulty: int = Field(default=1, ge=0, le=3)
    max_players: int = Field(default=8, ge=1, le=255)
    port: int = Field(default=7777, ge=1, le=65535)
    password: str = Field(default="", max_length=128)
    motd: str = Field(default="", max_length=500)
    secure: bool = True
    upnp: bool = False
    start_after_install: bool = True

    @field_validator("root_dir")
    @classmethod
    def validate_root_dir(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/").strip("/")
        parts = normalized.split("/")
        if not normalized or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("root_dir must be a relative directory without traversal")
        if any(character in normalized for character in ("\r", "\n", "\x00", ":")):
            raise ValueError("root_dir contains invalid characters")
        return normalized

    @field_validator("world_name")
    @classmethod
    def validate_world_name(cls, value: str) -> str:
        if any(character in value for character in ('/', '\\', ':', '*', '?', '"', '<', '>', '|')):
            raise ValueError("world_name contains invalid filename characters")
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("world_name must be a single line")
        return value

    @field_validator("motd")
    @classmethod
    def validate_motd(cls, value: str) -> str:
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("motd must be a single line")
        return value


class UpdateRequest(BaseModel):
    version: str | None = Field(default=None, pattern=r"^v[0-9]+(?:\.[0-9]+){2,3}$")
    start_after_update: bool = True


class ProvisionSnapshot(BaseModel):
    state: ProvisionState = ProvisionState.IDLE
    stage: ProvisionStage = ProvisionStage.IDLE
    operation: Literal["install", "update"] | None = None
    name: str | None = None
    root_dir: str | None = None
    version: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    instance: InstanceRecord | None = None
    process: ProcessSnapshot | None = None
