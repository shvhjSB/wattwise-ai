"""Baseline: buildings and meters (T023).

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out, not imported from the models, so this migration never changes when they do.
METER_TYPES = (
    "'chilledwater', 'electricity', 'gas', 'hotwater', 'irrigation', 'solar', 'steam', 'water'"
)
KWH_TYPES = "'chilledwater', 'electricity', 'gas', 'hotwater', 'solar', 'steam'"
M3_TYPES = "'irrigation', 'water'"


def upgrade() -> None:
    op.create_table(
        "buildings",
        sa.Column("building_id", sa.String(128), nullable=False),
        sa.Column("site_id", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("primary_use", sa.Text(), nullable=True),
        sa.Column("floor_area_m2", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("building_id", name="pk_buildings"),
        sa.CheckConstraint("floor_area_m2 > 0", name="ck_buildings_floor_area_positive"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_buildings_latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_buildings_longitude_range"),
    )
    op.create_index("ix_buildings_site_id", "buildings", ["site_id"])
    op.create_table(
        "meters",
        sa.Column("meter_id", sa.String(128), nullable=False),
        sa.Column("building_id", sa.String(128), nullable=False),
        sa.Column("meter_type", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("meter_id", name="pk_meters"),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.building_id"],
            name="fk_meters_building_id_buildings",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"meter_type IN ({METER_TYPES})", name="ck_meters_meter_type"),
        sa.CheckConstraint("unit IN ('kWh', 'm3')", name="ck_meters_unit"),
        sa.CheckConstraint(
            f"(meter_type IN ({KWH_TYPES}) AND unit = 'kWh') "
            f"OR (meter_type IN ({M3_TYPES}) AND unit = 'm3')",
            name="ck_meters_canonical_unit",
        ),
    )
    op.create_index("ix_meters_building_id", "meters", ["building_id"])


def downgrade() -> None:
    op.drop_index("ix_meters_building_id", table_name="meters")
    op.drop_table("meters")
    op.drop_index("ix_buildings_site_id", table_name="buildings")
    op.drop_table("buildings")
