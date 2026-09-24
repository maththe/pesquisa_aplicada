from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TextIO

import httpx
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.api import gateway, orders, users
from app.api.middleware import RequestLoggingMiddleware
from app.config import Settings
from app.observability.metrics import sample_metrics
from app.observability.models import Metrics
from app.schemas.catalog import HealthResponse
from app.services.http import DependencyFailure
from app.services.runtime import ServiceRuntime
from app.telemetry import EventLogger


def build_app(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    log_stream: TextIO | None = None,
) -> FastAPI:
    events = EventLogger(settings.service_name, settings.log_level, settings.log_dir, log_stream)
    runtime = ServiceRuntime(settings, events)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.http_timeout_seconds, transport=transport, trust_env=False
            ) as client:
                runtime.client = client
                events.emit("INFO", "service_started", "Serviço iniciado")
                try:
                    yield
                finally:
                    events.emit("INFO", "service_stopped", "Serviço encerrado")
                    runtime.client = None
        finally:
            events.close()

    app = FastAPI(title=settings.service_name, lifespan=lifespan)
    app.add_middleware(RequestLoggingMiddleware, events=events)

    @app.exception_handler(DependencyFailure)
    async def dependency_failure(request: Request, exc: DependencyFailure) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(service=settings.service_name)

    @app.get("/metrics")
    def metrics() -> Metrics:
        return sample_metrics(settings.service_name)

    if settings.service_name == "gateway":
        app.include_router(gateway.build_router(runtime))
    elif settings.service_name == "orders-service":
        app.include_router(orders.build_router(runtime))
    else:
        app.include_router(users.router)
    return app
