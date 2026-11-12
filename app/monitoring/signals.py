"""Sinais de negócio por serviço: volume, erros e latência das requisições recentes.

Health checks dizem se o processo responde; estes sinais dizem se o serviço está
atendendo bem. São calculados a partir dos logs já ingeridos e publicados no etcd
junto com o snapshot, onde o gatilho automático os compara com os limites.
"""

import math
from datetime import timedelta
from typing import Any

from app.config import ServiceName
from app.monitoring.models import ServiceSignals, utcnow
from app.monitoring.storage import History

SERVICES: tuple[ServiceName, ...] = ("gateway", "orders-service", "users-service")
DEPENDENCY_FAILURES = {"dependency_unavailable", "dependency_timeout", "dependency_http_error"}


def percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(0.95 * len(ordered)) - 1], 2)


def compute_signals(logs: list[dict[str, Any]], window_seconds: int) -> list[ServiceSignals]:
    signals: list[ServiceSignals] = []
    for service in SERVICES:
        own = [log for log in logs if log.get("service") == service]
        completed = [log for log in own if log.get("event") == "request_completed"]
        errors = sum((log.get("status_code") or 0) >= 500 for log in completed)
        durations = [
            float(log["duration_ms"]) for log in completed if log.get("duration_ms") is not None
        ]
        signals.append(
            ServiceSignals(
                service=service,
                window_seconds=window_seconds,
                requests=len(completed),
                errors=errors,
                error_rate=round(errors / len(completed), 4) if completed else None,
                p95_ms=percentile_95(durations),
                dependency_failures=sum(log.get("event") in DEPENDENCY_FAILURES for log in own),
            )
        )
    return signals


def business_signals(history: History, window_seconds: int) -> list[ServiceSignals]:
    since = utcnow() - timedelta(seconds=window_seconds)
    return compute_signals(history.recent_logs(since), window_seconds)
