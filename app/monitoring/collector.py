import asyncio
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import MonitorSettings, ServiceName
from app.models import HealthResponse
from app.monitoring.current import CurrentState
from app.monitoring.ingestion import ingest_logs
from app.monitoring.models import Metrics, Probe, Snapshot
from app.monitoring.storage import History


async def probe_service(client: httpx.AsyncClient, service: ServiceName, url: str) -> Probe:
    started = perf_counter()
    status: int | None = None
    error: str | None = None
    healthy = False
    try:
        response = await client.get(f"{url}/health")
        status = response.status_code
        response.raise_for_status()
        health = HealthResponse.model_validate_json(response.content)
        healthy = health.service == service
        if not healthy:
            error = "ServiceIdentityMismatch"
    except (httpx.HTTPError, ValidationError) as exc:
        error = type(exc).__name__
    latency = (perf_counter() - started) * 1000
    metrics: Metrics | None = None
    metrics_error: str | None = None
    if healthy:
        try:
            response = await client.get(f"{url}/metrics")
            response.raise_for_status()
            metrics = Metrics.model_validate_json(response.content)
            if metrics.service != service:
                metrics = None
                metrics_error = "ServiceIdentityMismatch"
        except (httpx.HTTPError, ValidationError) as exc:
            metrics_error = type(exc).__name__
    return Probe(
        service=service,
        reachable=healthy,
        status_code=status,
        latency_ms=latency,
        error_type=error,
        metrics=metrics,
        metrics_error=metrics_error,
    )


async def collect_once(
    settings: MonitorSettings,
    history: History,
    current: CurrentState,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        trust_env=False,
        transport=transport,
    ) as client:
        probes = await asyncio.gather(
            *(probe_service(client, service, url) for service, url in settings.targets().items())
        )
    snapshot = Snapshot(services=list(probes))
    # Primeiro persistir histórico. etcd pode falhar sem perder as evidências.
    await asyncio.to_thread(history.save_snapshot, snapshot)
    ingestion = await asyncio.to_thread(ingest_logs, history, settings.log_dir)
    current_error = None
    try:
        await asyncio.to_thread(current.publish, snapshot)
    except Exception as exc:
        current_error = type(exc).__name__
    return {
        "snapshot_id": snapshot.snapshot_id,
        "timestamp": snapshot.timestamp.isoformat(),
        "ingestion": ingestion,
        "current_published": current_error is None,
        "current_error": current_error,
    }
