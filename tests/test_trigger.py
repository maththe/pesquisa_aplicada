"""Sinais de negócio, limites e regras de disparo do gatilho automático."""

import asyncio
import io
from datetime import timedelta
from typing import Any

import httpx
from app.config import MonitorSettings, Settings
from app.microservices.factory import build_app
from app.monitoring.models import Probe, ServiceSignals, Snapshot, Thresholds, utcnow
from app.monitoring.signals import compute_signals, percentile_95
from app.monitoring.trigger import Trigger, find_violations
from experiments.scenarios import SCENARIOS, evaluate


def log(service: str, status: int, duration: float = 10, event: str = "request_completed") -> Any:
    return {"service": service, "event": event, "status_code": status, "duration_ms": duration}


def probe(service: str, reachable: bool = True) -> Probe:
    return Probe(service=service, reachable=reachable, latency_ms=1)  # type: ignore[arg-type]


def signal(service: str, requests: int, errors: int, p95: float = 10) -> ServiceSignals:
    return ServiceSignals(
        service=service,  # type: ignore[arg-type]
        window_seconds=30,
        requests=requests,
        errors=errors,
        error_rate=errors / requests if requests else None,
        p95_ms=p95,
    )


def snapshot(signals: list[ServiceSignals], users_up: bool = True) -> Snapshot:
    services = [probe("gateway"), probe("orders-service"), probe("users-service", users_up)]
    return Snapshot(services=services, signals=signals)


def test_signals_count_errors_latency_and_dependency_failures() -> None:
    logs = [
        log("orders-service", 500, 20),
        log("orders-service", 200, 40),
        log("gateway", 500),
        {"service": "gateway", "event": "dependency_http_error", "status_code": 500},
    ]
    signals = {s.service: s for s in compute_signals(logs, 30)}
    assert signals["orders-service"].requests == 2
    assert signals["orders-service"].error_rate == 0.5
    assert signals["orders-service"].p95_ms == 40
    assert signals["gateway"].dependency_failures == 1
    assert signals["users-service"].requests == 0
    assert signals["users-service"].error_rate is None


def test_percentile_95() -> None:
    assert percentile_95([]) is None
    assert percentile_95([float(n) for n in range(1, 101)]) == 95


def test_violations_respect_limits_and_minimum_volume() -> None:
    limits = Thresholds(error_rate=0.2, min_requests=3, p95_ms=1500)
    healthy = snapshot([signal("orders-service", 10, 1, 100)])
    assert find_violations(healthy, limits) == []
    too_few = snapshot([signal("orders-service", 2, 2)])
    assert find_violations(too_few, limits) == []
    failing = snapshot([signal("orders-service", 4, 4), signal("users-service", 4, 0, 3000)])
    assert {(v.service, v.metric) for v in find_violations(failing, limits)} == {
        ("orders-service", "error_rate"),
        ("users-service", "p95_ms"),
    }
    down = snapshot([], users_up=False)
    assert [(v.service, v.metric) for v in find_violations(down, limits)] == [
        ("users-service", "unreachable")
    ]


def test_trigger_fires_once_per_incident_and_rearms_after_recovery() -> None:
    now = [0.0]
    trigger = Trigger(MonitorSettings(trigger_cooldown_seconds=0), clock=lambda: now[0])
    limits = Thresholds()
    bad = [signal("orders-service", 5, 5)]
    assert trigger.should_fire(snapshot(bad), limits)
    assert trigger.should_fire(snapshot(bad), limits) == []  # mesmo incidente
    assert trigger.should_fire(snapshot([]), limits) == []  # recuperou: rearma
    assert trigger.should_fire(snapshot(bad), limits)


def test_trigger_cooldown_blocks_new_incident() -> None:
    now = [0.0]
    trigger = Trigger(MonitorSettings(trigger_cooldown_seconds=300), clock=lambda: now[0])
    bad = [signal("orders-service", 5, 5)]
    assert trigger.should_fire(snapshot(bad), Thresholds())
    trigger.should_fire(snapshot([]), Thresholds())
    now[0] = 100
    assert trigger.should_fire(snapshot(bad), Thresholds()) == []
    trigger.should_fire(snapshot([]), Thresholds())
    now[0] = 400
    assert trigger.should_fire(snapshot(bad), Thresholds())


def test_trigger_ignores_snapshots_older_than_its_start_and_repeats() -> None:
    trigger = Trigger(MonitorSettings())
    old = snapshot([signal("orders-service", 5, 5)])
    old.timestamp = utcnow() - timedelta(minutes=1)
    assert trigger.should_fire(old, Thresholds()) == []
    fresh = snapshot([signal("orders-service", 5, 5)])
    assert trigger.should_fire(fresh, Thresholds())
    assert trigger.should_fire(fresh, Thresholds()) == []


def test_probe_requests_are_not_logged_as_business_traffic() -> None:
    stream = io.StringIO()
    app = build_app(Settings(service_name="users-service"), log_stream=stream)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/health")
            await client.get("/metrics")
            await client.get("/users/1")

    asyncio.run(exercise())
    completed = [line for line in stream.getvalue().splitlines() if "request_completed" in line]
    assert len(completed) == 1 and '"/users/1"' in completed[0]


def test_not_triggered_counts_as_no_incident() -> None:
    observation: dict[str, Any] = {"baselines": {}, "ai": None}
    control = evaluate(SCENARIOS["normal"].expected, observation)["ai"]
    assert control["detection_correct"] is True and control["outcome"] == "not_triggered"
    missed = evaluate(SCENARIOS["orders_error"].expected, observation)["ai"]
    assert missed["detection_correct"] is False
