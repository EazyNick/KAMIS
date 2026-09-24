from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes_catalog import router as catalog_router
from app.api.routes_collection import router as collection_router
from app.api.routes_health import router as health_router
from app.api.routes_prices import router as prices_router
from app.core.container import ApplicationContainer
from app.core.errors import CollectionAlreadyRunning
from config.server_config import Settings
from log import app_logger


def create_app(container: ApplicationContainer | None = None) -> FastAPI:
    resolved = container or ApplicationContainer.build(Settings.from_env())
    app = FastAPI(title="KAMIS Research Dashboard API", version="0.1.0")
    app.state.container = resolved
    app.include_router(health_router)
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(prices_router, prefix="/api/v1")
    app.include_router(collection_router, prefix="/api/v1")

    @app.middleware("http")
    async def request_logging(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("X-Correlation-ID", uuid4().hex)
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:
            app_logger.exception(
                "http.request.failed",
                "HTTP request failed",
                error,
                method=request.method,
                path=request.url.path,
                correlation_id=correlation_id,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise
        response.headers["X-Correlation-ID"] = correlation_id
        app_logger.info(
            "http.request.completed",
            "HTTP request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            correlation_id=correlation_id,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return response

    @app.exception_handler(CollectionAlreadyRunning)
    async def collection_conflict(
        request: Request, error: CollectionAlreadyRunning
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    return app


app = create_app()
