from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.api.dependencies import get_container
from app.collectors.coupang_agent import collect_coupang_agent
from app.collectors.shopping import parse_target
from app.core.container import ApplicationContainer
from app.core.errors import CollectionAlreadyRunning

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


class CollectionRequest(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_order(self) -> CollectionRequest:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        return self


class DailyCollectionRequest(BaseModel):
    observed_date: date


class CoupangAgentCollectionRequest(BaseModel):
    observed_date: date
    item: str | None = None


@router.post("/collections/kamis")
def collect_kamis(
    request: CollectionRequest,
    container: ContainerDependency,
) -> dict[str, object]:
    return container.collection_service.collect(
        request.start_date, request.end_date
    ).to_dict()


@router.post("/collections/all")
def collect_all(
    request: DailyCollectionRequest,
    container: ContainerDependency,
) -> dict[str, object]:
    if container.daily_pipeline is None:
        raise HTTPException(status_code=503, detail="daily pipeline unavailable")
    return container.daily_pipeline.collect(request.observed_date).to_dict()


@router.post("/collections/coupang-agent")
def collect_coupang_with_agent(
    request: CoupangAgentCollectionRequest,
    container: ContainerDependency,
) -> dict[str, object]:
    if container.daily_pipeline is not None and container.daily_pipeline.is_running:
        raise CollectionAlreadyRunning("a unified daily collection is already running")
    if (
        not container.settings.coupang_agent_enabled
        or container.coupang_agent_source is None
    ):
        raise HTTPException(status_code=503, detail="Coupang agent unavailable")
    try:
        target = parse_target(request.item) if request.item else None
        result = collect_coupang_agent(
            container, request.observed_date, target=target
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "observed_date": request.observed_date.isoformat(),
        "target_count": 1 if target else len(container.settings.online_target_keys),
        "offer_count": result.offer_count,
        "summary_count": result.summary_count,
        "error_count": result.error_count,
        "errors": result.errors,
    }


@router.get("/collections/{run_id}")
def get_collection(
    run_id: str,
    container: ContainerDependency,
) -> dict[str, object]:
    run = container.run_repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="collection run not found")
    return run
