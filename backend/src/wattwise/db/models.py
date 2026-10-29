"""Tables for the entities of the data contract (docs/DATA_CONTRACT.md, docs/DATABASE.md).

The columns, types and limits follow the contract, so data that validated as canonical can be
stored. Every building belongs to a `Dataset`, which says whether its data is synthetic or
observed, so nothing the API serves loses that label. Alerts (T025) carry their full evidence
bundle and an append-only history of reviewers' feedback; the analysis-run table arrives with
T027.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wattwise.data.contracts import CANONICAL_UNIT, MeterType, Unit
from wattwise.db.base import Base

IDENTIFIER_LENGTH = 128  # the contract's identifier limit
NOTE_LENGTH = 2000
REVIEWER_LENGTH = 100


class DataKind(StrEnum):
    """Where a dataset's readings come from (the scientific-honesty labels)."""

    SYNTHETIC = "synthetic"  # generated, e.g. wattwise.data.synthetic
    OBSERVED = "observed"  # measured by real meters, e.g. BDG2


class FeedbackLabel(StrEnum):
    """A reviewer's verdict on an alert (D047). It is the reviewer's judgement, recorded as given;
    the system never sets it and never treats it as a measurement."""

    CONFIRMED_WASTE = "confirmed_waste"  # real excess consumption, worth acting on
    EXPECTED_BEHAVIOUR = "expected_behaviour"  # a known, legitimate reason (an event, a schedule)
    SENSOR_OR_DATA_FAULT = "sensor_or_data_fault"  # the meter or its data, not the building
    NEEDS_INVESTIGATION = "needs_investigation"  # not decided yet


#: `alerts.review_status`: the latest feedback label, or this when there is none.
UNREVIEWED = "unreviewed"
SEVERITIES = ("high", "medium", "low")
ALERT_KINDS = ("above_expected", "below_expected", "meter_problem")


def _quoted(values: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in sorted(values))


def _types_in(unit: Unit) -> str:
    return _quoted([t.value for t in MeterType if CANONICAL_UNIT[t] is unit])


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_quoted([k.value for k in DataKind])})", name="kind"),
    )

    dataset_id: Mapped[str] = mapped_column(String(IDENTIFIER_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    #: Where the data came from (a path, a URL or a generator and seed), for provenance.
    source: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buildings: Mapped[list[Building]] = relationship(back_populates="dataset")


class Building(Base):
    __tablename__ = "buildings"
    __table_args__ = (
        CheckConstraint("floor_area_m2 > 0", name="floor_area_positive"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    building_id: Mapped[str] = mapped_column(String(IDENTIFIER_LENGTH), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[str] = mapped_column(String(IDENTIFIER_LENGTH), index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    primary_use: Mapped[str | None] = mapped_column(Text)
    floor_area_m2: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[Dataset] = relationship(back_populates="buildings")
    meters: Mapped[list[Meter]] = relationship(back_populates="building")


class Meter(Base):
    __tablename__ = "meters"
    __table_args__ = (
        CheckConstraint(
            f"meter_type IN ({_quoted([t.value for t in MeterType])})", name="meter_type"
        ),
        CheckConstraint(f"unit IN ({_quoted([u.value for u in Unit])})", name="unit"),
        # One canonical unit per meter type (the contract's rule).
        CheckConstraint(
            f"(meter_type IN ({_types_in(Unit.KWH)}) AND unit = 'kWh') "
            f"OR (meter_type IN ({_types_in(Unit.CUBIC_METRE)}) AND unit = 'm3')",
            name="canonical_unit",
        ),
    )

    meter_id: Mapped[str] = mapped_column(String(IDENTIFIER_LENGTH), primary_key=True)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id", ondelete="RESTRICT"), index=True
    )
    meter_type: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    building: Mapped[Building] = relationship(back_populates="meters")


class Reading(Base):
    """One meter's consumption over the interval starting at `timestamp` (UTC). A missing
    `value` means "not measured" and is stored as NULL, never as 0 (the contract)."""

    __tablename__ = "readings"

    meter_id: Mapped[str] = mapped_column(
        ForeignKey("meters.meter_id", ondelete="RESTRICT"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float | None] = mapped_column(Float)


class Alert(Base):
    """One detected event, its priority (T022) and its evidence bundle (T020) as loaded."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("meter_id", "detector", "start"),
        CheckConstraint('"end" > start', name="end_after_start"),
        CheckConstraint("direction IN ('high', 'low')", name="direction"),
        CheckConstraint(f"kind IN ({_quoted(list(ALERT_KINDS))})", name="kind"),
        CheckConstraint(f"severity IN ({_quoted(list(SEVERITIES))})", name="severity"),
        CheckConstraint("priority_score BETWEEN 0 AND 100", name="priority_range"),
        CheckConstraint(
            f"review_status IN ({_quoted([UNREVIEWED, *(f.value for f in FeedbackLabel)])})",
            name="review_status",
        ),
    )

    alert_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    meter_id: Mapped[str] = mapped_column(
        ForeignKey("meters.meter_id", ondelete="RESTRICT"), index=True
    )
    detector: Mapped[str] = mapped_column(String(32))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_hours: Mapped[int] = mapped_column(Integer)
    flagged_hours: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(8))
    signature: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    peak_score: Mapped[float | None] = mapped_column(Float)
    priority_score: Mapped[float] = mapped_column(Float, index=True)
    severity: Mapped[str] = mapped_column(String(8), index=True)
    #: Potential, never verified (D038); NULL for meter problems (D040).
    potential_excess_kwh: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    review_status: Mapped[str] = mapped_column(String(32), server_default=UNREVIEWED, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A later load no longer detected it, but it has feedback, so it is kept (D047).
    superseded: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    feedback: Mapped[list[AlertFeedback]] = relationship(
        back_populates="alert", order_by="AlertFeedback.feedback_id"
    )


class AlertFeedback(Base):
    """One review of an alert. Append-only: a new verdict is a new row, so history is kept."""

    __tablename__ = "alert_feedback"
    __table_args__ = (
        CheckConstraint(f"label IN ({_quoted([f.value for f in FeedbackLabel])})", name="label"),
        CheckConstraint(f"char_length(note) <= {NOTE_LENGTH}", name="note_length"),
        CheckConstraint(f"char_length(reviewer) <= {REVIEWER_LENGTH}", name="reviewer_length"),
    )

    feedback_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="RESTRICT"), index=True
    )
    label: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(REVIEWER_LENGTH))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    alert: Mapped[Alert] = relationship(back_populates="feedback")


class AnalysisRun(Base):
    """A monitoring record of one `/inference/analyze` call (T027). Metadata only: the uploaded
    readings themselves are never stored (D048)."""

    __tablename__ = "analysis_runs"
    __table_args__ = (CheckConstraint("input_end >= input_start", name="input_range"),)

    run_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    #: The model that produced the expectation; NULL when no model was available.
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    detector: Mapped[str] = mapped_column(String(32))
    input_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meters: Mapped[int] = mapped_column(Integer)
    readings: Mapped[int] = mapped_column(Integer)
    missing_values: Mapped[int] = mapped_column(Integer)
    predictions: Mapped[int] = mapped_column(Integer)
    alerts: Mapped[int] = mapped_column(Integer)
