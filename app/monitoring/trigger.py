"""Gatilho automático: observa o snapshot no etcd e aciona o diagnóstico.

A cada snapshot publicado pelo coletor, compara os sinais com os limites guardados
no etcd. Na primeira violação de um incidente, pede o diagnóstico da janela recente
e registra o motivo e o resultado em `/observability/trigger/last`.

Proteções contra gasto com a LLM: um diagnóstico por incidente (o gatilho só se
rearma depois de um snapshot sem violações) e intervalo mínimo entre diagnósticos.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.config import MonitorSettings
from app.monitoring.context import build_context
from app.monitoring.current import CURRENT_KEY, CurrentState, etcd_client
from app.monitoring.diagnostics import diagnose
from app.monitoring.models import (
    DiagnosticRequest,
    Snapshot,
    Thresholds,
    Violation,
    new_id,
    utcnow,
)
from app.monitoring.providers import LangChainProvider
from app.monitoring.storage import History


def find_violations(snapshot: Snapshot, thresholds: Thresholds) -> list[Violation]:
    found: list[Violation] = []
    if thresholds.unreachable:
        found += [
            Violation(service=probe.service, metric="unreachable")
            for probe in snapshot.services
            if not probe.reachable
        ]
    for signal in snapshot.signals:
        if signal.requests < thresholds.min_requests:
            continue
        if signal.error_rate is not None and signal.error_rate > thresholds.error_rate:
            found.append(
                Violation(
                    service=signal.service,
                    metric="error_rate",
                    value=signal.error_rate,
                    limit=thresholds.error_rate,
                )
            )
        if signal.p95_ms is not None and signal.p95_ms > thresholds.p95_ms:
            found.append(
                Violation(
                    service=signal.service,
                    metric="p95_ms",
                    value=signal.p95_ms,
                    limit=thresholds.p95_ms,
                )
            )
    return found


class Trigger:
    def __init__(
        self,
        settings: MonitorSettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.started_at = utcnow()
        self.armed = True
        self.last_fired: float | None = None
        self.last_snapshot_id: str | None = None

    def should_fire(self, snapshot: Snapshot, thresholds: Thresholds) -> list[Violation]:
        """Violações que justificam um diagnóstico agora; lista vazia caso contrário."""
        if snapshot.snapshot_id == self.last_snapshot_id or snapshot.timestamp < self.started_at:
            return []  # Repetido ou anterior ao início do gatilho.
        self.last_snapshot_id = snapshot.snapshot_id
        violations = find_violations(snapshot, thresholds)
        if not violations:
            self.armed = True
            return []
        cooling = (
            self.last_fired is not None
            and self.clock() - self.last_fired < self.settings.trigger_cooldown_seconds
        )
        if not self.armed or cooling:
            return []
        self.armed = False
        self.last_fired = self.clock()
        return violations


def investigate(
    settings: MonitorSettings,
    history: History,
    current: CurrentState,
    snapshot: Snapshot,
    violations: list[Violation],
    thresholds: Thresholds,
) -> dict[str, Any]:
    end = utcnow()
    record: dict[str, Any] = {
        "trigger_id": new_id(),
        "status": "running",
        "triggered_at": end.isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "violations": [violation.model_dump() for violation in violations],
        "thresholds": thresholds.model_dump(),
    }
    current.write_trigger(record)
    # O motivo do alerta não entra no contexto: a IA analisa as mesmas evidências
    # de uma investigação manual, sem receber o serviço suspeito pronto.
    request = DiagnosticRequest(
        start=end - timedelta(seconds=settings.trigger_lookback_seconds),
        end=end,
        service="gateway",
    )
    context = build_context(history, request, settings)
    try:
        run = asyncio.run(diagnose(context, LangChainProvider(settings), history))
    except Exception as exc:
        record.update(status="failed", error=type(exc).__name__)
    else:
        record.update(
            status="done",
            run_id=run.run_id,
            outcome=run.response.outcome,
            finished_at=utcnow().isoformat(),
        )
    current.write_trigger(record)
    return record


def watch(settings: MonitorSettings, emit: Callable[[Any], None]) -> None:
    """Reage a cada mudança da chave do snapshot (watch do etcd), com sondagem de reserva."""
    settings.require_llm()
    history = History(settings.database_url)
    current = CurrentState(settings)
    trigger = Trigger(settings)
    changed = threading.Event()

    def listen() -> None:
        # Cliente sem timeout: o stream de watch fica aberto entre snapshots.
        while True:
            try:
                events, _cancel = etcd_client(settings, None).watch(CURRENT_KEY)
                for _ in events:
                    changed.set()
            except Exception:
                time.sleep(2)

    threading.Thread(target=listen, daemon=True).start()
    thresholds = current.read_thresholds()
    emit({"status": "watching", "key": CURRENT_KEY, "thresholds": thresholds.model_dump()})
    try:
        while True:
            changed.wait(timeout=settings.interval_seconds)
            changed.clear()
            try:
                snapshot = current.read()
                if snapshot is None:
                    continue
                thresholds = current.read_thresholds()
                violations = trigger.should_fire(snapshot, thresholds)
                if violations:
                    emit(
                        {"status": "triggered", "violations": [v.model_dump() for v in violations]}
                    )
                    emit(investigate(settings, history, current, snapshot, violations, thresholds))
            except Exception as exc:
                emit({"status": "watch_error", "error": type(exc).__name__})
    finally:
        current.close()
        history.close()
