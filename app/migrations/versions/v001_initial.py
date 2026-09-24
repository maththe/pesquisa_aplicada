"""Histórico de evidências, checkpoints e execuções."""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("ingested_at", sa.String(40), nullable=False),
        sa.Column("service", sa.String(64)),
        sa.Column("dependency", sa.String(64)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    for column in ("timestamp", "service", "request_id"):
        op.create_index(f"ix_evidence_{column}", "evidence", [column])
    op.create_table(
        "log_checkpoints",
        sa.Column("path", sa.String(1024), primary_key=True),
        sa.Column("identity", sa.String(128), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "log_rejections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("error", sa.String(200), nullable=False),
        sa.Column("ingested_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "diagnostic_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_diagnostic_runs_timestamp", "diagnostic_runs", ["timestamp"])


def downgrade() -> None:
    for name in ("diagnostic_runs", "log_rejections", "log_checkpoints", "evidence"):
        op.drop_table(name)
