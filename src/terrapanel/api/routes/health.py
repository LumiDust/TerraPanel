from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from terrapanel import __version__

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["terrapanel"] = "terrapanel"
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
