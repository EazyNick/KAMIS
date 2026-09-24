from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_container
from app.core.container import ApplicationContainer
from app.infrastructure.csv_repository import CatalogFilters

router = APIRouter()
ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


@router.get("/catalog")
def list_catalog(
    container: ContainerDependency,
    category_code: str | None = None,
    item_code: str | None = None,
    item_name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    rows = container.catalog_repository.search(
        CatalogFilters(category_code, item_code, item_name)
    )
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }
