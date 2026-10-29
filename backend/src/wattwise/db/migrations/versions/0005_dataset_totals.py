"""Dataset totals, computed once at load time (T029).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29

Adds the totals and fills them for datasets already loaded (one aggregate over their readings).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasets", sa.Column("reading_count", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.add_column(
        "datasets", sa.Column("missing_count", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.add_column("datasets", sa.Column("first_reading", sa.DateTime(timezone=True), nullable=True))
    op.add_column("datasets", sa.Column("last_reading", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "datasets", sa.Column("measured_kwh", sa.Float(), server_default="0", nullable=False)
    )
    op.execute(
        sa.text(
            """
            UPDATE datasets AS d SET
                reading_count = s.n,
                missing_count = s.missing,
                first_reading = s.first,
                last_reading = s.last,
                measured_kwh = s.kwh
            FROM (
                SELECT b.dataset_id,
                       count(*) AS n,
                       count(*) FILTER (WHERE r.value IS NULL) AS missing,
                       min(r.timestamp) AS first,
                       max(r.timestamp) AS last,
                       coalesce(sum(r.value) FILTER (WHERE m.unit = 'kWh'), 0) AS kwh
                FROM readings AS r
                JOIN meters AS m ON m.meter_id = r.meter_id
                JOIN buildings AS b ON b.building_id = m.building_id
                GROUP BY b.dataset_id
            ) AS s
            WHERE d.dataset_id = s.dataset_id
            """
        )
    )


def downgrade() -> None:
    for column in (
        "measured_kwh",
        "last_reading",
        "first_reading",
        "missing_count",
        "reading_count",
    ):
        op.drop_column("datasets", column)
