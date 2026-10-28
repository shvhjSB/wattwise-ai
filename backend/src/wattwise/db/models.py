"""Tables for the entities of the data contract (docs/DATA_CONTRACT.md, docs/DATABASE.md).

The columns, types and limits follow the contract, so data that validated as canonical can be
stored. Every building belongs to a `Dataset`, which says whether its data is synthetic or
observed, so nothing the API serves loses that label. Alert and analysis-run tables arrive with
the tasks that serve them (T025, T027).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wattwise.data.contracts import CANONICAL_UNIT, MeterType, Unit
from wattwise.db.base import Base

IDENTIFIER_LENGTH = 128  # the contract's identifier limit


class DataKind(StrEnum):
    """Where a dataset's readings come from (the scientific-honesty labels)."""

    SYNTHETIC = "synthetic"  # generated, e.g. wattwise.data.synthetic
    OBSERVED = "observed"  # measured by real meters, e.g. BDG2


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
