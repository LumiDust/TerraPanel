from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from terrapanel.api.dependencies import get_services
from terrapanel.domain.server_content import (
    LogView,
    ModInfo,
    ModToggle,
    ServerConfigPatch,
    ServerConfigView,
    WorldCreate,
    WorldInfo,
    WorldSelection,
)
from terrapanel.services.container import ServiceContainer

router = APIRouter(tags=["server content"])
Services = Annotated[ServiceContainer, Depends(get_services)]


@router.get("/server-config", response_model=ServerConfigView)
def get_server_config(services: Services) -> ServerConfigView:
    return services.server_config.read()


@router.patch("/server-config", response_model=ServerConfigView)
def update_server_config(patch: ServerConfigPatch, services: Services) -> ServerConfigView:
    return services.server_config.update(patch)


@router.get("/worlds", response_model=list[WorldInfo])
def list_worlds(services: Services) -> list[WorldInfo]:
    return services.worlds.list()


@router.post("/worlds", response_model=WorldInfo, status_code=status.HTTP_201_CREATED)
def create_world(request: WorldCreate, services: Services) -> WorldInfo:
    return services.worlds.create(request)


@router.post("/worlds/select", response_model=ServerConfigView)
def select_world(selection: WorldSelection, services: Services) -> ServerConfigView:
    return services.worlds.select(selection.path)


@router.post("/worlds/upload", response_model=WorldInfo, status_code=status.HTTP_201_CREATED)
def upload_world(
    files: Annotated[list[UploadFile], File()],
    services: Services,
    replace: Annotated[bool, Query()] = False,
) -> WorldInfo:
    return services.worlds.upload(
        [(file.filename, file.file) for file in files],
        replace=replace,
    )


@router.delete("/worlds/{name}", response_model=list[str])
def delete_world(name: str, services: Services) -> list[str]:
    return services.worlds.delete(name)


@router.get("/mods", response_model=list[ModInfo])
def list_mods(services: Services) -> list[ModInfo]:
    return services.mods.list()


@router.post("/mods/enable", response_model=list[str])
def enable_mod(toggle: ModToggle, services: Services) -> list[str]:
    return services.mods.enable(toggle.name)


@router.post("/mods/disable", response_model=list[str])
def disable_mod(toggle: ModToggle, services: Services) -> list[str]:
    return services.mods.disable(toggle.name)


@router.post(
    "/mods/upload",
    response_model=ModInfo,
    status_code=status.HTTP_201_CREATED,
)
def upload_mod(
    file: Annotated[UploadFile, File()],
    services: Services,
    replace: Annotated[bool, Query()] = False,
) -> ModInfo:
    return services.mods.upload(file.filename, file.file, replace=replace)


@router.delete("/mods/local/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_local_mod(name: str, services: Services) -> None:
    services.mods.delete_local(name)


@router.get("/logs/{source}", response_model=LogView)
def read_log(
    source: Literal["console", "server", "launch", "native"],
    services: Services,
    lines: Annotated[int, Query(ge=1, le=2000)] = 300,
) -> LogView:
    return services.logs.read(source, lines=lines)
