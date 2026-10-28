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


class DashboardSummary(BaseModel):
    """Totals of what is stored. No alerts, savings or costs: those come with later tasks."""

    datasets: list[DatasetSummary]
    data_kinds: list[DataKindName] = Field(description="The kinds of data present.")
    buildings: int
    meters: int
    meters_by_type: dict[str, int]
    readings: int
    missing_values: int
    first_reading: UtcDatetime | None
    last_reading: UtcDatetime | None
