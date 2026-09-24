from itertools import zip_longest

from app.config import ServiceName
from app.observability.config import MonitorSettings
from app.observability.models import DiagnosticContext, DiagnosticRequest, Evidence
from app.observability.storage import History

DEPENDENCIES: dict[ServiceName, list[ServiceName]] = {
    "gateway": ["orders-service", "users-service"],
    "orders-service": ["users-service"],
    "users-service": [],
}


def related_services(service: ServiceName | None) -> list[ServiceName]:
    if service is None:
        return list(DEPENDENCIES)
    selected: set[ServiceName] = set()
    pending = [service]
    while pending:
        item = pending.pop()
        if item not in selected:
            selected.add(item)
            pending.extend(DEPENDENCIES[item])
    return [item for item in DEPENDENCIES if item in selected]


def build_context(
    history: History,
    request: DiagnosticRequest,
    settings: MonitorSettings,
) -> DiagnosticContext:
    services = related_services(request.service)
    rows, total = history.query(request, list(services), settings.context_max_items)
    logs = [row for row in rows if row["kind"] == "log"]
    snapshots = [row for row in rows if row["kind"] == "snapshot"]
    missing: list[str] = []
    if not logs:
        missing.append(
            "Nenhum log encontrado para os filtros; isso não comprova ausência de falha."
        )
    if not snapshots:
        missing.append("Nenhum snapshot encontrado na janela.")
    missing.append(
        "Health verifica o processo local; CPU/memória do sistema refletem o ambiente "
        "visível ao processo, não uma medição isolada de limites do container."
    )
    context = DiagnosticContext(
        request=request,
        services=services,
        evidence=[],
        missing_data=missing,
    )
    # Alternar tipos evita que sondagens frequentes excluam todos os logs.
    for pair in zip_longest(logs, snapshots):
        for row in pair:
            if row is None:
                continue
            item = Evidence(evidence_id=row["id"], kind=row["kind"], data=row["data"])
            candidate = context.model_copy(update={"evidence": [*context.evidence, item]})
            # Reserva espaço para os metadados de truncamento.
            if (
                len(candidate.evidence) <= settings.context_max_items
                and len(candidate.model_dump_json()) <= settings.context_max_chars - 200
            ):
                context.evidence.append(item)
    context.omitted_count = total - len(context.evidence)
    context.truncated = context.omitted_count > 0
    return context
