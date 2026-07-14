import os
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from terrapanel.domain.tasks import TaskDefinition, TaskRun, TaskRunStatus


class _TaskDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    tasks: list[TaskDefinition] = []


class _TaskRunDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    runs: list[TaskRun] = []


class TaskRepository:
    def __init__(self, tasks_file: Path, runs_file: Path, *, history_limit: int = 500) -> None:
        self._tasks_file = tasks_file
        self._runs_file = runs_file
        self._history_limit = history_limit
        self._lock = RLock()

    def list_tasks(self) -> list[TaskDefinition]:
        with self._lock:
            return list(self._read_tasks().tasks)

    def get_task(self, task_id: UUID) -> TaskDefinition | None:
        with self._lock:
            return next((task for task in self._read_tasks().tasks if task.id == task_id), None)

    def save_task(self, task: TaskDefinition) -> TaskDefinition:
        with self._lock:
            document = self._read_tasks()
            for index, current in enumerate(document.tasks):
                if current.id == task.id:
                    document.tasks[index] = task
                    break
            else:
                document.tasks.append(task)
            self._write(self._tasks_file, document.model_dump_json(indent=2))
            return task

    def delete_task(self, task_id: UUID) -> bool:
        with self._lock:
            document = self._read_tasks()
            remaining = [task for task in document.tasks if task.id != task_id]
            if len(remaining) == len(document.tasks):
                return False
            document.tasks = remaining
            self._write(self._tasks_file, document.model_dump_json(indent=2))
            return True

    def list_runs(self, *, task_id: UUID | None = None, limit: int = 100) -> list[TaskRun]:
        with self._lock:
            runs = self._read_runs().runs
            if task_id is not None:
                runs = [run for run in runs if run.task_id == task_id]
            return list(reversed(runs[-limit:]))

    def save_run(self, run: TaskRun) -> TaskRun:
        with self._lock:
            document = self._read_runs()
            for index, current in enumerate(document.runs):
                if current.id == run.id:
                    document.runs[index] = run
                    break
            else:
                document.runs.append(run)
            document.runs = document.runs[-self._history_limit :]
            self._write(self._runs_file, document.model_dump_json(indent=2))
            return run

    def recover_interrupted_runs(self) -> None:
        with self._lock:
            document = self._read_runs()
            changed = False
            recovered_at = datetime.now(UTC)
            for index, run in enumerate(document.runs):
                if run.status is not TaskRunStatus.RUNNING:
                    continue
                document.runs[index] = run.model_copy(
                    update={
                        "status": TaskRunStatus.FAILED,
                        "finished_at": recovered_at,
                        "message": "TerraPanel stopped before this task finished",
                    }
                )
                changed = True
            if changed:
                self._write(self._runs_file, document.model_dump_json(indent=2))

    def _read_tasks(self) -> _TaskDocument:
        if not self._tasks_file.is_file():
            return _TaskDocument()
        return _TaskDocument.model_validate_json(self._tasks_file.read_text(encoding="utf-8"))

    def _read_runs(self) -> _TaskRunDocument:
        if not self._runs_file.is_file():
            return _TaskRunDocument()
        return _TaskRunDocument.model_validate_json(self._runs_file.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
