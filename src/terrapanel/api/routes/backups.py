from typing import Annotated

from fastapi import APIRouter, Depends, status

from terrapanel.api.dependencies import get_services
from terrapanel.domain.errors import ConflictError
from terrapanel.domain.server_content import BackupCreate, BackupInfo
from terrapanel.services.container import ServiceContainer

router = APIRouter(prefix="/backups", tags=["backups"])
Services = Annotated[ServiceContainer, Depends(get_services)]


@router.get("", response_model=list[BackupInfo])
def list_backups(services: Services) -> list[BackupInfo]:
    return services.backups.list()


@router.post("", response_model=BackupInfo, status_code=status.HTTP_201_CREATED)
def create_backup(request: BackupCreate, services: Services) -> BackupInfo:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return services.backups.create(request.label)


@router.post("/{backup_id}/restore", response_model=BackupInfo)
def restore_backup(backup_id: str, services: Services) -> BackupInfo:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return services.backups.restore(backup_id)
