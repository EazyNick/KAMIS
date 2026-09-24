from fastapi import Request

from app.core.container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container
