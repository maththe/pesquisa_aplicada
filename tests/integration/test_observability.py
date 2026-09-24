import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.observability.collector import collect_once, probe_service
from app.observability.config import MonitorSettings
from app.observability.context import build_context
from app.observability.current import CurrentState
from app.observability.database import migrate
from app.observability.diagnostics import diagnose, validate_response
from app.observability.ingestion import ingest_logs
from app.observability.models import (
    DiagnosticContext,
    DiagnosticRequest,
    DiagnosticResponse,
    Evidence,
    Metrics,
    Probe,
    Snapshot,
    utcnow,
)
from app.observability.providers import FakeProvider, LangChainProvider, make_provider
from app.observability.storage import History, checkpoints, evidence, rejections
from app.schemas.logs import StructuredLog
from pydantic import AnyHttpUrl, SecretStr, ValidationError
from sqlalchemy import event, func, select


@pytest.fixture
def history(tmp_path: Path) -> Iterator[History]:
    store = History(f"sqlite:///{tmp_path / 'history.db'}")
    migrate(store)
    migrate(store)  # Migrações são idempotentes.
    yield store
    store.close()


def request(correlation: str | None = None) -> DiagnosticRequest:
    now = utcnow()
    return DiagnosticRequest(
        start=now - timedelta(minutes=5), end=now + timedelta(seconds=5), correlation_id=correlation
    )


def write_log(directory: Path, event: StructuredLog, suffix: bytes = b"\n") -> None:
    with (directory / f"{event.service}.jsonl").open("ab") as output:
        output.write(event.model_dump_json().encode() + suffix)


def test_ingestion_partial_duplicate_restart_and_replacement(
    history: History, tmp_path: Path
) -> None:
    first = StructuredLog(
        service="gateway", level="INFO", event="request_completed", message="ok", request_id="r1"
    )
    second = first.model_copy(
        update={
            "log_id": StructuredLog(
                service="gateway", level="INFO", event="test", message="new"
            ).log_id
        }
    )
    write_log(tmp_path, first)
    write_log(tmp_path, second, suffix=b"")
    assert ingest_logs(history, tmp_path)["inserted"] == 1
    assert ingest_logs(history, tmp_path)["inserted"] == 0
    with (tmp_path / "gateway.jsonl").open("ab") as output:
        output.write(b"\n")
    assert ingest_logs(history, tmp_path)["inserted"] == 1
    write_log(tmp_path, first)
    assert ingest_logs(history, tmp_path)["duplicates"] == 1
    # Novo inode e conteúdo antigo: deduplicação persiste após rotação.
    replacement = tmp_path / "replacement"
    replacement.write_text(first.model_dump_json() + "\n", encoding="utf-8")
    replacement.replace(tmp_path / "gateway.jsonl")
    assert ingest_logs(history, tmp_path)["duplicates"] == 1
    with history.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(evidence)) == 2
    stored = history.get_evidence(str(first.log_id))
    assert (
        stored is not None
        and stored["data"]["timestamp"] == first.model_dump(mode="json")["timestamp"]
    )
    assert stored["ingested_at"] >= stored["timestamp"]


def test_ingestion_rejects_malformed_and_control_files(history: History, tmp_path: Path) -> None:
    (tmp_path / "gateway.jsonl").write_text("invalid\n", encoding="utf-8")
    other = StructuredLog(service="users-service", level="INFO", event="test", message="wrong")
    with (tmp_path / "gateway.jsonl").open("a", encoding="utf-8") as output:
        output.write(other.model_dump_json() + "\n")
    (tmp_path / "controle-experimental.jsonl").write_text(other.model_dump_json() + "\n")
    assert ingest_logs(history, tmp_path)["rejected"] == 2
    assert ingest_logs(history, tmp_path)["rejected"] == 0
    with history.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(evidence)) == 0
        assert connection.scalar(select(func.count()).select_from(rejections)) == 2


