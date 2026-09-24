import hashlib
import os
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, insert, select

from app.observability.models import utcnow
from app.observability.storage import (
    History,
    checkpoints,
    log_values,
    put_unique,
    rejections,
    timestamp,
)
from app.schemas.logs import StructuredLog

SERVICES = ("gateway", "orders-service", "users-service")
MAX_LINE_BYTES = 1024 * 1024


def ingest_logs(history: History, directory: Path) -> dict[str, int]:
    counts = {"inserted": 0, "duplicates": 0, "rejected": 0, "missing_files": 0}
    # Lista fechada: arquivos experimentais nunca são ingeridos.
    for service in SERVICES:
        path = directory / f"{service}.jsonl"
        if not path.is_file():
            counts["missing_files"] += 1
            continue
        with path.open("rb") as source, history.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(87042001)")
            stat = os.fstat(source.fileno())
            prefix = source.read(64)
            identity = f"{stat.st_dev}:{stat.st_ino}:{hashlib.sha256(prefix).hexdigest()}"
            previous = (
                connection.execute(select(checkpoints).where(checkpoints.c.path == str(path)))
                .mappings()
                .first()
            )
            offset = (
                int(previous["offset"])
                if (
                    previous
                    and previous["identity"] == identity
                    and previous["offset"] <= stat.st_size
                )
                else 0
            )
            source.seek(offset)
            for _ in range(1000):
                start = source.tell()
                line = source.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    # Descarta uma linha grande por inteiro, sem carregar tudo na memória.
                    while line and not line.endswith(b"\n"):
                        line = source.readline(MAX_LINE_BYTES + 1)
                    if not line.endswith(b"\n"):
                        source.seek(start)
                        break
                    error = "line_too_large"
                elif not line.endswith(b"\n"):
                    source.seek(start)
                    break  # Escrita em andamento: só avançar quando houver newline.
                else:
                    try:
                        record = StructuredLog.model_validate_json(line)
                        if record.service != service:
                            raise ValueError("service_does_not_match_file")
                        added = put_unique(connection, log_values(record))
                        counts["inserted" if added else "duplicates"] += 1
                        continue
                    except (ValidationError, ValueError) as exc:
                        error = type(exc).__name__
                connection.execute(
                    insert(rejections).values(
                        path=str(path), offset=start, error=error, ingested_at=timestamp(utcnow())
                    )
                )
                counts["rejected"] += 1
            connection.execute(delete(checkpoints).where(checkpoints.c.path == str(path)))
            connection.execute(
                insert(checkpoints).values(path=str(path), identity=identity, offset=source.tell())
            )
    return counts
