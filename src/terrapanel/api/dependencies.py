from typing import cast

from fastapi import Request

from terrapanel.services.container import ServiceContainer


def get_services(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.services)
