from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FileEntry(BaseModel):
    name: str
    path: str
    kind: Literal["file", "directory", "symlink", "other"]
    size: int | None
    modified_at: datetime
    archive: bool = False


class DirectoryListing(BaseModel):
    path: str
    parent: str | None
    entries: list[FileEntry]


class DirectoryCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class FileMove(BaseModel):
    source: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)
    replace: bool = False


class ArchivePreview(BaseModel):
    path: str
    files: int
    directories: int
    expanded_size: int
    compressed_size: int
    top_level: list[str]
    conflicts: list[str]


class ArchiveExtract(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    destination: str = Field(default="", max_length=1024)
    replace: bool = False

    @field_validator("path", "destination")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("path contains control characters")
        return value


class ArchiveExtractResult(BaseModel):
    destination: str
    files: int
    directories: int
    bytes_written: int
