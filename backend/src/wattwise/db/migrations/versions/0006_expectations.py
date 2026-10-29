"""Stored model expectations and intervals for the evaluation windows (T030).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expectation_sets",
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("interval_nominal", sa.Float(), nullable=False),
        sa.Column("measured_coverage", sa.Float(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detection_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_expectation_sets"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_expectation_sets_dataset_id_datasets",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "expectations",
        sa.Column("meter_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected", postgresql.REAL(), nullable=True),
        sa.Column("lower", postgresql.REAL(), nullable=True),
        sa.Column("upper", postgresql.REAL(), nullable=True),
        sa.PrimaryKeyConstraint("meter_id", "timestamp", name="pk_expectations"),
        sa.ForeignKeyConstraint(
            ["meter_id"],
            ["meters.meter_id"],
            name="fk_expectations_meter_id_meters",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("expectations")
    op.drop_table("expectation_sets")
