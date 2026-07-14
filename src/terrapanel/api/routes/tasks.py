from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from terrapanel.api.dependencies import get_services
from terrapanel.domain.tasks import (
    TaskCreate,
    TaskEnableRequest,
    TaskRun,
    TaskView,
)
from terrapanel.services.container import ServiceContainer

router = APIRouter(prefix="/tasks", tags=["tasks"])
Services = Annotated[ServiceContainer, Depends(get_services)]


@router.get("", response_model=list[TaskView])
async def list_tasks(
    services: Services,
    kind: Annotated[Literal["schedule", "event"] | None, Query()] = None,
) -> list[TaskView]:
    return services.tasks.list(kind=kind)


@router.get("/runs", response_model=list[TaskRun])
async def list_task_runs(
    services: Services,
    task_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TaskRun]:
    return services.tasks.list_runs(task_id=task_id, limit=limit)


@router.post("", response_model=TaskView, status_code=status.HTTP_201_CREATED)
async def create_task(request: TaskCreate, services: Services) -> TaskView:
    return services.tasks.create(request)


@router.get("/{task_id}", response_model=TaskView)
async def get_task(task_id: UUID, services: Services) -> TaskView:
    return services.tasks.get(task_id)


@router.put("/{task_id}", response_model=TaskView)
async def update_task(task_id: UUID, request: TaskCreate, services: Services) -> TaskView:
    return services.tasks.update(task_id, request)


@router.patch("/{task_id}/enabled", response_model=TaskView)
async def set_task_enabled(
    task_id: UUID,
    request: TaskEnableRequest,
    services: Services,
) -> TaskView:
    return services.tasks.set_enabled(task_id, request.enabled)


@router.post("/{task_id}/run", response_model=TaskRun, status_code=status.HTTP_202_ACCEPTED)
async def run_task(task_id: UUID, services: Services) -> TaskRun:
    return services.tasks.run_now(task_id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, services: Services) -> Response:
    services.tasks.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
