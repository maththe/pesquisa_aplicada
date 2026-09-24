from io import StringIO
from uuid import UUID

import pytest
from app.api.factory import build_app
from app.config import ServiceName, Settings
from app.telemetry import request_id_context
from tests.helpers import app_client, read_events


@pytest.mark.parametrize("service", ["gateway", "users-service", "orders-service"])
async def test_health_and_generated_request_id(service: ServiceName) -> None:
    stream = StringIO()
    app = build_app(Settings(service_name=service), log_stream=stream)
    async with app_client(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"service": service, "status": "ok"}
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    events = read_events(stream)
    completed = next(record for record in events if record.event == "request_completed")
    assert completed.request_id == request_id
    assert completed.duration_ms is not None
    assert completed.status_code == 200
    assert all(
        record.request_id is None for record in events if record.event != "request_completed"
    )
    assert request_id_context.get() is None


@pytest.mark.parametrize("incoming", ["req-123", "trace:123.test_1", "a" * 128])
async def test_preserves_valid_request_id(incoming: str) -> None:
    app = build_app(Settings(service_name="users-service"), log_stream=StringIO())
    async with app_client(app) as client:
        response = await client.get("/users/1", headers={"X-Request-ID": incoming})
    assert response.headers["X-Request-ID"] == incoming


@pytest.mark.parametrize("incoming", ["", "has spaces", "a" * 129, "invalid\nheader"])
async def test_replaces_invalid_request_id(incoming: str) -> None:
    app = build_app(Settings(service_name="users-service"), log_stream=StringIO())
    async with app_client(app) as client:
        response = await client.get("/health", headers={"X-Request-ID": incoming})
    assert UUID(response.headers["X-Request-ID"]).version == 4


@pytest.mark.parametrize(
    ("path", "status"), [("/missing", 404), ("/users/999", 404), ("/users/not-an-int", 422)]
)
async def test_expected_errors_keep_correlation(path: str, status: int) -> None:
    stream = StringIO()
    app = build_app(Settings(service_name="users-service"), log_stream=stream)
    async with app_client(app) as client:
        response = await client.get(path, headers={"X-Request-ID": "req-error"})
    assert response.status_code == status
    assert response.headers["X-Request-ID"] == "req-error"
    completed = next(event for event in read_events(stream) if event.event == "request_completed")
    assert completed.status_code == status
    assert completed.request_id == "req-error"


async def test_unexpected_exception_keeps_id_and_cleans_context() -> None:
    stream = StringIO()
    app = build_app(Settings(service_name="users-service"), log_stream=stream)

    @app.get("/broken")
    async def broken() -> None:
        raise RuntimeError("test failure")

    async with app_client(app) as client:
        response = await client.get("/broken", headers={"X-Request-ID": "req-broken"})
        assert request_id_context.get() is None
        health = await client.get("/health")
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-broken"
    assert health.headers["X-Request-ID"] != "req-broken"
    failed = next(event for event in read_events(stream) if event.event == "unhandled_exception")
    assert failed.error_type == "RuntimeError"
    assert failed.request_id == "req-broken"
