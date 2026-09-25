from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


@router.get("/health")
def health(container: ContainerDependency) -> dict[str, object]:
    startup_running = bool(
        container.startup_collection_service
        and container.startup_collection_service.is_running
    )
    daily_running = bool(container.daily_pipeline and container.daily_pipeline.is_running)
    return {
        "status": "ok",
        "collection_running": (
            startup_running or daily_running or container.collection_service.is_running
        ),
        "latest_run": container.run_repository.latest(),
    }
