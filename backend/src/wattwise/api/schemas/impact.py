"""Schemas for potential energy, cost and carbon impact scenarios."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wattwise.api.schemas.catalog import DataKindName

_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


class TariffScenario(BaseModel):
    """An explicit what-if tariff. It is not persisted or inferred."""

    model_config = ConfigDict(extra="forbid")

    geography: str
    currency: str
    rate_per_kwh: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, value: str) -> str:
        if not _CURRENCY.fullmatch(value):
            raise ValueError("currency must be a three-letter code")
        return value.upper()


class MoneyEstimate(BaseModel):
    value: float
    currency: str
    events: int


class CarbonFactorOut(BaseModel):
    geography: str
    geography_name: str
    requested_year: int
    vintage_year: int
    kg_co2e_per_kwh: float
    scope: str
    source_name: str
    source_url: str
    retrieved: str
    licence: str


class PriceReferenceOut(BaseModel):
    geography: str
    geography_name: str
    year: int
    period: str
    sector: str
    band: str | None
    tax_basis: str
    rate_per_kwh: float
    currency: str
    source_name: str
    source_url: str
    retrieved: str
    licence: str


class GeographyImpact(BaseModel):
    carbon_geography: str | None
    tariff_geography: str | None
    sites: list[str]
    years: list[int]
    events: int
    potential_excess_kwh: float
    potential_carbon_kg: float | None = Field(
        description="null when no event in this group has a sourced carbon factor."
    )
    carbon_configured_events: int
    carbon_unconfigured_events: int
    cost: MoneyEstimate | None
    carbon_factors: list[CarbonFactorOut]
    price_references: list[PriceReferenceOut]


class KindImpact(BaseModel):
    kind: DataKindName
    events: int
    events_counted: int
    meter_problem_events: int
    total_potential_excess_kwh: float
    total_potential_carbon_kg: float | None
    carbon_configured_events: int
    carbon_unconfigured_events: int
    total_cost: MoneyEstimate | None
    by_geography: list[GeographyImpact]


class ImpactSummary(BaseModel):
    """Potential impact from stored, non-superseded alerts; kinds are never combined."""

    status: Literal["potential"] = "potential"
    tariff: TariffScenario | None
    by_kind: list[KindImpact]
    caveats: list[str]
