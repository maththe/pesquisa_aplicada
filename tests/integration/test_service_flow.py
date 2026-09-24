import asyncio
from contextlib import AsyncExitStack
from io import StringIO
from uuid import UUID

import httpx
import pytest
from app.api.factory import build_app
from app.config import ServiceName, Settings
from app.telemetry import request_id_context
from tests.helpers import ServiceTransport, app_client, read_events


@pytest.mark.parametrize("incoming", [None, "req-chain-123"])
async def test_request_crosses_three_services(incoming: str | None) -> None:
    names: list[ServiceName] = ["gateway", "users-service", "orders-service"]
    streams = {name: StringIO() for name in names}
    users = build_app(Settings(service_name="users-service"), log_stream=streams["users-service"])
    orders = build_app(
        Settings(service_name="orders-service"),
        transport=ServiceTransport({"users-service": users}),
        log_stream=streams["orders-service"],
    )
    gateway = build_app(
        Settings(service_name="gateway"),
        transport=ServiceTransport({"users-service": users, "orders-service": orders}),
        log_stream=streams["gateway"],
    )
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(users.router.lifespan_context(users))
        await stack.enter_async_context(orders.router.lifespan_context(orders))
        client = await stack.enter_async_context(app_client(gateway))
        response = await client.get(
            "/orders/1", headers={"X-Request-ID": incoming} if incoming else {}
        )
        assert request_id_context.get() is None

    assert response.status_code == 200
    assert response.json()["user"]["id"] == 1
    request_id = response.headers["X-Request-ID"]
    if incoming:
        assert request_id == incoming
    else:
        assert UUID(request_id).version == 4
    records = [event for stream in streams.values() for event in read_events(stream)]
    request_events = [event for event in records if event.request_id is not None]
    assert {event.service for event in request_events} == set(names)
    assert {event.request_id for event in request_events} == {request_id}
    assert len({event.log_id for event in records}) == len(records)
    assert {
        (event.service, event.dependency)
        for event in request_events
        if event.event == "dependency_completed"
    } == {("gateway", "orders-service"), ("orders-service", "users-service")}


async def test_concurrent_requests_do_not_mix_ids() -> None:
    stream = StringIO()
    forwarded: dict[int, str] = {}
    all_entered = asyncio.Event()
    count = 20

    async def downstream(request: httpx.Request) -> httpx.Response:
        user_id = int(request.url.path.rsplit("/", 1)[1])
        forwarded[user_id] = request.headers["X-Request-ID"]
        if len(forwarded) == count:
            all_entered.set()
        await asyncio.wait_for(all_entered.wait(), timeout=3)
        return httpx.Response(200, json={"id": user_id, "name": "Test"})

    app = build_app(Settings(), transport=httpx.MockTransport(downstream), log_stream=stream)
    async with app_client(app) as client:
        responses = await asyncio.gather(
            *(client.get(f"/users/{i}", headers={"X-Request-ID": f"req-{i}"}) for i in range(count))
        )
    for i, response in enumerate(responses):
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == f"req-{i}"
        assert forwarded[i] == f"req-{i}"
    events = [event for event in read_events(stream) if event.path is not None]
    assert len(events) == count * 2
    for event in events:
        assert event.path is not None
        assert event.request_id == f"req-{event.path.rsplit('/', 1)[1]}"


@pytest.mark.parametrize(
    ("failure", "status", "event"),
    [
        ("timeout", 504, "dependency_timeout"),
        ("connect", 503, "dependency_unavailable"),
        ("http503", 503, "dependency_http_error"),
        ("http500", 500, "dependency_http_error"),
        ("http404", 404, "dependency_http_error"),
        ("invalid_json", 502, "dependency_invalid_response"),
        ("invalid_schema", 502, "dependency_invalid_response"),
    ],
)
async def test_dependency_errors_are_logged_and_correlated(
    failure: str, status: int, event: str
) -> None:
    def downstream(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-ID"] == "req-failure"
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "connect":
            raise httpx.ConnectError("unavailable", request=request)
        if failure.startswith("http"):
            return httpx.Response(int(failure[4:]), json={"detail": "error"})
        if failure == "invalid_json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json={"unexpected": True})

    stream = StringIO()
    app = build_app(Settings(), transport=httpx.MockTransport(downstream), log_stream=stream)
    async with app_client(app) as client:
        response = await client.get("/orders/1", headers={"X-Request-ID": "req-failure"})
        health = await client.get("/health")
    assert response.status_code == status
    assert response.headers["X-Request-ID"] == "req-failure"
    assert health.status_code == 200
    failure_event = next(record for record in read_events(stream) if record.event == event)
    assert failure_event.request_id == "req-failure"
    assert failure_event.dependency == "orders-service"
    assert failure_event.duration_ms is not None
