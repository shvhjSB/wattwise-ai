"""Potential excess energy, cost and carbon scenarios over stored alerts."""

from dataclasses import asdict, dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.impact import ImpactSummary, TariffScenario
from wattwise.data.reference import (
    CarbonFactor,
    carbon_factor,
    geography_for_site,
    load_carbon_factors,
    load_prices,
    price_geography_for_site,
    prices,
)
from wattwise.db.models import Alert, Building, Dataset, Meter

router = APIRouter(tags=["impact"])
SessionDep = Annotated[Session, Depends(get_session)]

KIND_ORDER = ("observed", "synthetic")
CAVEATS = (
    "Every figure is potential, not verified savings or avoided emissions.",
    "Potential excess counts only energy above the model interval's upper bound.",
    "Meter and data problems are excluded from energy, cost and carbon totals.",
    "Carbon uses each event site's sourced factor for its year; missing factors stay "
    "not configured.",
    "A tariff scenario applies only to its named geography and is not saved.",
)


@dataclass
class _Group:
    sites: set[str] = field(default_factory=set)
    years: set[int] = field(default_factory=set)
    events: int = 0
    excess: float = 0.0
    carbon: float = 0.0
    carbon_configured: int = 0
    carbon_unconfigured: int = 0
    cost: float = 0.0
    priced_events: int = 0
    factors: dict[int, CarbonFactor] = field(default_factory=dict)


@dataclass
class _Kind:
    events: int = 0
    meter_problems: int = 0
    groups: dict[tuple[str | None, str | None], _Group] = field(default_factory=dict)


def _tariff(
    geography: str | None, currency: str | None, rate_per_kwh: float | None
) -> TariffScenario | None:
    if geography is None or currency is None or rate_per_kwh is None:
        if geography is not None or currency is not None or rate_per_kwh is not None:
            raise HTTPException(
                status_code=422,
                detail="tariff_geography, currency and rate_per_kwh must be supplied together",
            )
        return None
    return TariffScenario(geography=geography, currency=currency, rate_per_kwh=rate_per_kwh)


def _reference_rate(value: float, unit: str) -> float:
    if unit in ("cents_per_kwh", "pence_per_kwh"):
        return value / 100
    if unit == "eur_per_kwh":
        return value
    raise ValueError(f"unsupported committed price unit: {unit}")


def _factor_out(factor: CarbonFactor) -> dict[str, Any]:
    result = asdict(factor)
    result.pop("file_sha256")
    return result


