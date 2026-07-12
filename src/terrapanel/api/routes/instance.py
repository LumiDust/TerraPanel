from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from terrapanel.api.dependencies import get_services
from terrapanel.domain.errors import ConflictError
from terrapanel.domain.instance import InstanceAssociation, InstanceRecord
from terrapanel.domain.process import ConsoleCommand, ConsoleEntry, ProcessSnapshot
from terrapanel.services.container import ServiceContainer

router = APIRouter(prefix="/instance", tags=["instance"])
Services = Annotated[ServiceContainer, Depends(get_services)]


class InstanceStateView(BaseModel):
    configured: bool
    instance: InstanceRecord | None
    process: ProcessSnapshot


@router.get("", response_model=InstanceStateView)
def get_instance(services: Services) -> InstanceStateView:
    instance = services.instances.get()
    return InstanceStateView(
        configured=instance is not None,
        instance=instance,
        process=services.process.snapshot(),
    )


@router.put("", response_model=InstanceRecord)
def associate_instance(association: InstanceAssociation, services: Services) -> InstanceRecord:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    if services.process.is_running():
        raise ConflictError("Stop the server before changing the associated instance")
    return services.instances.associate(association)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_instance(services: Services) -> Response:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    if services.process.is_running():
        raise ConflictError("Stop the server before removing the associated instance")
    services.instances.remove()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/start", response_model=ProcessSnapshot)
async def start_instance(services: Services) -> ProcessSnapshot:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return await services.process.start()


@router.post("/stop", response_model=ProcessSnapshot)
async def stop_instance(
    services: Services,
    timeout_seconds: Annotated[float, Query(ge=1, le=120)] = 30,
) -> ProcessSnapshot:
    return await services.process.stop(timeout_seconds=timeout_seconds)


@router.get("/status", response_model=ProcessSnapshot)
def get_status(services: Services) -> ProcessSnapshot:
    return services.process.snapshot()


@router.post("/console", status_code=status.HTTP_202_ACCEPTED)
async def send_console_command(command: ConsoleCommand, services: Services) -> dict[str, str]:
    await services.process.send_command(command.command)
    return {"status": "accepted"}


@router.get("/console", response_model=list[ConsoleEntry])
def get_console(
    services: Services,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[ConsoleEntry]:
    return services.process.console(after_sequence=after_sequence, limit=limit)
