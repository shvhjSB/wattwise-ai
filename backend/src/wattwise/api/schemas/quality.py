"""Schemas for a dataset's stored data-quality audit (T047)."""

from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from wattwise.api.schemas.catalog import DataKindName, Page, UtcDatetime
from wattwise.data.quality import QualityCheck

#: What each check finds, from docs/DATA_QUALITY.md. Findings describe the data, not the building.
CHECK_DEFINITIONS: Final = {
    QualityCheck.GAPS: "Intervals with no row between a meter's first and last reading.",
    QualityCheck.IRREGULAR_INTERVAL: "Steps between readings that are not a multiple of the "
    "meter's interval (shifted or mixed timestamps).",
    QualityCheck.MISSING_VALUES: "Rows whose value is empty.",
    QualityCheck.LOW_COVERAGE: "Available values fall below the coverage threshold of the "
    "expected intervals.",
    QualityCheck.NEGATIVE_VALUES: "Negative readings on a meter type that cannot measure them "
    "(solar is exempt).",
    QualityCheck.ZERO_RUNS: "Long runs of consecutive zero readings (an outage, a disconnected "
    "meter, a logger fault, or a real shutdown).",
    QualityCheck.FLATLINES: "Long runs of identical non-zero readings (a stuck meter or logger "
    "fault).",
    QualityCheck.EXTREME_VALUES: "Readings far above the meter's own 99th percentile (out of "
    "range: for example a Wh/kWh slip or a counter reset).",
    QualityCheck.IMPLAUSIBLE_INTENSITY: "Annual energy per m² of floor area outside a plausible "
    "range (out of range: a unit or scaling error, a wrong floor area, or a shared meter).",
}
DUPLICATES_NOTE: Final = (
    "Duplicate timestamps (two rows for one meter and hour) are rejected by the data contract "
    "(duplicate_key) before any dataset is stored, so stored datasets contain none."
)
RECENT_UPLOADS_NOTE: Final = (
    "Uploaded files are validated and analysed but not stored; each analysis leaves a "
    "monitoring record, listed under recent uploads."
)


class CheckOut(BaseModel):
    check: QualityCheck
    definition: str
    meters: int = Field(description="Meters with at least one finding of this check.")


class FindingOut(BaseModel):
    check: QualityCheck
    severity: Literal["info", "warning"]
    message: str
    count: int
    start: str | None = Field(None, description="First affected timestamp of an example (UTC).")
    end: str | None = Field(None, description="Last affected timestamp of an example (UTC).")


class MeterQualityOut(BaseModel):
    meter_id: str
    building_id: str
    meter_type: str
    unit: str
    interval_minutes: int | None
    first: str
    last: str
    expected_intervals: int
    present_rows: int
    absent_intervals: int
    missing_values: int
    available_values: int
    coverage_pct: float
    negative_values: int
    zero_values: int
    warnings: int = Field(description="Findings of warning severity.")
    findings: list[FindingOut]


class QualityNotAssessed(BaseModel):
    available: Literal[False] = False
    dataset_id: str
    name: str
    data_kind: DataKindName
    message: str


class DatasetQualityOut(BaseModel):
    available: Literal[True] = True
    dataset_id: str
    name: str
    data_kind: DataKindName
    assessed_at: UtcDatetime
    quality_version: str
    contract_version: str
    thresholds: dict[str, Any] = Field(description="The thresholds the audit used.")
    summary: dict[str, Any] = Field(
        description="Meters, rows, period, expected intervals, available values, coverage and "
        "meters with warnings."
    )
    checks: list[CheckOut]
    duplicates_note: str = DUPLICATES_NOTE
    uploads_note: str = RECENT_UPLOADS_NOTE
    meters: Page[MeterQualityOut]
