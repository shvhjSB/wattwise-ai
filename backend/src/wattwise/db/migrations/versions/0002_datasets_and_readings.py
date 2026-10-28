"""Datasets (synthetic or observed) and readings (T024).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28

Every building now belongs to a dataset. `buildings.dataset_id` is NOT NULL; the baseline was
only ever empty, so there are no rows to backfill (the upgrade fails loudly if there are).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_datasets"),
        sa.CheckConstraint("kind IN ('observed', 'synthetic')", name="ck_datasets_kind"),
    )
    op.add_column("buildings", sa.Column("dataset_id", sa.String(128), nullable=False))
    op.create_foreign_key(
        "fk_buildings_dataset_id_datasets",
        "buildings",
        "datasets",
        ["dataset_id"],
        ["dataset_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_buildings_dataset_id", "buildings", ["dataset_id"])
    op.create_table(
        "readings",
        sa.Column("meter_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("meter_id", "timestamp", name="pk_readings"),
        sa.ForeignKeyConstraint(
            ["meter_id"],
            ["meters.meter_id"],
            name="fk_readings_meter_id_meters",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("readings")
    op.drop_index("ix_buildings_dataset_id", table_name="buildings")
    op.drop_constraint("fk_buildings_dataset_id_datasets", "buildings", type_="foreignkey")
    op.drop_column("buildings", "dataset_id")
    op.drop_table("datasets")
