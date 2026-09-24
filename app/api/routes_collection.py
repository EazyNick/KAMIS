from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer

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


@router.get("/collections/{run_id}")
def get_collection(
    run_id: str,
    container: ContainerDependency,
) -> dict[str, object]:
    run = container.run_repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="collection run not found")
    return run
