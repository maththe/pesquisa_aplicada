import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import TextIO

from app.config import LogLevel, ServiceName
from app.schemas.logs import StructuredLog

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class EventLogger:
    def __init__(
        self,
        service: ServiceName,
        level: LogLevel = "INFO",
        log_dir: Path | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self.service = service
        self.logger = logging.Logger(service, level=level)
        self.logger.propagate = False
        self.logger.addHandler(logging.StreamHandler(stream if stream is not None else sys.stdout))
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.logger.addHandler(
                logging.FileHandler(log_dir / f"{service}.jsonl", encoding="utf-8")
            )

    def emit(
        self,
        level: LogLevel,
        event: str,
        message: str,
        *,
        dependency: ServiceName | None = None,
        duration_ms: float | None = None,
        method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        record = StructuredLog(
            service=self.service,
            level=level,
            event=event,
            message=message,
            request_id=request_id_context.get(),
            dependency=dependency,
            duration_ms=duration_ms,
            method=method,
            path=path,
            status_code=status_code,
            error_type=error_type,
        )
        self.logger.log(logging.getLevelNamesMapping()[level], record.model_dump_json())

    def close(self) -> None:
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
