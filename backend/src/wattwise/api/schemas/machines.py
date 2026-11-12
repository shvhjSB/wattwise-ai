"""The machine comparison of one building (T066, D077)."""

from pydantic import BaseModel, Field

from wattwise.api.schemas.catalog import DataKindName, UtcDatetime


class MeterComparisonOut(BaseModel):
    meter_id: str
    energy_kwh: float
    hours_with_reading: int
    running_threshold_kwh: float
    running_hours: int
    closed_kwh: float
    closed_share: float | None = Field(description="Of this meter's own energy.")
    peak_kwh: float = Field(description="The highest hourly use.")
    events: int = Field(description="Found now by the default detector; not stored alerts.")
    negative_hours: int = Field(description="Hours recorded below zero, included as recorded.")
    negative_kwh: float


class MainMeterOut(MeterComparisonOut):
    chosen: bool = Field(description="True if the request named it; otherwise the largest.")


class MachineOut(MeterComparisonOut):
    share_of_main: float | None


class MachineComparison(BaseModel):
    """Each meter of a building against its main meter, from stored readings. Computed on
    request; nothing is stored, and no model is involved."""

    available: bool
    message: str | None
    building_id: str
    dataset_id: str
    dataset_name: str
    data_kind: DataKindName
    timezone: str
    first_reading: UtcDatetime | None
    last_reading: UtcDatetime | None
    open_days: list[int] = Field(description="0 is Monday.")
    open_from: int
    open_to: int = Field(description="Exclusive, in local hours.")
    main: MainMeterOut | None
    machines: list[MachineOut]
    unmetered_kwh: float | None
    unmetered_share: float | None
    not_compared: list[str] = Field(description="Meters that are not electricity in kWh.")
    definitions: dict[str, str]
    caveats: list[str]
