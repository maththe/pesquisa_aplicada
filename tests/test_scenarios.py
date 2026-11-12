"""Gabarito, baselines, correlação hierárquica e injeção de falhas, sem Docker."""

import asyncio
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from app.config import Settings
from app.microservices.factory import build_app
from app.microservices.middleware import FaultInjectionMiddleware
from app.models import StructuredLog
from app.monitoring.models import DiagnosticRequest
from app.monitoring.storage import History, log_values, migrate, put_unique
from experiments.scenarios import SCENARIOS, Expected, baselines, evaluate, score


def check(status: int | None) -> dict[str, Any]:
    return {"status": status, "elapsed_ms": 1.0, "reachable": status is not None}


def test_health_baseline_misses_failure_behind_healthy_processes() -> None:
    health = {s: check(200) for s in ("gateway", "orders-service", "users-service")}
    result = baselines(health, [check(500), check(500)])
    assert result["health"] == {"incident": False, "service": None}
    assert result["probe"] == {"incident": True, "service": "gateway"}


def test_health_baseline_points_to_single_unhealthy_service() -> None:
    health = {"gateway": check(200), "orders-service": check(200), "users-service": check(None)}
    assert baselines(health, [check(503)])["health"] == {
        "incident": True,
        "service": "users-service",
    }


def test_score_requires_right_service_for_localization() -> None:
    expected = Expected(True, "orders-service", "erro interno")
    assert score(expected, {"incident": True, "service": "users-service"}) == {
        "incident": True,
        "service": "users-service",
        "detection_correct": True,
        "localization_correct": False,
    }
    control = score(Expected(False, None, "nenhuma"), {"incident": False, "service": None})
    assert control["detection_correct"] is True
    assert control["localization_correct"] is None


def test_ai_verdict_uses_first_hypothesis_with_service() -> None:
    observation = {
        "baselines": {"health": {"incident": False, "service": None}},
        "ai": {
            "outcome": "incident",
            "hypotheses": [
                {"service": None, "description": "cadeia", "evidence_ids": ["a"]},
                {"service": "orders-service", "description": "orders", "evidence_ids": ["a"]},
            ],
        },
    }
    result = evaluate(SCENARIOS["orders_error"].expected, observation)
    assert result["ai"]["localization_correct"] is True
    assert result["health"]["detection_correct"] is False


def test_insufficient_evidence_is_not_counted_as_detection() -> None:
    result = score(
        Expected(True, "users-service", "x"),
        {"incident": None, "service": None, "outcome": "insufficient_evidence"},
    )
    assert result["detection_correct"] is False


def test_every_incident_scenario_has_a_root_service() -> None:
    for scenario in SCENARIOS.values():
        assert (scenario.expected.service is not None) == scenario.expected.incident
    roots = {s.expected.service for s in SCENARIOS.values() if s.expected.incident}
    assert roots == {"users-service", "orders-service"}


def test_correlation_prefix_selects_children_only(tmp_path: Path) -> None:
    history = History(f"sqlite:///{tmp_path / 'history.db'}")
    migrate(history)
    now = datetime.now(UTC)
    with history.engine.begin() as connection:
        for request_id in ("burst-1.01", "burst-1.02", "burst-1", "burst-10.01", "other"):
            record = StructuredLog(
                service="gateway",
                level="INFO",
                event="request_completed",
                message="ok",
                request_id=request_id,
            )
            put_unique(connection, log_values(record))
    request = DiagnosticRequest(
        start=now - timedelta(minutes=1),
        end=now + timedelta(minutes=1),
        correlation_id="burst-1",
    )
    rows, _ = history.query(request, ["gateway"], 80)
    history.close()
    assert sorted(row["request_id"] for row in rows) == ["burst-1", "burst-1.01", "burst-1.02"]


def test_fault_rate_fails_deterministic_fraction() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        return

    middleware = FaultInjectionMiddleware(app, error_rate=0.5, latency_ms=0)
    assert [middleware.should_fail() for _ in range(6)] == [False, True] * 3
    always = FaultInjectionMiddleware(app, error_rate=1, latency_ms=0)
    assert all(always.should_fail() for _ in range(3))


def test_injected_error_looks_like_ordinary_exception() -> None:
    stream = io.StringIO()
    app = build_app(Settings(service_name="users-service", fault_error_rate=1), log_stream=stream)

    async def exercise() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            business = await client.get("/users/1", headers={"X-Request-ID": "req-1"})
            health = await client.get("/health")
        return business.status_code, health.status_code

    assert asyncio.run(exercise()) == (500, 200)
    logs = stream.getvalue()
    assert "unhandled_exception" in logs and "RuntimeError" in logs
    assert "fault" not in logs.lower()
