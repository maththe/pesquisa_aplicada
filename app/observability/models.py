from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import ServiceName


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("timestamp", "start", "end", check_fields=False)
    @classmethod
    def normalize_utc_datetime(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class Metrics(StrictModel):
    service: ServiceName
    timestamp: AwareDatetime = Field(default_factory=utcnow)
    scope: Literal["service_process_and_visible_system"] = "service_process_and_visible_system"
    process_rss_bytes: int | None = Field(default=None, ge=0)
    process_threads: int | None = Field(default=None, ge=0)
    system_cpu_percent: float | None = Field(default=None, ge=0, le=100)
    system_memory_percent: float | None = Field(default=None, ge=0, le=100)


class Probe(StrictModel):
    service: ServiceName
    reachable: bool
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: float = Field(ge=0)
    error_type: str | None = None
    metrics: Metrics | None = None
    metrics_error: str | None = None


class Snapshot(StrictModel):
    snapshot_id: str = Field(default_factory=new_id)
    timestamp: AwareDatetime = Field(default_factory=utcnow)
    services: list[Probe]


class DiagnosticRequest(StrictModel):
    request_id: str = Field(default_factory=new_id)
    start: AwareDatetime
    end: AwareDatetime
    service: ServiceName | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start deve ser anterior a end")
        if (self.end - self.start).total_seconds() > 86400:
            raise ValueError("Janela máxima de 24 horas")
        return self


class Evidence(StrictModel):
    evidence_id: str
    kind: Literal["log", "snapshot"]
    data: dict[str, Any]


class DiagnosticContext(StrictModel):
    context_id: str = Field(default_factory=new_id)
    request: DiagnosticRequest
    services: list[ServiceName]
    evidence: list[Evidence]
    missing_data: list[str] = Field(default_factory=list)
    truncated: bool = False
    omitted_count: int = 0
    prompt_version: str = "v1"


class Hypothesis(StrictModel):
    description: str = Field(min_length=1, max_length=3000)
    service: ServiceName | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=80)


class DiagnosticResponse(StrictModel):
    outcome: Literal["incident", "no_incident", "insufficient_evidence", "failure"]
    summary: str = Field(min_length=1, max_length=4000)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def require_support(self) -> Self:
        if self.outcome in ("incident", "no_incident") and not self.evidence_ids:
            raise ValueError("Conclusões exigem evidence_ids")
        if self.outcome == "incident" and not self.hypotheses:
            raise ValueError("Incidente exige ao menos uma hipótese com evidências")
        return self


class LLMExecution(StrictModel):
    execution_id: str = Field(default_factory=new_id)
    timestamp: AwareDatetime = Field(default_factory=utcnow)
    provider: str
    model: str
    simulated: bool
    attempt: int
    duration_ms: float
    raw_response: str | None = None
    validation_error: str | None = None


class DiagnosticRun(StrictModel):
    run_id: str = Field(default_factory=new_id)
    timestamp: AwareDatetime = Field(default_factory=utcnow)
    context: DiagnosticContext
    executions: list[LLMExecution]
    response: DiagnosticResponse
    simulated: bool
