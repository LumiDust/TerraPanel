from fastapi import APIRouter

from terrapanel.api.routes.backups import router as backups_router
from terrapanel.api.routes.files import router as files_router
from terrapanel.api.routes.health import router as health_router
from terrapanel.api.routes.instance import router as instance_router
from terrapanel.api.routes.provisioning import router as provisioning_router
from terrapanel.api.routes.server_content import router as server_content_router
from terrapanel.api.routes.tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(instance_router)
api_router.include_router(provisioning_router)
api_router.include_router(server_content_router)
api_router.include_router(backups_router)
api_router.include_router(files_router)
api_router.include_router(tasks_router)
