"""Buildings, meters and meter series."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.catalog import (
    BuildingOut,
    ExpectationSeries,
    MeterOut,
    Page,
    SeriesPoint,
    SeriesResponse,
)
from wattwise.data.contracts import MeterType
from wattwise.db.models import Building, Dataset, Expectation, ExpectationSet, Meter, Reading

router = APIRouter(tags=["catalog"])

DEFAULT_PAGE = 50
MAX_PAGE = 200
DEFAULT_POINTS = 10_000
MAX_POINTS = 50_000

SessionDep = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE, description="Items per page.")]
Offset = Annotated[int, Query(ge=0, description="Items to skip.")]


LIKE_ESCAPE = "\\"  # one backslash


def _contains(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with the wildcards in `text` taken literally."""
    for special in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(special, LIKE_ESCAPE + special)
    return f"%{text}%"


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
    q: Annotated[
        str | None,
        Query(max_length=100, description="Buildings whose id or primary use contains this text."),
    ] = None,
) -> Page[BuildingOut]:
    query = _buildings()
    if q:
        needle = _contains(q)
        query = query.where(
            Building.building_id.ilike(needle, escape=LIKE_ESCAPE)
            | Building.primary_use.ilike(needle, escape=LIKE_ESCAPE)
        )
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


EXPECTATION_CAVEATS = [
    "The expectation is the model's estimate under the observed conditions, not a target.",
    "The interval is a 90% interval whose coverage was measured on the test window; a reading "
    "outside it is a reason to look, not confirmed waste.",
    "Expectations exist only for the model's validation and test windows, where it was not "
    "trained on the readings.",
]


@router.get(
    "/meters/{meter_id}/expectation",
    summary="A meter's readings against the model's expectation and interval",
    responses={404: {"description": "No such meter."}, 422: {"description": "Invalid range."}},
)
def get_expectation(
    meter_id: str,
    session: SessionDep,
    start: Annotated[
        AwareDatetime | None, Query(description="Inclusive; ISO 8601 with an offset.")
    ] = None,
    end: Annotated[
        AwareDatetime | None, Query(description="Exclusive; ISO 8601 with an offset.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_POINTS, description="Most points.")] = DEFAULT_POINTS,
) -> ExpectationSeries:
    """Readings with the expectation and interval where the model has them. A meter or range
    without an expectation answers `available: false` with the reason, never invented values."""
    if start is not None and end is not None and start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")
    meter = get_meter(meter_id, session)
    base = {
        "meter_id": meter_id,
        "unit": meter.unit,
        "data_kind": meter.data_kind,
        "caveats": EXPECTATION_CAVEATS,
        "points": [],
        "truncated": False,
        "meta": None,
    }
    stored = session.get(ExpectationSet, meter.dataset_id)
    if stored is None:
        return ExpectationSeries.model_validate(
            {
                **base,
                "available": False,
                "reason": "no_expectation_stored",
                "message": "No model expectation is stored for this dataset.",
            }
        )
    first_interval = session.scalar(
        select(func.min(Expectation.timestamp)).where(
            Expectation.meter_id == meter_id, Expectation.lower.is_not(None)
        )
    )
    meta = {
        "model_version": stored.model_version,
        "interval_nominal": stored.interval_nominal,
        "measured_coverage": stored.measured_coverage,
        "window_start": stored.window_start,
        "window_end": stored.window_end,
        "detection_start": stored.detection_start,
        "first_interval": first_interval,
    }
    low = max(start, stored.window_start) if start is not None else stored.window_start
    high = min(end, stored.window_end) if end is not None else stored.window_end
    if low >= high:
        return ExpectationSeries.model_validate(
            {
                **base,
                "meta": meta,
                "available": False,
                "reason": "outside_evaluation_window",
                "message": "The model's expectation exists only between "
                f"{stored.window_start:%Y-%m-%d} and {stored.window_end:%Y-%m-%d} (UTC).",
            }
        )
    rows = session.execute(
        select(
            Reading.timestamp,
            Reading.value,
            Expectation.expected,
            Expectation.lower,
            Expectation.upper,
        )
        .outerjoin(
            Expectation,
            (Expectation.meter_id == Reading.meter_id)
            & (Expectation.timestamp == Reading.timestamp),
        )
        .where(Reading.meter_id == meter_id, Reading.timestamp >= low, Reading.timestamp < high)
        .order_by(Reading.timestamp)
        .limit(limit + 1)
    ).all()
    return ExpectationSeries.model_validate(
        {
            **base,
            "meta": meta,
            "available": True,
            "reason": None,
            "message": None,
            "points": [
                {"timestamp": t, "observed": v, "expected": e, "lower": lo, "upper": up}
                for t, v, e, lo, up in rows[:limit]
            ],
            "truncated": len(rows) > limit,
        }
    )
