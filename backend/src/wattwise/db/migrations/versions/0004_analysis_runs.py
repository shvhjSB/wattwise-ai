"""Analysis-run monitoring records (T027).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("detector", sa.String(32), nullable=False),
        sa.Column("input_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meters", sa.Integer(), nullable=False),
        sa.Column("readings", sa.Integer(), nullable=False),
        sa.Column("missing_values", sa.Integer(), nullable=False),
        sa.Column("predictions", sa.Integer(), nullable=False),
        sa.Column("alerts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_analysis_runs"),
        sa.CheckConstraint("input_end >= input_start", name="ck_analysis_runs_input_range"),
    )
    op.create_index("ix_analysis_runs_created_at", "analysis_runs", ["created_at"])
    op.create_index("ix_analysis_runs_model_version", "analysis_runs", ["model_version"])


def downgrade() -> None:
    op.drop_table("analysis_runs")