def test_checkpoint_rolls_back_with_log_transaction(
    history: History,
    tmp_path: Path,
) -> None:
    record = StructuredLog(service="gateway", level="INFO", event="test", message="rollback")
    write_log(tmp_path, record)

    def fail_checkpoint(*args: Any) -> None:
        statement = args[2]
        if statement.startswith("INSERT INTO log_checkpoints"):
            raise RuntimeError("checkpoint unavailable")

    event.listen(history.engine, "before_cursor_execute", fail_checkpoint)
    try:
        with pytest.raises(RuntimeError):
            ingest_logs(history, tmp_path)
    finally:
        event.remove(history.engine, "before_cursor_execute", fail_checkpoint)
    assert history.get_evidence(str(record.log_id)) is None
    with history.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(checkpoints)) == 0
    assert ingest_logs(history, tmp_path)["inserted"] == 1


def test_context_window_correlation_limits_and_original_ids(
    history: History, tmp_path: Path
) -> None:
    for index in range(12):
        write_log(
            tmp_path,
            StructuredLog(
                service="orders-service",
                level="ERROR",
                event="dependency_unavailable",
                message="Users unavailable " + "x" * 200,
                dependency="users-service",
                request_id="match" if index % 2 == 0 else "unrelated",
            ),
        )
    old = StructuredLog(
        service="gateway",
        level="ERROR",
        event="old",
        message="old",
        timestamp=utcnow() - timedelta(days=1),
        request_id="match",
    )
    write_log(tmp_path, old)
    ingest_logs(history, tmp_path)
    snapshot = Snapshot(services=[Probe(service="users-service", reachable=False, latency_ms=1)])
    history.save_snapshot(snapshot)
    settings = MonitorSettings(context_max_items=4, context_max_chars=3000)
    context = build_context(history, request("match"), settings)
    assert context.truncated and context.omitted_count == 7 - len(context.evidence)
    assert len(context.model_dump_json()) <= 3000
    assert any(item.kind == "snapshot" for item in context.evidence)
    assert any(item.kind == "log" for item in context.evidence)
    for item in context.evidence:
        stored = history.get_evidence(item.evidence_id)
        assert stored is not None and stored["data"] == item.data
        if item.kind == "log":
            assert item.data["request_id"] == "match"
            assert item.evidence_id != str(old.log_id)


