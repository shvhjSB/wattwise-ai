"""Buildings, meters and meter series."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.catalog import (
    BuildingOut,
    MeterOut,
    Page,
    SeriesPoint,
    SeriesResponse,
)
from wattwise.data.contracts import MeterType
from wattwise.db.models import Building, Dataset, Meter, Reading

router = APIRouter(tags=["catalog"])

DEFAULT_PAGE = 50
MAX_PAGE = 200
DEFAULT_POINTS = 10_000
MAX_POINTS = 50_000

SessionDep = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE, description="Items per page.")]
Offset = Annotated[int, Query(ge=0, description="Items to skip.")]


def _page(session: Session, query: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = session.execute(query.limit(limit).offset(offset)).all()
    return list(rows), int(total or 0)


def _buildings() -> Select[Any]:
    meters = (
        select(func.count(Meter.meter_id))
        .where(Meter.building_id == Building.building_id)
        .scalar_subquery()
    )
    return (
        select(Building, Dataset.kind, meters.label("meter_count"))
        .join(Dataset)
        .order_by(Building.building_id)
    )


def _building_out(building: Building, kind: str, meter_count: int) -> BuildingOut:
    return BuildingOut.model_validate(
        {
            "building_id": building.building_id,
            "dataset_id": building.dataset_id,
            "data_kind": kind,
            "site_id": building.site_id,
            "timezone": building.timezone,
            "primary_use": building.primary_use,
            "floor_area_m2": building.floor_area_m2,
            "latitude": building.latitude,
            "longitude": building.longitude,
            "meter_count": meter_count,
        }
    )


def _meters() -> Select[Any]:
    return (
        select(Meter, Building.dataset_id, Dataset.kind)
        .join(Building, Meter.building_id == Building.building_id)
        .join(Dataset, Building.dataset_id == Dataset.dataset_id)
        .order_by(Meter.meter_id)
    )


def _meter_out(meter: Meter, dataset_id: str, kind: str) -> MeterOut:
    return MeterOut.model_validate(
        {
            "meter_id": meter.meter_id,
            "building_id": meter.building_id,
            "dataset_id": dataset_id,
            "data_kind": kind,
            "meter_type": meter.meter_type,
            "unit": meter.unit,
        }
    )


@router.get("/buildings", summary="List buildings")
def list_buildings(
    session: SessionDep,
    limit: Limit = DEFAULT_PAGE,
    offset: Offset = 0,
    site_id: Annotated[str | None, Query(description="Only this site's buildings.")] = None,
    dataset_id: Annotated[str | None, Query(description="Only this dataset's buildings.")] = None,
) -> Page[BuildingOut]:
    query = _buildings()
    if site_id is not None:
        query = query.where(Building.site_id == site_id)
    if dataset_id is not None:
        query = query.where(Building.dataset_id == dataset_id)
    rows, total = _page(session, query, limit, offset)
    return Page[BuildingOut](
        items=[_building_out(*row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/buildings/{building_id}",
    summary="One building",
    responses={404: {"description": "No such building."}},
)
def get_building(building_id: str, session: SessionDep) -> BuildingOut:
    row = session.execute(_buildings().where(Building.building_id == building_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"building {building_id!r} not found")
    return _building_out(*row)


@router.get("/meters", summary="List meters")
def list_meters(
    session: SessionDep,
    limit: Limit = DEFAULT_PAGE,
    offset: Offset = 0,
    building_id: Annotated[str | None, Query(description="Only this building's meters.")] = None,
    meter_type: Annotated[MeterType | None, Query(description="Only meters of this type.")] = None,
) -> Page[MeterOut]:
    query = _meters()
    if building_id is not None:
        query = query.where(Meter.building_id == building_id)
    if meter_type is not None:
        query = query.where(Meter.meter_type == meter_type.value)
    rows, total = _page(session, query, limit, offset)
    return Page[MeterOut](
        items=[_meter_out(*row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/meters/{meter_id}", summary="One meter", responses={404: {"description": "No such meter."}}
)
def get_meter(meter_id: str, session: SessionDep) -> MeterOut:
    row = session.execute(_meters().where(Meter.meter_id == meter_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"meter {meter_id!r} not found")
    return _meter_out(*row)


@router.get(
    "/meters/{meter_id}/series",
    summary="A meter's readings in a time range",
    responses={
        404: {"description": "No such meter."},
        422: {"description": "A timestamp without a time zone, or start not before end."},
    },
)
def get_series(
    meter_id: str,
    session: SessionDep,
    start: Annotated[
        AwareDatetime | None, Query(description="Inclusive; ISO 8601 with an offset.")
    ] = None,
    end: Annotated[
        AwareDatetime | None, Query(description="Exclusive; ISO 8601 with an offset.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_POINTS, description="Most points.")] = DEFAULT_POINTS,
) -> SeriesResponse:
    """Readings in time order. Missing readings are returned as null, never as zero."""
    if start is not None and end is not None and start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")
    meter = get_meter(meter_id, session)
    query = select(Reading.timestamp, Reading.value).where(Reading.meter_id == meter_id)
    if start is not None:
        query = query.where(Reading.timestamp >= start)
    if end is not None:
        query = query.where(Reading.timestamp < end)
    rows = session.execute(query.order_by(Reading.timestamp).limit(limit + 1)).all()
    return SeriesResponse.model_validate(
        {
            "meter_id": meter_id,
            "unit": meter.unit,
            "data_kind": meter.data_kind,
            "start": start,
            "end": end,
            "points": [SeriesPoint(timestamp=t, value=v) for t, v in rows[:limit]],
            "truncated": len(rows) > limit,
        }
    )
