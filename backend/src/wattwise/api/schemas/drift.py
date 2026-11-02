"""Schemas for data drift in the model lab (T048)."""

from typing import Final, Literal

from pydantic import BaseModel, Field

from wattwise.api.schemas.catalog import DataKindName, Page, UtcDatetime

Period = Literal["week", "month"]

DRIFT_DEFINITIONS: Final = {
    "level_ratio": "A meter's mean reading in the period divided by its mean in the training "
    "period (readings before the evaluation window). 1.0 is unchanged; the period value is the "
    "median over meters.",
    "wape": "Sum of absolute errors of the model's expectation divided by the sum of readings.",
    "bias": "Mean of expected minus observed, in the readings' unit (negative: the model "
    "expected less than was used).",
    "coverage": "Share of readings inside the model's interval; compare with the nominal level.",
}
DRIFT_NOTE: Final = (
    "Drift describes change, not failure: consumption changes for many reasons (season, "
    "occupancy, equipment, metering), and a model's errors grow when its inputs move away from "
    "what it was trained on. Each figure comes from stored readings and expectations."
)


class PeriodDrift(BaseModel):
    start: UtcDatetime = Field(description="Start of the week (Monday) or month, UTC.")
    readings: int = Field(description="Readings with an expectation in the period.")
    meters: int
    median_level_ratio: float | None
    wape: float | None
    bias: float | None
    coverage: float | None = Field(description="Share inside the interval; None without one.")


class MeterDrift(BaseModel):
    meter_id: str
    readings: int
    level_ratio: float | None
    wape: float | None
    coverage: float | None


class DriftUnavailable(BaseModel):
    available: Literal[False] = False
    message: str
    datasets: list[str] = Field(description="Datasets that have stored expectations.")


class DriftOut(BaseModel):
    available: Literal[True] = True
    dataset_id: str
    data_kind: DataKindName
    datasets: list[str] = Field(description="Datasets that have stored expectations.")
    model_version: str
    interval_nominal: float
    period: Period
    reference_end: UtcDatetime = Field(
        description="The training period is the dataset's readings before this time."
    )
    window_start: UtcDatetime
    window_end: UtcDatetime
    periods: list[PeriodDrift]
    latest_period: UtcDatetime | None
    meters: Page[MeterDrift] = Field(
        description="Each meter in the latest period, largest level change first."
    )
    definitions: dict[str, str] = DRIFT_DEFINITIONS
    note: str = DRIFT_NOTE
