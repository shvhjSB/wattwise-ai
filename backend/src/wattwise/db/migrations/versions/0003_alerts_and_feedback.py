"""Alerts with their evidence, and reviewers' feedback (T025).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out, not imported, so this migration never changes when the code does.
LABELS = "'confirmed_waste', 'expected_behaviour', 'needs_investigation', 'sensor_or_data_fault'"
STATUSES = (
    "'confirmed_waste', 'expected_behaviour', 'needs_investigation', 'sensor_or_data_fault', "
    "'unreviewed'"
)


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("meter_id", sa.String(128), nullable=False),
        sa.Column("detector", sa.String(32), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("flagged_hours", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("signature", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("peak_score", sa.Float(), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("potential_excess_kwh", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(32), server_default="unreviewed", nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("alert_id", name="pk_alerts"),
        sa.ForeignKeyConstraint(
            ["meter_id"], ["meters.meter_id"], name="fk_alerts_meter_id_meters", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "meter_id", "detector", "start", name="uq_alerts_meter_id_detector_start"
        ),
        sa.CheckConstraint('"end" > start', name="ck_alerts_end_after_start"),
        sa.CheckConstraint("direction IN ('high', 'low')", name="ck_alerts_direction"),
        sa.CheckConstraint(
            "kind IN ('above_expected', 'below_expected', 'meter_problem')", name="ck_alerts_kind"
        ),
        sa.CheckConstraint("severity IN ('high', 'low', 'medium')", name="ck_alerts_severity"),
        sa.CheckConstraint("priority_score BETWEEN 0 AND 100", name="ck_alerts_priority_range"),
        sa.CheckConstraint(f"review_status IN ({STATUSES})", name="ck_alerts_review_status"),
    )
    for column in ("meter_id", "start", "signature", "priority_score", "severity", "review_status"):
        op.create_index(f"ix_alerts_{column}", "alerts", [column])
    op.create_table(
        "alert_feedback",
        sa.Column("feedback_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("feedback_id", name="pk_alert_feedback"),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.alert_id"],
            name="fk_alert_feedback_alert_id_alerts",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"label IN ({LABELS})", name="ck_alert_feedback_label"),
        sa.CheckConstraint("char_length(note) <= 2000", name="ck_alert_feedback_note_length"),
        sa.CheckConstraint(
            "char_length(reviewer) <= 100", name="ck_alert_feedback_reviewer_length"
        ),
    )
    op.create_index("ix_alert_feedback_alert_id", "alert_feedback", ["alert_id"])


def downgrade() -> None:
    op.drop_table("alert_feedback")
    op.drop_table("alerts")
