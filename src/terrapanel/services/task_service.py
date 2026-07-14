import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import (  # pyright: ignore[reportMissingTypeStubs]
    AsyncIOScheduler,
)
from apscheduler.triggers.cron import CronTrigger  # pyright: ignore[reportMissingTypeStubs]
from apscheduler.triggers.date import DateTrigger  # pyright: ignore[reportMissingTypeStubs]
from apscheduler.triggers.interval import (  # pyright: ignore[reportMissingTypeStubs]
    IntervalTrigger,
)

from terrapanel.domain.errors import ConflictError, DomainValidationError, ResourceNotFoundError
from terrapanel.domain.process import ProcessEvent, ProcessEventType
from terrapanel.domain.tasks import (
    EventTaskTrigger,
    IntervalTaskTrigger,
    OnceTaskTrigger,
    TaskAction,
    TaskActionType,
    TaskCreate,
    TaskDefinition,
    TaskEventType,
    TaskRun,
    TaskRunSource,
    TaskRunStatus,
    TaskView,
    WeeklyTaskTrigger,
)
from terrapanel.repository.task_repository import TaskRepository
from terrapanel.services.backup_service import BackupService
from terrapanel.services.process_manager import ProcessManager
from terrapanel.services.provisioning_service import ProvisioningService
from terrapanel.services.world_service import WorldService

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MAX_TASKS = 100
_MISFIRE_GRACE_SECONDS = 60


class _ScheduledJob(Protocol):
    next_run_time: datetime | None


