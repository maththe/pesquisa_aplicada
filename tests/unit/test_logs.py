from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
from app.schemas.logs import StructuredLog
from app.telemetry import EventLogger, request_id_context
from pydantic import ValidationError
from tests.helpers import read_events


def test_log_identity_utc_and_missing_metrics() -> None:
    first = StructuredLog(service="orders-service", level="INFO", event="test", message="Test")
    second = StructuredLog(service="orders-service", level="INFO", event="test", message="Test")
    assert first.log_id != second.log_id
    assert first.timestamp.tzinfo == UTC
    assert first.duration_ms is None
    assert first.status_code is None
    assert first.request_id is None
    assert first.model_dump(mode="json")["duration_ms"] is None


def test_log_normalizes_timezone() -> None:
    local = datetime(2026, 9, 17, 15, 42, tzinfo=timezone(timedelta(hours=-3)))
    event = StructuredLog(
        service="users-service", level="INFO", event="test", message="Test", timestamp=local
    )
    assert event.timestamp == datetime(2026, 9, 17, 18, 42, tzinfo=UTC)
    assert event.timestamp.tzinfo == UTC


def test_log_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        StructuredLog(
            service="gateway",
            level="INFO",
            event="test",
            message="Test",
            timestamp=datetime(2026, 9, 17, 18, 42),
        )


def test_stdout_and_file_share_id_and_preserve_existing_logs(tmp_path: Path) -> None:
    stream = StringIO()
    for _ in range(2):
        logger = EventLogger("gateway", log_dir=tmp_path, stream=stream)
        token = request_id_context.set("req-123")
        try:
            logger.emit("INFO", "example", "Mensagem\ncom quebra de linha")
        finally:
            request_id_context.reset(token)
            logger.close()
    records = read_events(stream)
    file_records = [
        StructuredLog.model_validate_json(line)
        for line in (tmp_path / "gateway.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(file_records) == 2
    assert file_records == records
    assert records[0].request_id == "req-123"
    assert records[0].log_id != records[1].log_id
    assert request_id_context.get() is None
