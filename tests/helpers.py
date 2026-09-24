from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import StringIO

import httpx
from app.schemas.logs import StructuredLog
from fastapi import FastAPI


def read_events(stream: StringIO) -> list[StructuredLog]:
    return [StructuredLog.model_validate_json(line) for line in stream.getvalue().splitlines()]


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


class ServiceTransport(httpx.AsyncBaseTransport):
    def __init__(self, apps: dict[str, FastAPI]) -> None:
        self.transports = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.transports[request.url.host].handle_async_request(request)

    async def aclose(self) -> None:
        for transport in self.transports.values():
            await transport.aclose()