@router.get("/impact/summary", summary="Potential energy, cost and carbon impact")
def impact_summary(
    session: SessionDep,
    tariff_geography: Annotated[str | None, Query(max_length=32)] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    rate_per_kwh: Annotated[float | None, Query(gt=0, allow_inf_nan=False)] = None,
) -> ImpactSummary:
    """Summarise stored alerts without combining observed and synthetic data.

    Carbon is resolved from the committed reference table by each event's site and year. Cost is
    a read-only scenario only when all three tariff parameters are explicit; it is never inferred
    from a reference price and never persisted.
    """
    tariff = _tariff(tariff_geography, currency, rate_per_kwh)
    rows = session.execute(
        select(
            Alert.kind,
            Alert.potential_excess_kwh,
            Alert.start,
            Building.site_id,
            Dataset.kind,
        )
        .join(Meter, Alert.meter_id == Meter.meter_id)
        .join(Building, Meter.building_id == Building.building_id)
        .join(Dataset, Building.dataset_id == Dataset.dataset_id)
        .where(Alert.superseded.is_(False))
        .order_by(Dataset.kind, Alert.alert_id)
    ).all()
    carbon_table = load_carbon_factors()
    price_table = load_prices()
    factors: dict[tuple[str | None, int], CarbonFactor | None] = {}
    kinds: dict[str, _Kind] = {}
    for alert_kind, potential_excess, start, site_id, data_kind in rows:
        kind = kinds.setdefault(data_kind, _Kind())
        kind.events += 1
        if alert_kind == "meter_problem":
            kind.meter_problems += 1
            continue
        carbon_geography = geography_for_site(site_id)
        tariff_geography_for_event = price_geography_for_site(site_id)
        group = kind.groups.setdefault((carbon_geography, tariff_geography_for_event), _Group())
        year = start.year
        excess = float(potential_excess or 0.0)
        group.sites.add(site_id)
        group.years.add(year)
        group.events += 1
        group.excess += excess
        factor_key = (carbon_geography, year)
        if factor_key not in factors:
            factors[factor_key] = carbon_factor(carbon_geography, year, carbon_table)
        factor = factors[factor_key]
        if factor is None:
            group.carbon_unconfigured += 1
        else:
            group.carbon += excess * factor.kg_co2e_per_kwh
            group.carbon_configured += 1
            group.factors[year] = factor
        if tariff is not None and tariff.geography == tariff_geography_for_event:
            group.cost += excess * tariff.rate_per_kwh
            group.priced_events += 1

    by_kind = []
    for data_kind in KIND_ORDER:
        aggregate = kinds.get(data_kind)
        if aggregate is None:
            continue
        groups = []
        for (carbon_geography, price_geography), group in sorted(
            aggregate.groups.items(), key=lambda item: (item[0][1] or "~", item[0][0] or "~")
        ):
            references = []
            for year in sorted(group.years):
                for reference in prices(price_geography, year, price_table):
                    references.append(
                        {
                            "geography": reference.geography,
                            "geography_name": reference.geography_name,
                            "year": reference.year,
                            "period": reference.period,
                            "sector": reference.sector,
                            "band": reference.band,
                            "tax_basis": reference.tax_basis,
                            "rate_per_kwh": _reference_rate(reference.value, reference.unit),
                            "currency": reference.currency,
                            "source_name": reference.source_name,
                            "source_url": reference.source_url,
                            "retrieved": reference.retrieved,
                            "licence": reference.licence,
                        }
                    )
            groups.append(
                {
                    "carbon_geography": carbon_geography,
                    "tariff_geography": price_geography,
                    "sites": sorted(group.sites),
                    "years": sorted(group.years),
                    "events": group.events,
                    "potential_excess_kwh": round(group.excess, 4),
                    "potential_carbon_kg": (
                        round(group.carbon, 4) if group.carbon_configured else None
                    ),
                    "carbon_configured_events": group.carbon_configured,
                    "carbon_unconfigured_events": group.carbon_unconfigured,
                    "cost": (
                        {
                            "value": round(group.cost, 4),
                            "currency": tariff.currency,
                            "events": group.priced_events,
                        }
                        if tariff is not None and group.priced_events
                        else None
                    ),
                    "carbon_factors": [
                        _factor_out(group.factors[year]) for year in sorted(group.factors)
                    ],
                    "price_references": references,
                }
            )
        configured = sum(group.carbon_configured for group in aggregate.groups.values())
        unconfigured = sum(group.carbon_unconfigured for group in aggregate.groups.values())
        priced = sum(group.priced_events for group in aggregate.groups.values())
        by_kind.append(
            {
                "kind": data_kind,
                "events": aggregate.events,
                "events_counted": sum(group.events for group in aggregate.groups.values()),
                "meter_problem_events": aggregate.meter_problems,
                "total_potential_excess_kwh": round(
                    sum(group.excess for group in aggregate.groups.values()), 4
                ),
                "total_potential_carbon_kg": (
                    round(sum(group.carbon for group in aggregate.groups.values()), 4)
                    if configured
                    else None
                ),
                "carbon_configured_events": configured,
                "carbon_unconfigured_events": unconfigured,
                "total_cost": (
                    {
                        "value": round(sum(group.cost for group in aggregate.groups.values()), 4),
                        "currency": tariff.currency,
                        "events": priced,
                    }
                    if tariff is not None and priced
                    else None
                ),
                "by_geography": groups,
            }
        )
    return ImpactSummary.model_validate(
        {"tariff": tariff, "by_kind": by_kind, "caveats": list(CAVEATS)}
    )
