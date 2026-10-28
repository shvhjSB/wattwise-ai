"""The dashboard summary."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.catalog import DashboardSummary, DatasetSummary
from wattwise.db.models import Building, Dataset, Meter, Reading

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", summary="Totals of the stored data")
def dashboard_summary(session: Annotated[Session, Depends(get_session)]) -> DashboardSummary:
    """Counts per dataset and overall, with each dataset's kind (synthetic or observed).

    It reports only what is stored: no alerts, savings or costs."""
    buildings = (
        select(Building.dataset_id, func.count().label("n"))
        .group_by(Building.dataset_id)
        .subquery()
    )
    meters = (
        select(Building.dataset_id, func.count().label("n"))
        .select_from(Meter)
        .join(Building)
        .group_by(Building.dataset_id)
        .subquery()
    )
    readings = (
        select(
            Building.dataset_id,
            func.count().label("n"),
            func.count().filter(Reading.value.is_(None)).label("missing"),
            func.min(Reading.timestamp).label("first"),
            func.max(Reading.timestamp).label("last"),
        )
        .select_from(Reading)
        .join(Meter)
        .join(Building)
        .group_by(Building.dataset_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Dataset.dataset_id,
            Dataset.name,
            Dataset.kind,
            func.coalesce(buildings.c.n, 0),
            func.coalesce(meters.c.n, 0),
            func.coalesce(readings.c.n, 0),
            func.coalesce(readings.c.missing, 0),
            readings.c.first,
            readings.c.last,
        )
        .outerjoin(buildings, buildings.c.dataset_id == Dataset.dataset_id)
        .outerjoin(meters, meters.c.dataset_id == Dataset.dataset_id)
        .outerjoin(readings, readings.c.dataset_id == Dataset.dataset_id)
        .order_by(Dataset.dataset_id)
    ).all()
    datasets = [
        DatasetSummary.model_validate(
            {
                "dataset_id": r[0],
                "name": r[1],
                "kind": r[2],
                "buildings": r[3],
                "meters": r[4],
                "readings": r[5],
                "missing_values": r[6],
                "first_reading": r[7],
                "last_reading": r[8],
            }
        )
        for r in rows
    ]
    by_type: dict[str, int] = {
        meter_type: int(n)
        for meter_type, n in session.execute(
            select(Meter.meter_type, func.count())
            .group_by(Meter.meter_type)
            .order_by(Meter.meter_type)
        ).all()
    }
    firsts = [d.first_reading for d in datasets if d.first_reading is not None]
    lasts = [d.last_reading for d in datasets if d.last_reading is not None]
    return DashboardSummary.model_validate(
        {
            "datasets": datasets,
            "data_kinds": sorted({d.kind for d in datasets}),
            "buildings": sum(d.buildings for d in datasets),
            "meters": sum(d.meters for d in datasets),
            "meters_by_type": by_type,
            "readings": sum(d.readings for d in datasets),
            "missing_values": sum(d.missing_values for d in datasets),
            "first_reading": min(firsts, default=None),
            "last_reading": max(lasts, default=None),
        }
    )
