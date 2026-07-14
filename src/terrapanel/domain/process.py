from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProcessState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class ProcessEventType(StrEnum):
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"


class ProcessSnapshot(BaseModel):
    state: ProcessState
    pid: int | None = None
    started_at: datetime | None = None
    exit_code: int | None = None


class ConsoleEntry(BaseModel):
    sequence: int
    timestamp: datetime
    stream: str
    text: str


class ProcessEvent(BaseModel):
    type: ProcessEventType
    timestamp: datetime
    exit_code: int | None = None
    message: str | None = None


class ConsoleCommand(BaseModel):
    command: str = Field(min_length=1, max_length=2048)
