import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse

from terrapanel.api.dependencies import get_services
from terrapanel.domain.errors import ConflictError, DomainValidationError
from terrapanel.domain.files import (
    ArchiveExtract,
    ArchiveExtractResult,
    ArchivePreview,
    DirectoryCreate,
    DirectoryListing,
    FileEntry,
    FileMove,
    TextFileUpdate,
    TextFileView,
)
from terrapanel.services.container import ServiceContainer

router = APIRouter(prefix="/files", tags=["files"])
Services = Annotated[ServiceContainer, Depends(get_services)]


@router.get("", response_model=DirectoryListing)
def list_files(services: Services, path: str = "") -> DirectoryListing:
    return services.files.list(path)


@router.post("/directories", response_model=FileEntry, status_code=status.HTTP_201_CREATED)
def create_directory(request: DirectoryCreate, services: Services) -> FileEntry:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return services.files.create_directory(request.path)


@router.post("/upload", response_model=FileEntry, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    services: Services,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    directory: str = "",
    replace: bool = False,
) -> FileEntry:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    declared_size: int | None = None
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise DomainValidationError("Content-Length must be an integer") from error
        if declared_size < 0:
            raise DomainValidationError("Content-Length cannot be negative")

    async def chunks() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            yield chunk

    return await services.files.upload(
        directory,
        filename,
        chunks(),
        replace=replace,
        declared_size=declared_size,
    )


@router.get("/download", response_class=FileResponse)
def download_file(path: str, services: Services) -> FileResponse:
    file = services.files.download_path(path)
    return FileResponse(file, filename=file.name)


@router.get("/text", response_model=TextFileView)
def read_text_file(path: str, services: Services) -> TextFileView:
    return services.files.read_text(path)


@router.put("/text", response_model=TextFileView)
def update_text_file(request: TextFileUpdate, services: Services) -> TextFileView:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return services.files.update_text(request)


@router.patch("", response_model=FileEntry)
def move_file(request: FileMove, services: Services) -> FileEntry:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return services.files.move(
        request.source,
        request.destination,
        replace=request.replace,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(path: str, services: Services, recursive: bool = False) -> None:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    services.files.delete(path, recursive=recursive)


@router.get("/archive", response_model=ArchivePreview)
def inspect_archive(path: str, services: Services, destination: str = "") -> ArchivePreview:
    return services.files.inspect_archive(path, destination)


@router.post("/archive/extract", response_model=ArchiveExtractResult)
async def extract_archive(
    request: ArchiveExtract,
    services: Services,
) -> ArchiveExtractResult:
    if services.provisioning.is_running():
        raise ConflictError("Wait for installation or update to finish")
    return await asyncio.to_thread(
        services.files.extract_archive,
        request.path,
        request.destination,
        replace=request.replace,
    )
