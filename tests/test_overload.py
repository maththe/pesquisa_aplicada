import asyncio
import io

import httpx
from app.config import Settings
from app.microservices.factory import build_app


def test_overload_guard_records_and_rejects_excess_concurrency() -> None:
    stream = io.StringIO()
    app = build_app(
        Settings(
            service_name="users-service",
            overload_concurrency_limit=1,
            overload_delay_ms=50,
        ),
        log_stream=stream,
    )

    async def exercise() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *[client.get("/users/1", headers={"X-Request-ID": "load-test"}) for _ in range(6)]
            )
        return [response.status_code for response in responses]

    statuses = asyncio.run(exercise())
    assert 200 in statuses
    assert 503 in statuses
    assert "overload_rejected" in stream.getvalue()
    assert "ConcurrencyLimitExceeded" in stream.getvalue()
