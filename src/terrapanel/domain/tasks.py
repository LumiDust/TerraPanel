from datetime import datetime, time
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskActionType(StrEnum):
    WAIT = "wait"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    COMMAND = "command"
    BACKUP = "backup"


class TaskEventType(StrEnum):
    PANEL_STARTED = "panel_started"
    SERVER_STARTED = "server_started"
    SERVER_STOPPED = "server_stopped"
    SERVER_FAILED = "server_failed"


class TaskRunSource(StrEnum):
    SCHEDULE = "schedule"
    EVENT = "event"
    MANUAL = "manual"


class TaskRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TaskActionType
    command: str | None = Field(default=None, max_length=2048)
    delay_seconds: int | None = Field(default=None, ge=1, le=3600)
    backup_label: str | None = Field(
        default=None,
        max_length=60,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.type is TaskActionType.COMMAND:
            command = (self.command or "").strip()
            if not command:
                raise ValueError("command action requires a command")
            if any(character in command for character in ("\r", "\n", "\x00")):
                raise ValueError("command must contain exactly one line")
            self.command = command
        elif self.command is not None:
            raise ValueError("command is only valid for command actions")

        if self.type is TaskActionType.WAIT:
            if self.delay_seconds is None:
                raise ValueError("wait action requires delay_seconds")
        elif self.delay_seconds is not None:
            raise ValueError("delay_seconds is only valid for wait actions")

        if self.type is not TaskActionType.BACKUP and self.backup_label is not None:
            raise ValueError("backup_label is only valid for backup actions")
        return self


class IntervalTaskTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["interval"] = "interval"
    interval_seconds: int = Field(ge=5, le=31_536_000)
    start_at: datetime | None = None

    @field_validator("start_at")
    @classmethod
    def require_aware_start(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("start_at must include a timezone")
        return value


class WeeklyTaskTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["weekly"] = "weekly"
    weekdays: list[int] = Field(min_length=1, max_length=7)
    at_time: time
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays must use values from 0 (Monday) to 6 (Sunday)")
        return sorted(set(value))

    @field_validator("at_time")
    @classmethod
    def reject_time_timezone(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("at_time must not include a timezone")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown timezone: {value}") from error
        return value


class OnceTaskTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["once"] = "once"
    run_at: datetime

    @field_validator("run_at")
    @classmethod
    def require_aware_run_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("run_at must include a timezone")
        return value


class EventTaskTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["event"] = "event"
    event: TaskEventType
    cooldown_seconds: int = Field(default=10, ge=0, le=86_400)


TaskTrigger = Annotated[
    IntervalTaskTrigger | WeeklyTaskTrigger | OnceTaskTrigger | EventTaskTrigger,
    Field(discriminator="type"),
]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    trigger: TaskTrigger
    actions: list[TaskAction] = Field(min_length=1, max_length=10)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("task name cannot be empty")
        if any(character in normalized for character in ("\r", "\n", "\x00")):
            raise ValueError("task name must contain exactly one line")
        return normalized


class TaskDefinition(TaskCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class TaskRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    task_id: UUID
    task_name: str
    source: TaskRunSource
    event: TaskEventType | None = None
    status: TaskRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    message: str | None = Field(default=None, max_length=2000)


class TaskView(TaskDefinition):
    next_run_at: datetime | None = None
    running: bool = False
    last_run: TaskRun | None = None


class TaskEnableRequest(BaseModel):
    enabled: bool
