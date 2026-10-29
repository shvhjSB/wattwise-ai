"""Schemas for buildings, meters, series and the dashboard summary."""

from datetime import UTC, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, Field

DataKindName = Literal["synthetic", "observed"]
T = TypeVar("T")
#: Every timestamp the API returns is UTC (the contract), whatever zone it was read or given in.
UtcDatetime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(UTC))]


class Page(BaseModel, Generic[T]):  # noqa: UP046  (pydantic generic models)
    """One page of a list, ordered by identifier."""

    items: list[T]
    total: int = Field(description="Matching items across all pages.")
    limit: int
    offset: int


class BuildingOut(BaseModel):
    building_id: str
    dataset_id: str
    data_kind: DataKindName = Field(description="Whether the dataset is synthetic or observed.")
    site_id: str
    timezone: str
    primary_use: str | None
    floor_area_m2: float | None
    latitude: float | None
    longitude: float | None
    meter_count: int


class MeterOut(BaseModel):
    meter_id: str
    building_id: str
    dataset_id: str
    data_kind: DataKindName
    meter_type: str
    unit: str


class SeriesPoint(BaseModel):
    timestamp: UtcDatetime = Field(description="Start of the interval, UTC.")
    value: float | None = Field(description="Consumption; null means not measured, never zero.")


class SeriesResponse(BaseModel):
    meter_id: str
    unit: str
    data_kind: DataKindName
    start: UtcDatetime | None = Field(description="The requested start (inclusive), if any.")
    end: UtcDatetime | None = Field(description="The requested end (exclusive), if any.")
    points: list[SeriesPoint]
    truncated: bool = Field(description="More points exist in the range than `limit` returned.")


class DatasetSummary(BaseModel):
    dataset_id: str
    name: str
    kind: DataKindName
    buildings: int
    meters: int
    readings: int
    missing_values: int
    first_reading: UtcDatetime | None
    last_reading: UtcDatetime | None
    measured_kwh: float = Field(description="Sum of recorded values of the dataset's kWh meters.")


class AlertTotals(BaseModel):
    """What the stored alerts add up to, for one kind of data. Alerts that a later detection no
    longer finds (superseded) are not counted."""

    alerts: int
    open: int = Field(description="Unreviewed or marked needs investigation.")
    high_severity: int = Field(description="Open alerts in the high severity band.")
    by_review_status: dict[str, int]
    by_kind: dict[str, int]
    potential_excess_kwh: float = Field(
        description="Estimate: kWh above the model's upper bound over the alerts' hours, for "
        "consumption alerts. Potential, not verified; meter problems are not counted."
    )
    observed_kwh_in_alerts: float = Field(
        description="Recorded kWh over the hours of consumption alerts that the model covers."
    )
    expected_kwh_in_alerts: float = Field(
        description="The model's expected kWh over the same hours. Only alert windows have an "
        "expectation stored; there is no portfolio-wide figure."
    )


class KindSummary(BaseModel):
    """Totals for the datasets of one kind. Synthetic and observed data are never added together."""

    kind: DataKindName
    datasets: int
    buildings: int
    meters: int
    readings: int
    missing_values: int
    missing_share: float | None = Field(description="Missing readings / readings; null if none.")
    first_reading: UtcDatetime | None
    last_reading: UtcDatetime | None
    measured_kwh: float
    alerts: AlertTotals


class DashboardSummary(BaseModel):
    """Totals of what is stored. Potential figures are estimates, never verified savings."""

    datasets: list[DatasetSummary]
    data_kinds: list[DataKindName] = Field(description="The kinds of data present.")
    by_kind: list[KindSummary] = Field(description="Observed first, then synthetic.")
    buildings: int
    meters: int
    meters_by_type: dict[str, int]
    readings: int
    missing_values: int
    first_reading: UtcDatetime | None
    last_reading: UtcDatetime | None


ExpectationUnavailable = Literal["no_expectation_stored", "outside_evaluation_window"]


class ExpectationMeta(BaseModel):
    """What produced the expectation and where it exists."""

    model_version: str
    interval_nominal: float = Field(description="Nominal coverage of the interval, e.g. 0.9.")
    measured_coverage: float | None = Field(
        description="Share of readings inside the interval in the test window; null if unmeasured."
    )
    window_start: UtcDatetime = Field(description="First hour with an expectation (inclusive).")
    window_end: UtcDatetime = Field(description="End of the window (exclusive).")
    detection_start: UtcDatetime = Field(description="Start of the test window.")
    first_interval: UtcDatetime | None = Field(
        description="This meter's first hour with an interval; earlier hours have only the "
        "expectation (the interval needs weeks of out-of-sample residuals)."
    )


class ExpectationPoint(BaseModel):
    timestamp: UtcDatetime
    observed: float | None = Field(description="null means not measured, never zero.")
    expected: float | None
    lower: float | None
    upper: float | None


class ExpectationSeries(BaseModel):
    """A meter's readings with the model's expectation and interval, for a time range."""

    meter_id: str
    unit: str
    data_kind: DataKindName
    available: bool
    reason: ExpectationUnavailable | None = Field(description="Why not, when unavailable.")
    message: str | None
    meta: ExpectationMeta | None
    points: list[ExpectationPoint]
    truncated: bool
    caveats: list[str]
