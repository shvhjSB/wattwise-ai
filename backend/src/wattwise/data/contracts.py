"""Canonical data contracts: the single internal representation of energy data.

Every pipeline stage (synthetic fixtures, dataset adapters, validation, models, the API) exchanges
data in these shapes. The contracts define *structure*: columns, types, units, keys and physically
impossible values. Data *quality* (gaps, negative consumption, flatlines, outliers) is assessed
separately (roadmap T008). The human-readable specification is docs/DATA_CONTRACT.md; a test keeps
it in sync with this module.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CONTRACT_VERSION: Final = "1.0"

#: Identifiers: 1-128 characters, starting with a letter or digit, then letters, digits, `_ . : -`.
IDENTIFIER_PATTERN: Final = r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}"

#: Canonical pandas dtypes. pandas 3 parses timestamps at microsecond resolution.
TIMESTAMP_DTYPE: Final = "datetime64[us, UTC]"
TEXT_DTYPE: Final = "str"
NUMBER_DTYPE: Final = "float64"


class MeterType(StrEnum):
    """Kinds of meter. Names follow the Building Data Genome Project 2 meter files."""

    ELECTRICITY = "electricity"
    CHILLED_WATER = "chilledwater"
    STEAM = "steam"
    HOT_WATER = "hotwater"
    GAS = "gas"
    WATER = "water"
    IRRIGATION = "irrigation"
    SOLAR = "solar"


class Unit(StrEnum):
    """Units allowed in canonical readings."""

    KWH = "kWh"
    CUBIC_METRE = "m3"


#: Each meter type has exactly one canonical unit. Adapters convert source units (for example
#: kBTU to kWh) before data enters the canonical tables; validation never converts silently.
CANONICAL_UNIT: Mapping[MeterType, Unit] = {
    MeterType.ELECTRICITY: Unit.KWH,
    MeterType.CHILLED_WATER: Unit.KWH,
    MeterType.STEAM: Unit.KWH,
    MeterType.HOT_WATER: Unit.KWH,
    MeterType.GAS: Unit.KWH,
    MeterType.SOLAR: Unit.KWH,
    MeterType.WATER: Unit.CUBIC_METRE,
    MeterType.IRRIGATION: Unit.CUBIC_METRE,
}

#: Meter types that forecasting and anomaly detection support in this version. Other types are
#: valid data but are labelled as unsupported rather than silently mixed into electricity models.
ANALYSIS_SUPPORTED: frozenset[MeterType] = frozenset({MeterType.ELECTRICITY})


class ColumnKind(StrEnum):
    IDENTIFIER = "identifier"
    TIMESTAMP = "timestamp"
    CATEGORY = "category"
    NUMBER = "number"
    TEXT = "text"
    TIMEZONE = "timezone"


@dataclass(frozen=True)
class Column:
    """One column of a table contract.

    `required` means the column must be present. `nullable` means individual values may be
    missing. Bounds describe physically impossible values only; plausibility is a quality concern.
    """

    name: str
    kind: ColumnKind
    description: str
    required: bool = True
    nullable: bool = False
    unit: str | None = None
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False


@dataclass(frozen=True)
class TableContract:
    name: str
    description: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    version: str = CONTRACT_VERSION

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"{self.name} has no column {name!r}")


READINGS = TableContract(
    name="readings",
    description="Metered consumption: one row per meter per interval.",
    columns=(
        Column(
            "timestamp",
            ColumnKind.TIMESTAMP,
            "Start of the measurement interval, in UTC.",
        ),
        Column("meter_id", ColumnKind.IDENTIFIER, "Meter identifier, unique across buildings."),
        Column("building_id", ColumnKind.IDENTIFIER, "Building the meter belongs to."),
        Column(
            "meter_type",
            ColumnKind.CATEGORY,
            "Kind of meter.",
            choices=tuple(m.value for m in MeterType),
        ),
        Column(
            "unit",
            ColumnKind.CATEGORY,
            "Unit of `value`; must be the canonical unit of the meter type.",
            choices=tuple(u.value for u in Unit),
        ),
        Column(
            "value",
            ColumnKind.NUMBER,
            "Quantity consumed during the interval. Missing means not measured.",
            nullable=True,
            unit="see `unit`",
        ),
    ),
    primary_key=("meter_id", "timestamp"),
)

BUILDINGS = TableContract(
    name="buildings",
    description="Building metadata: one row per building.",
    columns=(
        Column("building_id", ColumnKind.IDENTIFIER, "Building identifier."),
        Column("site_id", ColumnKind.IDENTIFIER, "Site (campus) the building belongs to."),
        Column(
            "timezone",
            ColumnKind.TIMEZONE,
            "IANA time zone of the building, for local calendar features.",
        ),
        Column(
            "primary_use",
            ColumnKind.TEXT,
            "Primary space usage as given by the source.",
            required=False,
            nullable=True,
        ),
        Column(
            "floor_area_m2",
            ColumnKind.NUMBER,
            "Gross floor area.",
            required=False,
            nullable=True,
            unit="m2",
            minimum=0.0,
            exclusive_minimum=True,
        ),
        Column(
            "latitude",
            ColumnKind.NUMBER,
            "Latitude, WGS84.",
            required=False,
            nullable=True,
            unit="degrees",
            minimum=-90.0,
            maximum=90.0,
        ),
        Column(
            "longitude",
            ColumnKind.NUMBER,
            "Longitude, WGS84.",
            required=False,
            nullable=True,
            unit="degrees",
            minimum=-180.0,
            maximum=180.0,
        ),
    ),
    primary_key=("building_id",),
)

WEATHER = TableContract(
    name="weather",
    description="Observed site weather: one row per site per timestamp.",
    columns=(
        Column("site_id", ColumnKind.IDENTIFIER, "Site the observation applies to."),
        Column("timestamp", ColumnKind.TIMESTAMP, "Observation time, in UTC."),
        Column(
            "air_temperature_c",
            ColumnKind.NUMBER,
            "Dry-bulb air temperature.",
            nullable=True,
            unit="degC",
        ),
        Column(
            "dew_temperature_c",
            ColumnKind.NUMBER,
            "Dew-point temperature.",
            required=False,
            nullable=True,
            unit="degC",
        ),
        Column(
            "wind_speed_m_s",
            ColumnKind.NUMBER,
            "Wind speed.",
            required=False,
            nullable=True,
            unit="m/s",
            minimum=0.0,
        ),
    ),
    primary_key=("site_id", "timestamp"),
)

CONTRACTS: Mapping[str, TableContract] = {c.name: c for c in (READINGS, BUILDINGS, WEATHER)}
