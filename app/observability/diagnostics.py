from time import perf_counter

from pydantic import ValidationError

from app.observability.models import (
    DiagnosticContext,
    DiagnosticResponse,
    DiagnosticRun,
    LLMExecution,
)
from app.observability.providers import LLMProvider
from app.observability.storage import History


def validate_response(raw: str, context: DiagnosticContext) -> DiagnosticResponse:
    response = DiagnosticResponse.model_validate_json(raw)
    allowed = {item.evidence_id for item in context.evidence}
    cited = set(response.evidence_ids)
    for hypothesis in response.hypotheses:
        cited.update(hypothesis.evidence_ids)
        if hypothesis.service is not None and hypothesis.service not in context.services:
            raise ValueError("Hipótese refere serviço fora do contexto")
    if not cited <= allowed:
        raise ValueError("Resposta contém evidence_ids que não estão no contexto")
    return response


async def diagnose(
    context: DiagnosticContext,
    provider: LLMProvider,
    history: History,
) -> DiagnosticRun:
    executions: list[LLMExecution] = []
    response: DiagnosticResponse | None = None
    correction: str | None = None
    for attempt in (1, 2):
        started = perf_counter()
        raw: str | None = None
        error: str | None = None
        provider_failed = False
        try:
            raw = await provider.generate(context, correction)
        except Exception as exc:
            # Não persistir mensagens de transporte que podem conter URLs/chaves.
            error = f"provider_error:{type(exc).__name__}"
            provider_failed = True
        if not provider_failed:
            try:
                assert raw is not None
                response = validate_response(raw, context)
            except (ValidationError, ValueError) as exc:
                error = str(exc)[:2000]
        executions.append(
            LLMExecution(
                provider=provider.name,
                model=provider.model,
                simulated=provider.simulated,
                attempt=attempt,
                duration_ms=(perf_counter() - started) * 1000,
                raw_response=raw,
                validation_error=error,
            )
        )
        if response is not None or provider_failed:
            break
        correction = error
    if response is None:
        response = DiagnosticResponse(
            outcome="failure",
            summary="Não foi possível obter uma resposta válida do provedor.",
            limitations=[executions[-1].validation_error or "Falha desconhecida"],
        )
    run = DiagnosticRun(
        context=context,
        executions=executions,
        response=response,
        simulated=provider.simulated,
    )
    history.save_run(run)
    return run
