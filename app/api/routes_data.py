from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]
Mode = Literal["raw", "base100", "return_1d", "return_7d"]


def _page(rows: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


def _clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


@router.get("/online/offers")
def online_offers(
    container: ContainerDependency,
    item_code: str | None = None,
    platform: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if container.online_repository is None:
        raise HTTPException(status_code=503, detail="online repository unavailable")
    return _page(
        container.online_repository.search_offers(
            item_code=item_code, platform=platform
        ),
        limit,
        offset,
    )


@router.get("/online/summaries")
def online_summaries(
    container: ContainerDependency,
    item_code: str | None = None,
    platform: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if container.online_repository is None:
        raise HTTPException(status_code=503, detail="online repository unavailable")
    return _page(
        container.online_repository.search_summaries(
            item_code=item_code, platform=platform
        ),
        limit,
        offset,
    )


@router.get("/online/decisions")
def online_decisions(
    container: ContainerDependency,
    item_code: str | None = None,
    platform: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if container.online_repository is None:
        raise HTTPException(status_code=503, detail="online repository unavailable")
    return _page(
        container.online_repository.search_decisions(
            item_code=item_code, platform=platform
        ),
        limit,
        offset,
    )


@router.get("/market")
def market_data(
    container: ContainerDependency,
    series_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if container.market_repository is None:
        raise HTTPException(status_code=503, detail="market repository unavailable")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422, detail="start_date must not exceed end_date"
        )
    return _page(
        container.market_repository.search(
            series_id=series_id, start_date=start_date, end_date=end_date
        ),
        limit,
        offset,
    )


@router.get("/comparison")
def comparison(
    container: ContainerDependency,
    item_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    mode: Mode = "base100",
) -> dict[str, Any]:
    if container.comparison_service is None:
        raise HTTPException(status_code=503, detail="comparison service unavailable")
    return container.comparison_service.chart(item_code, start_date, end_date, mode)


@router.get("/dashboard/defaults")
def dashboard_defaults(container: ContainerDependency) -> dict[str, str | None]:
    if container.comparison_service is None:
        raise HTTPException(status_code=503, detail="comparison service unavailable")
    return container.comparison_service.dashboard_defaults()


@router.get("/dashboard/bootstrap")
def dashboard_bootstrap(container: ContainerDependency) -> dict[str, Any]:
    if container.dashboard_bootstrap_service is None:
        raise HTTPException(status_code=503, detail="dashboard bootstrap unavailable")
    return _clean(container.dashboard_bootstrap_service.load())


@router.get("/correlations")
def correlations(
    container: ContainerDependency,
    item_code: str,
    target_series: str = "kamis_retail",
    start_date: date | None = None,
    end_date: date | None = None,
    mode: Mode = "return_1d",
) -> list[dict[str, Any]]:
    if container.comparison_service is None:
        raise HTTPException(status_code=503, detail="comparison service unavailable")
    return _clean(
        container.comparison_service.correlations(
            item_code, target_series, start_date, end_date, mode
        )
    )


@router.get("/analytics/{table}")
def analytics_table(
    table: str,
    container: ContainerDependency,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if container.analytics_repository is None:
        raise HTTPException(status_code=503, detail="analytics repository unavailable")
    try:
        rows = container.analytics_repository.read(table)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _page(rows, limit, offset)
