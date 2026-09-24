from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer
from app.infrastructure.csv_repository import PriceFilters

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


@router.get("/prices")
def list_prices(
    container: ContainerDependency,
    price_type: str | None = None,
    item_code: str | None = None,
    item_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not exceed end_date")
    rows = container.price_repository.search(
        PriceFilters(price_type, item_code, item_name, start_date, end_date)
    )
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }
