from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from terrapanel import __version__
from terrapanel.api.router import api_router
from terrapanel.config import Settings, load_settings
from terrapanel.domain.errors import (
    ConflictError,
    DomainValidationError,
    NotConfiguredError,
    ResourceNotFoundError,
    TerraPanelError,
    UnsupportedPlatformError,
)
from terrapanel.services.container import ServiceContainer, build_services


def create_app(
    settings: Settings | None = None,
    services: ServiceContainer | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app_settings.prepare_directories()
        app.state.settings = app_settings
        app_services = services or build_services(app_settings)
        app.state.services = app_services
        try:
            yield
        finally:
            await app_services.provisioning.close()
            await app_services.process.close()

    app = FastAPI(
        title="TerraPanel API",
        version=__version__,
        lifespan=lifespan,
    )

    @app.exception_handler(TerraPanelError)
    async def handle_domain_error(  # pyright: ignore[reportUnusedFunction]
        _request: Request, error: TerraPanelError
    ) -> JSONResponse:
        if isinstance(error, (NotConfiguredError, ResourceNotFoundError)):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(error, ConflictError):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(error, (DomainValidationError, UnsupportedPlatformError)):
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content={"detail": str(error)})

    app.include_router(api_router, prefix="/api/v1")

    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if index_file.is_file() and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def frontend_index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
            return FileResponse(index_file)

    return app