@pytest.mark.parametrize("value", ["2026-09-24T12:00:00", "bad"])
def test_request_rejects_naive_or_invalid_time(value: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate({"start": value, "end": utcnow()})


def test_request_normalizes_offset_and_rejects_reversed_window() -> None:
    query = DiagnosticRequest.model_validate(
        {"start": "2026-09-24T09:00:00-03:00", "end": "2026-09-24T10:00:00-03:00"}
    )
    assert query.start == datetime(2026, 9, 24, 12, tzinfo=UTC)
    with pytest.raises(ValidationError):
        DiagnosticRequest(start=query.end, end=query.start)


async def test_probe_connection_timeout_and_invalid_metrics() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "down":
            raise httpx.ConnectError("down")
        if req.url.host == "slow":
            raise httpx.ReadTimeout("slow")
        if req.url.path == "/health":
            return httpx.Response(200, json={"service": "users-service", "status": "ok"})
        return httpx.Response(200, json={"invalid": "metrics"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        down = await probe_service(client, "users-service", "http://down")
        slow = await probe_service(client, "users-service", "http://slow")
        good = await probe_service(client, "users-service", "http://healthy")
    assert not down.reachable and down.error_type == "ConnectError" and down.metrics is None
    assert not slow.reachable and slow.error_type == "ReadTimeout"
    assert good.reachable and good.metrics is None and good.metrics_error == "ValidationError"


class MemoryCurrent(CurrentState):
    def __init__(self, fail: bool = False) -> None:
        self.snapshot: Snapshot | None = None
        self.fail = fail

    def publish(self, snapshot: Snapshot) -> None:
        if self.fail:
            raise ConnectionError("etcd unavailable")
        self.snapshot = snapshot

    def read(self) -> Snapshot | None:
        return self.snapshot

    def close(self) -> None:
        pass


@pytest.mark.parametrize("etcd_fails", [False, True])
async def test_collection_preserves_history_on_etcd_failure(
    history: History,
    tmp_path: Path,
    etcd_fails: bool,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        service = req.url.host
        if service == "users-service":
            raise httpx.ConnectError("unavailable")
        if req.url.path == "/health":
            return httpx.Response(200, json={"service": service, "status": "ok"})
        return httpx.Response(
            200,
            json=Metrics.model_validate({"service": service, "process_rss_bytes": 123}).model_dump(
                mode="json"
            ),
        )

    current = MemoryCurrent(fail=etcd_fails)
    result = await collect_once(
        MonitorSettings(log_dir=tmp_path),
        history,
        current,
        httpx.MockTransport(handler),
    )
    assert result["current_published"] is not etcd_fails
    stored = history.get_evidence(result["snapshot_id"])
    assert stored is not None
    users = next(
        probe for probe in stored["data"]["services"] if probe["service"] == "users-service"
    )
    assert users["metrics"] is None and users["reachable"] is False


class ScriptedProvider:
    name = "test-scripted"
    model = "fixture"
    simulated = True

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.calls: list[str | None] = []

    async def generate(self, context: DiagnosticContext, correction: str | None = None) -> str:
        self.calls.append(correction)
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


def example_context() -> DiagnosticContext:
    return DiagnosticContext(
        request=request("r1"),
        services=["gateway", "orders-service", "users-service"],
        evidence=[
            Evidence(
                evidence_id="log-1",
                kind="log",
                data={
                    "event": "dependency_unavailable",
                    "service": "orders-service",
                    "dependency": "users-service",
                    "request_id": "r1",
                },
            )
        ],
    )


def incident(evidence_id: str = "log-1") -> str:
    return json.dumps(
        {
            "outcome": "incident",
            "summary": "Indisponibilidade da dependência Users.",
            "evidence_ids": [evidence_id],
            "hypotheses": [
                {
                    "description": "Users inacessível; causa da indisponibilidade indeterminada.",
                    "service": "users-service",
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    )


async def test_invalid_evidence_repair_and_trace_are_persisted(history: History) -> None:
    provider = ScriptedProvider([incident("invented"), incident()])
    run = await diagnose(example_context(), provider, history)
    assert run.response.outcome == "incident"
    assert len(run.executions) == 2 and provider.calls[1] is not None
    assert run.executions[0].raw_response == incident("invented")
    assert run.executions[0].validation_error
    assert history.get_run(run.run_id) == run


async def test_two_invalid_outputs_stop_without_rule_fallback(history: History) -> None:
    provider = ScriptedProvider(["not json", incident("invented")])
    run = await diagnose(example_context(), provider, history)
    assert run.response.outcome == "failure"
    assert len(provider.calls) == 2
    assert run.response.hypotheses == []
    assert history.get_run(run.run_id) == run


async def test_provider_failure_recorded_without_credentials(history: History) -> None:
    provider = ScriptedProvider([ConnectionError("secret-key-123")])
    run = await diagnose(example_context(), provider, history)
    assert len(run.executions) == 1 and run.response.outcome == "failure"
    assert "secret-key-123" not in run.model_dump_json()


async def test_fake_is_explicit_and_does_not_diagnose_by_rules(history: History) -> None:
    run = await diagnose(example_context(), FakeProvider(), history)
    assert run.simulated and run.response.outcome == "insufficient_evidence"
    assert not run.response.hypotheses


async def test_http_provider_payload_and_real_marker(history: History) -> None:
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer test-key"
        captured.append(json.loads(req.content))
        return chat_completion(incident())

    settings = MonitorSettings(
        llm_provider="http",
        llm_url=AnyHttpUrl("https://provider.example/v1/chat/completions"),
        llm_model="test-model",
        llm_api_key=SecretStr("test-key"),
    )
    run = await diagnose(
        example_context(), LangChainProvider(settings, httpx.MockTransport(handler)), history
    )
    assert not run.simulated and run.response.outcome == "incident"
    assert captured[0]["model"] == "test-model" and "tools" not in captured[0]
    assert captured[0]["messages"][1]["content"] == run.context.model_dump_json()
    assert "test-key" not in run.model_dump_json()
    assert run.executions[0].provider == "langchain"


def test_invented_hypothesis_evidence_rejected() -> None:
    raw = json.loads(incident())
    raw["hypotheses"][0]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError, match="evidence_ids"):
        validate_response(json.dumps(raw), example_context())
    with pytest.raises(ValidationError):
        DiagnosticResponse(outcome="no_incident", summary="No support")


def chat_completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://provider.example/v1",
        "https://provider.example/v1/",
        "https://provider.example/v1/chat/completions",
        "https://provider.example/v1/chat/completions/",
    ],
)
async def test_langchain_accepts_base_and_complete_url(url: str) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return chat_completion(incident())

    provider = LangChainProvider(
        MonitorSettings(
            llm_provider="langchain",
            llm_url=AnyHttpUrl(url),
            llm_model="test-model",
            llm_api_key=SecretStr("test-key"),
        ),
        httpx.MockTransport(handler),
    )
    assert await provider.generate(example_context()) == incident()
    assert seen == ["https://provider.example/v1/chat/completions"]


async def test_langchain_query_and_empty_key_do_not_use_ambient_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-secret")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert "Authorization" not in req.headers
        seen.append(str(req.url))
        return chat_completion(incident())

    provider = LangChainProvider(
        MonitorSettings(
            llm_provider="langchain",
            llm_url=AnyHttpUrl("http://localhost:11434/v1/chat/completions?api-version=test"),
            llm_model="test-model",
            llm_api_key=SecretStr(""),
        ),
        httpx.MockTransport(handler),
    )
    assert await provider.generate(example_context()) == incident()
    assert seen == ["http://localhost:11434/v1/chat/completions?api-version=test"]


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_langchain_transport_errors_have_no_hidden_retries(
    history: History,
    status: int,
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "Upstream unavailable",
                    "type": "server_error",
                    "code": "test",
                }
            },
        )

    provider = LangChainProvider(
        MonitorSettings(
            llm_provider="langchain",
            llm_url=AnyHttpUrl("https://provider.example/v1"),
            llm_model="test-model",
            llm_api_key=SecretStr("test-key"),
        ),
        httpx.MockTransport(handler),
    )
    run = await diagnose(example_context(), provider, history)
    assert run.response.outcome == "failure"
    assert len(calls) == 1 and len(run.executions) == 1
    assert run.executions[0].provider == "langchain"
    assert "test-key" not in run.model_dump_json()
    assert history.get_run(run.run_id) == run


@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_langchain_repairs_evidence_and_preserves_raw_output(
    history: History,
    repair_succeeds: bool,
) -> None:
    messages: list[list[dict[str, Any]]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        assert "tools" not in payload
        assert payload["response_format"] == {"type": "json_object"}
        messages.append(payload["messages"])
        return chat_completion(
            incident() if len(messages) == 2 and repair_succeeds else incident("invented")
        )

    context = example_context()
    context.evidence[0].data["message"] = 'Dado com chaves: {"campo": "{variavel}"}'
    provider = LangChainProvider(
        MonitorSettings(
            llm_provider="langchain",
            llm_url=AnyHttpUrl("https://provider.example/v1"),
            llm_model="test-model",
            llm_api_key=SecretStr("test-key"),
        ),
        httpx.MockTransport(handler),
    )
    run = await diagnose(context, provider, history)
    assert run.response.outcome == ("incident" if repair_succeeds else "failure")
    assert len(messages) == len(run.executions) == 2
    assert len(messages[0]) == 2 and len(messages[1]) == 3
    assert messages[0][1]["content"] == context.model_dump_json()
    assert messages[1][1] == messages[0][1]
    assert "evidence_ids" in messages[1][2]["content"]
    assert run.executions[0].raw_response == incident("invented")
    assert run.executions[0].validation_error is not None
    assert history.get_run(run.run_id) == run


@pytest.mark.parametrize("provider_name", ["langchain", "http"])
def test_provider_factory_accepts_current_and_legacy_setting(provider_name: str) -> None:
    settings = MonitorSettings.model_validate(
        {
            "llm_provider": provider_name,
            "llm_url": "https://provider.example/v1",
            "llm_model": "test-model",
        }
    )
    assert isinstance(make_provider(settings), LangChainProvider)
    assert make_provider(settings).name == "langchain"
    with pytest.raises(ValidationError, match="OBS_LLM_URL"):
        MonitorSettings.model_validate({"llm_provider": provider_name})


async def test_langchain_rejects_oversized_output() -> None:
    provider = LangChainProvider(
        MonitorSettings(
            llm_provider="langchain",
            llm_url=AnyHttpUrl("https://provider.example/v1"),
            llm_model="test-model",
            llm_api_key=SecretStr("test-key"),
        ),
        httpx.MockTransport(lambda request: chat_completion("x" * 100001)),
    )
    with pytest.raises(ValueError, match="limite"):
        await provider.generate(example_context())