class _Scheduler(Protocol):
    running: bool

    def start(self) -> None: ...

    def shutdown(self, wait: bool = True) -> None: ...

    def add_job(
        self,
        function: object,
        *,
        trigger: object,
        args: list[str],
        id: str,
        replace_existing: bool,
        coalesce: bool,
        max_instances: int,
        misfire_grace_time: int,
    ) -> _ScheduledJob: ...

    def get_job(self, job_id: str) -> _ScheduledJob | None: ...

    def remove_job(self, job_id: str) -> None: ...


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        process: ProcessManager,
        worlds: WorldService,
        backups: BackupService,
        provisioning: ProvisioningService,
    ) -> None:
        self._repository = repository
        self._process = process
        self._worlds = worlds
        self._backups = backups
        self._provisioning = provisioning
        self._scheduler = cast(_Scheduler, AsyncIOScheduler(timezone=UTC))
        self._started = False
        self._closing = False
        self._running_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._last_event_runs: dict[tuple[UUID, TaskEventType], datetime] = {}
        self._process.add_event_listener(self._handle_process_event)

    async def start(self) -> None:
        if self._started:
            return
        self._repository.recover_interrupted_runs()
        self._closing = False
        self._scheduler.start()
        self._started = True
        now = datetime.now(UTC)
        for task in self._repository.list_tasks():
            if (
                task.enabled
                and isinstance(task.trigger, OnceTaskTrigger)
                and task.trigger.run_at.astimezone(UTC)
                < now - timedelta(seconds=_MISFIRE_GRACE_SECONDS)
            ):
                self._expire_missed_once(task, now)
                continue
            self._sync_schedule(task)
        self._queue_background(self._dispatch_event(TaskEventType.PANEL_STARTED))

    async def close(self) -> None:
        if not self._started:
            return
        self._closing = True
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        pending = [*self._background_tasks, *self._running_tasks.values()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._background_tasks.clear()
        self._running_tasks.clear()
        self._started = False

    def list(self, *, kind: str | None = None) -> list[TaskView]:
        tasks = self._repository.list_tasks()
        if kind == "schedule":
            tasks = [task for task in tasks if not isinstance(task.trigger, EventTaskTrigger)]
        elif kind == "event":
            tasks = [task for task in tasks if isinstance(task.trigger, EventTaskTrigger)]

        latest: dict[UUID, TaskRun] = {}
        for run in self._repository.list_runs(limit=500):
            latest.setdefault(run.task_id, run)
        return [self._to_view(task, latest.get(task.id)) for task in tasks]

    def get(self, task_id: UUID) -> TaskView:
        task = self._require_task(task_id)
        runs = self._repository.list_runs(task_id=task_id, limit=1)
        return self._to_view(task, runs[0] if runs else None)

    def create(self, request: TaskCreate) -> TaskView:
        current = self._repository.list_tasks()
        if len(current) >= _MAX_TASKS:
            raise ConflictError(f"A maximum of {_MAX_TASKS} tasks is allowed")
        self._ensure_unique_name(request.name, current)
        now = datetime.now(UTC)
        trigger = request.trigger
        if isinstance(trigger, IntervalTaskTrigger) and trigger.start_at is None:
            trigger = trigger.model_copy(update={"start_at": now})
        self._validate_future_once(trigger)
        task = TaskDefinition(
            id=uuid4(),
            name=request.name,
            enabled=request.enabled,
            trigger=trigger,
            actions=request.actions,
            created_at=now,
            updated_at=now,
        )
        self._repository.save_task(task)
        try:
            self._sync_schedule(task)
        except Exception:
            self._repository.delete_task(task.id)
            raise
        return self._to_view(task)

    def update(self, task_id: UUID, request: TaskCreate) -> TaskView:
        previous = self._require_task(task_id)
        self._ensure_unique_name(request.name, self._repository.list_tasks(), exclude=task_id)
        trigger = request.trigger
        if isinstance(trigger, IntervalTaskTrigger) and trigger.start_at is None:
            previous_start = (
                previous.trigger.start_at
                if isinstance(previous.trigger, IntervalTaskTrigger)
                else datetime.now(UTC)
            )
            trigger = trigger.model_copy(update={"start_at": previous_start})
        if request.enabled:
            self._validate_future_once(trigger)
        task = TaskDefinition(
            id=previous.id,
            name=request.name,
            enabled=request.enabled,
            trigger=trigger,
            actions=request.actions,
            created_at=previous.created_at,
            updated_at=datetime.now(UTC),
        )
        self._repository.save_task(task)
        try:
            self._sync_schedule(task)
        except Exception:
            self._repository.save_task(previous)
            self._sync_schedule(previous)
            raise
        return self.get(task_id)

    def set_enabled(self, task_id: UUID, enabled: bool) -> TaskView:
        previous = self._require_task(task_id)
        if enabled:
            self._validate_future_once(previous.trigger)
        task = previous.model_copy(update={"enabled": enabled, "updated_at": datetime.now(UTC)})
        self._repository.save_task(task)
        try:
            self._sync_schedule(task)
        except Exception:
            self._repository.save_task(previous)
            self._sync_schedule(previous)
            raise
        return self.get(task_id)

    def delete(self, task_id: UUID) -> None:
        self._require_task(task_id)
        if task_id in self._running_tasks:
            raise ConflictError("Wait for the task to finish before deleting it")
        self._remove_schedule(task_id)
        if not self._repository.delete_task(task_id):
            raise ResourceNotFoundError(f"Task does not exist: {task_id}")

    def run_now(self, task_id: UUID) -> TaskRun:
        if self._closing or not self._started:
            raise ConflictError("Task runtime is not available")
        task = self._require_task(task_id)
        return self._launch(task, TaskRunSource.MANUAL)

    def list_runs(self, *, task_id: UUID | None = None, limit: int = 100) -> list[TaskRun]:
        if task_id is not None:
            self._require_task(task_id)
        return self._repository.list_runs(task_id=task_id, limit=limit)

    async def _scheduled_fire(self, task_id: str) -> None:
        task = self._repository.get_task(UUID(task_id))
        if task is None or not task.enabled:
            return
        self._launch(task, TaskRunSource.SCHEDULE)
        if isinstance(task.trigger, OnceTaskTrigger):
            disabled = task.model_copy(update={"enabled": False, "updated_at": datetime.now(UTC)})
            self._repository.save_task(disabled)

    async def _dispatch_event(self, event: TaskEventType) -> None:
        now = datetime.now(UTC)
        for task in self._repository.list_tasks():
            trigger = task.trigger
            if not task.enabled or not isinstance(trigger, EventTaskTrigger):
                continue
            if trigger.event is not event:
                continue
            key = (task.id, event)
            previous = self._last_event_runs.get(key)
            if previous is not None and (now - previous).total_seconds() < trigger.cooldown_seconds:
                self._record_skipped(task, TaskRunSource.EVENT, event, "Event cooldown is active")
                continue
            self._last_event_runs[key] = now
            self._launch(task, TaskRunSource.EVENT, event)

    def _launch(
        self,
        task: TaskDefinition,
        source: TaskRunSource,
        event: TaskEventType | None = None,
    ) -> TaskRun:
        if task.id in self._running_tasks:
            return self._record_skipped(task, source, event, "Task is already running")
        run = TaskRun(
            id=uuid4(),
            task_id=task.id,
            task_name=task.name,
            source=source,
            event=event,
            status=TaskRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        self._repository.save_run(run)
        execution = asyncio.create_task(self._execute(task, run))
        self._running_tasks[task.id] = execution
        return run

    async def _execute(self, task: TaskDefinition, run: TaskRun) -> None:
        current_action_index = 0
        try:
            for action_index, action in enumerate(task.actions, start=1):
                current_action_index = action_index
                await self._execute_action(action)
        except asyncio.CancelledError:
            self._finish_run(run, TaskRunStatus.FAILED, "Task cancelled during shutdown")
            raise
        except Exception as error:
            self._finish_run(
                run,
                TaskRunStatus.FAILED,
                f"Action {current_action_index} failed: {error}",
            )
        else:
            self._finish_run(
                run,
                TaskRunStatus.SUCCESS,
                f"Completed {len(task.actions)} action(s)",
            )
        finally:
            current = asyncio.current_task()
            if self._running_tasks.get(task.id) is current:
                self._running_tasks.pop(task.id, None)

    async def _execute_action(self, action: TaskAction) -> None:
        if action.type is TaskActionType.WAIT:
            await asyncio.sleep(action.delay_seconds or 0)
            return
        if action.type is TaskActionType.START:
            if not self._process.is_running():
                self._ensure_start_allowed()
                await self._process.start()
            return
        if action.type is TaskActionType.STOP:
            if self._process.is_running():
                await self._process.stop()
            return
        if action.type is TaskActionType.RESTART:
            if self._process.is_running():
                await self._process.stop()
            self._ensure_start_allowed()
            await self._process.start()
            return
        if action.type is TaskActionType.COMMAND:
            await self._process.send_command(action.command or "")
            return
        if action.type is TaskActionType.BACKUP:
            if self._provisioning.is_running():
                raise ConflictError("Wait for installation or update to finish")
            await asyncio.to_thread(self._backups.create, action.backup_label)
            return
        raise DomainValidationError(f"Unsupported task action: {action.type}")

    def _ensure_start_allowed(self) -> None:
        if self._provisioning.is_running():
            raise ConflictError("Wait for installation or update to finish")
        self._worlds.ensure_startable()

    def _sync_schedule(self, task: TaskDefinition) -> None:
        self._remove_schedule(task.id)
        if not self._started or not task.enabled or isinstance(task.trigger, EventTaskTrigger):
            return
        trigger = self._build_trigger(task)
        self._scheduler.add_job(
            self._scheduled_fire,
            trigger=trigger,
            args=[str(task.id)],
            id=str(task.id),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        )

    @staticmethod
    def _build_trigger(task: TaskDefinition) -> object:
        trigger = task.trigger
        if isinstance(trigger, IntervalTaskTrigger):
            return IntervalTrigger(
                seconds=trigger.interval_seconds,
                start_date=trigger.start_at,
                timezone=UTC,
            )
        if isinstance(trigger, WeeklyTaskTrigger):
            weekdays = ",".join(_WEEKDAYS[day] for day in trigger.weekdays)
            return CronTrigger(
                day_of_week=weekdays,
                hour=trigger.at_time.hour,
                minute=trigger.at_time.minute,
                second=trigger.at_time.second,
                timezone=ZoneInfo(trigger.timezone),
            )
        if isinstance(trigger, OnceTaskTrigger):
            return DateTrigger(run_date=trigger.run_at)
        raise DomainValidationError("Event tasks do not have a schedule trigger")

    def _remove_schedule(self, task_id: UUID) -> None:
        if self._scheduler.get_job(str(task_id)) is not None:
            self._scheduler.remove_job(str(task_id))

    def _to_view(self, task: TaskDefinition, last_run: TaskRun | None = None) -> TaskView:
        job = self._scheduler.get_job(str(task.id)) if self._started else None
        return TaskView(
            **task.model_dump(),
            next_run_at=job.next_run_time if job is not None else None,
            running=task.id in self._running_tasks,
            last_run=last_run,
        )

    def _handle_process_event(self, event: ProcessEvent) -> None:
        if not self._started or self._closing:
            return
        event_type = {
            ProcessEventType.STARTED: TaskEventType.SERVER_STARTED,
            ProcessEventType.STOPPED: TaskEventType.SERVER_STOPPED,
            ProcessEventType.FAILED: TaskEventType.SERVER_FAILED,
        }[event.type]
        self._queue_background(self._dispatch_event(event_type))

    def _queue_background(self, coroutine: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _record_skipped(
        self,
        task: TaskDefinition,
        source: TaskRunSource,
        event: TaskEventType | None,
        message: str,
    ) -> TaskRun:
        now = datetime.now(UTC)
        run = TaskRun(
            id=uuid4(),
            task_id=task.id,
            task_name=task.name,
            source=source,
            event=event,
            status=TaskRunStatus.SKIPPED,
            started_at=now,
            finished_at=now,
            message=message,
        )
        return self._repository.save_run(run)

    def _finish_run(self, run: TaskRun, status: TaskRunStatus, message: str) -> None:
        self._repository.save_run(
            run.model_copy(
                update={
                    "status": status,
                    "finished_at": datetime.now(UTC),
                    "message": message,
                }
            )
        )

    def _expire_missed_once(self, task: TaskDefinition, now: datetime) -> None:
        disabled = task.model_copy(update={"enabled": False, "updated_at": now})
        self._repository.save_task(disabled)
        self._record_skipped(
            task,
            TaskRunSource.SCHEDULE,
            None,
            "One-time schedule was missed while TerraPanel was offline",
        )

    def _require_task(self, task_id: UUID) -> TaskDefinition:
        task = self._repository.get_task(task_id)
        if task is None:
            raise ResourceNotFoundError(f"Task does not exist: {task_id}")
        return task

    @staticmethod
    def _ensure_unique_name(
        name: str,
        tasks: list[TaskDefinition],
        *,
        exclude: UUID | None = None,
    ) -> None:
        normalized = name.casefold()
        if any(task.id != exclude and task.name.casefold() == normalized for task in tasks):
            raise ConflictError(f"A task named '{name}' already exists")

    @staticmethod
    def _validate_future_once(trigger: object) -> None:
        if isinstance(trigger, OnceTaskTrigger) and trigger.run_at.astimezone(UTC) <= datetime.now(
            UTC
        ):
            raise DomainValidationError("One-time task must be scheduled in the future")
