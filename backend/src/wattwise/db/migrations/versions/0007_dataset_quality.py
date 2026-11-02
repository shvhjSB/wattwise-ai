"""The stored data-quality audit of each dataset (T047).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_quality",
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("quality_version", sa.String(16), nullable=False),
        sa.Column("contract_version", sa.String(16), nullable=False),
        sa.Column(
            "assessed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("meters", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_dataset_quality"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_dataset_quality_dataset_id_datasets",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("dataset_quality")
