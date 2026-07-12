from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from terrapanel.api.dependencies import get_services
from terrapanel.domain.process import ConsoleEntry
from terrapanel.domain.provisioning import ProvisionRequest, ProvisionSnapshot, UpdateRequest
from terrapanel.services.container import ServiceContainer

router = APIRouter(prefix="/provisioning", tags=["provisioning"])
Services = Annotated[ServiceContainer, Depends(get_services)]


@router.get("", response_model=ProvisionSnapshot)
def get_provisioning(services: Services) -> ProvisionSnapshot:
    return services.provisioning.snapshot()


@router.post("", response_model=ProvisionSnapshot, status_code=status.HTTP_202_ACCEPTED)
async def provision(
    request: ProvisionRequest,
    services: Services,
) -> ProvisionSnapshot:
    return await services.provisioning.provision(request)


@router.post("/update", response_model=ProvisionSnapshot, status_code=status.HTTP_202_ACCEPTED)
async def update(
    request: UpdateRequest,
    services: Services,
) -> ProvisionSnapshot:
    return await services.provisioning.update(request)


@router.post("/cancel", response_model=ProvisionSnapshot)
async def cancel(services: Services) -> ProvisionSnapshot:
    return await services.provisioning.cancel()


@router.get("/logs", response_model=list[ConsoleEntry])
def get_logs(
    services: Services,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[ConsoleEntry]:
    return services.provisioning.logs(after_sequence=after_sequence, limit=limit)
