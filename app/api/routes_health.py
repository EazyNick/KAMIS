from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


@router.get("/health")
def health(container: ContainerDependency) -> dict[str, object]:
    return {
        "status": "ok",
        "collection_running": container.collection_service.is_running,
        "latest_run": container.run_repository.latest(),
    }
