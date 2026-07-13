from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ServerConfigPatch(BaseModel):
    world: str | None = None
    autocreate: int | None = Field(default=None, ge=1, le=3)
    seed: str | None = Field(default=None, max_length=200)
    worldname: str | None = Field(default=None, max_length=120)
    difficulty: int | None = Field(default=None, ge=0, le=3)
    maxplayers: int | None = Field(default=None, ge=1, le=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    password: str | None = Field(default=None, max_length=128)
    motd: str | None = Field(default=None, max_length=500)
    worldpath: str | None = None
    banlist: str | None = None
    secure: bool | None = None
    language: str | None = Field(default=None, min_length=2, max_length=20)
    upnp: bool | None = None
    npcstream: int | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=0, le=5)
    modpath: str | None = None
    modpack: str | None = Field(default=None, max_length=200)

    @field_validator("worldname", "modpack")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("value must be a single line")
        return value


class ServerConfigView(BaseModel):
    values: dict[str, str]


class WorldInfo(BaseModel):
    name: str
    path: str
    has_mod_data: bool
    size: int
    modified_at: datetime
    selected: bool
    exists: bool = True


class WorldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    world_size: int = Field(default=1, ge=1, le=3)
    difficulty: int = Field(default=0, ge=0, le=3)
    seed: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("world name cannot be empty")
        return normalized

    @field_validator("seed")
    @classmethod
    def normalize_seed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("seed must be a single line")
        normalized = value.strip()
        return normalized or None


class WorldSelection(BaseModel):
    path: str


class ModInfo(BaseModel):
    name: str
    source: Literal["local", "workshop"]
    file: str
    size: int
    enabled: bool


class ModToggle(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w.-]+$")


class LogView(BaseModel):
    source: str
    path: str | None
    lines: list[str]


class BackupInfo(BaseModel):
    id: str
    created_at: datetime
    size: int
    world_files: int


class BackupCreate(BaseModel):
    label: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
