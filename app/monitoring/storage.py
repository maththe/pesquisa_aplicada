from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.engine import Connection
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import ColumnElement

from app.models import StructuredLog
from app.monitoring.models import DiagnosticRequest, DiagnosticRun, Snapshot, utcnow

metadata = MetaData()
evidence = Table(
    "evidence",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("timestamp", String(40), nullable=False, index=True),
    Column("ingested_at", String(40), nullable=False),
    Column("service", String(64), index=True),
    Column("dependency", String(64)),
    Column("request_id", String(128), index=True),
    Column("data", JSON, nullable=False),
)
checkpoints = Table(
    "log_checkpoints",
    metadata,
    Column("path", String(1024), primary_key=True),
    Column("identity", String(128), nullable=False),
    Column("offset", BigInteger, nullable=False),
)
rejections = Table(
    "log_rejections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("path", String(1024), nullable=False),
    Column("offset", BigInteger, nullable=False),
    Column("error", String(200), nullable=False),
    Column("ingested_at", String(40), nullable=False),
)
runs = Table(
    "diagnostic_runs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("timestamp", String(40), nullable=False, index=True),
    Column("data", JSON, nullable=False),
)


def timestamp(value: datetime) -> str:
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def put_unique(connection: Connection, values: dict[str, Any]) -> bool:
    # Ambas as implementações são atômicas: reler um arquivo não duplica eventos.
    statement: Insert
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        statement = pg_insert(evidence)
    else:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = sqlite_insert(evidence)
    statement = (
        statement.values(**values)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(evidence.c.id)
    )
    return connection.execute(statement).scalar_one_or_none() is not None


def log_values(record: StructuredLog) -> dict[str, Any]:
    return {
        "id": str(record.log_id),
        "kind": "log",
        "timestamp": timestamp(record.timestamp),
        "ingested_at": timestamp(utcnow()),
        "service": record.service,
        "dependency": record.dependency,
        "request_id": record.request_id,
        "data": record.model_dump(mode="json"),
    }


class History:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, pool_pre_ping=True)

    def save_snapshot(self, snapshot: Snapshot) -> None:
        with self.engine.begin() as connection:
            put_unique(
                connection,
                {
                    "id": snapshot.snapshot_id,
                    "kind": "snapshot",
                    "timestamp": timestamp(snapshot.timestamp),
                    "ingested_at": timestamp(utcnow()),
                    "data": snapshot.model_dump(mode="json"),
                },
            )

    def query(
        self,
        request: DiagnosticRequest,
        services: list[str],
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[ColumnElement[bool]] = [
            evidence.c.timestamp >= timestamp(request.start),
            evidence.c.timestamp <= timestamp(request.end),
            or_(
                evidence.c.kind == "snapshot",
                evidence.c.service.in_(services),
                evidence.c.dependency.in_(services),
            ),
        ]
        if request.correlation_id:
            clauses.append(
                or_(evidence.c.kind == "snapshot", evidence.c.request_id == request.correlation_id)
            )
        with self.engine.connect() as connection:
            count = int(
                connection.execute(
                    select(func.count()).select_from(evidence).where(*clauses)
                ).scalar_one()
            )
            # Logs da requisição têm prioridade; snapshots ocupam a outra metade da cota.
            rows: list[dict[str, Any]] = []
            for kind in ("log", "snapshot"):
                results = connection.execute(
                    select(evidence)
                    .where(*clauses, evidence.c.kind == kind)
                    .order_by(evidence.c.timestamp.desc(), evidence.c.id)
                    .limit(limit)
                ).mappings()
                rows.extend(dict(row) for row in results)
        return rows, count

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(evidence).where(evidence.c.id == evidence_id))
                .mappings()
                .first()
            )
            return dict(row) if row is not None else None

    def save_run(self, run: DiagnosticRun) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(runs).values(
                    id=run.run_id,
                    timestamp=timestamp(run.timestamp),
                    data=run.model_dump(mode="json"),
                )
            )

    def get_run(self, run_id: str) -> DiagnosticRun | None:
        with self.engine.connect() as connection:
            data = connection.execute(
                select(runs.c.data).where(runs.c.id == run_id)
            ).scalar_one_or_none()
            return DiagnosticRun.model_validate(data) if data is not None else None

    def recent_runs(self, limit: int = 20) -> list[DiagnosticRun]:
        with self.engine.connect() as connection:
            records = connection.execute(
                select(runs.c.data).order_by(runs.c.timestamp.desc()).limit(limit)
            ).scalars()
            return [DiagnosticRun.model_validate(item) for item in records]

    def close(self) -> None:
        self.engine.dispose()


def migrate(history: History) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    with history.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
