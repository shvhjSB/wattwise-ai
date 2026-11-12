"""A building's meters compared against its main meter (T066, D077)."""

from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.machines import MachineComparison
from wattwise.db.models import Building, Dataset, Meter, Reading
from wattwise.ml.machines import DEFINITIONS, OpenHours, compare

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

CAVEATS = [
    "Figures come from each meter's own readings; nothing is estimated for meters that do not "
    "exist. A main meter cannot be split into machines (T065, D076).",
    "Events are found now by the default detector on these readings: anomalies to investigate, "
    "not confirmed waste. They are not stored alerts.",
    "Closed-hours figures depend on the opening days and hours given, not on any record of when "
    "the site was actually open.",
    "Unmetered is the main meter minus the other meters. It can include loads, losses, or meters "
    "that are not behind the main meter.",
    "Readings below zero are included as recorded and counted per meter (negative_hours): check "
    "such a meter before trusting its figures.",
]


@router.get(
    "/buildings/{building_id}/machines",
    summary="Compare a building's meters against its main meter",
    responses={404: {"description": "No such building."}, 422: {"description": "Bad input."}},
)
def machine_comparison(
    building_id: str,
    session: SessionDep,
    main_meter_id: Annotated[
        str | None,
        Query(max_length=200, description="The site's main meter; default: the largest."),
    ] = None,
    open_days: Annotated[
        str,
        Query(pattern=r"^[0-6](,[0-6])*$", description="Open weekdays, 0 (Monday) to 6."),
    ] = "0,1,2,3,4",
    open_from: Annotated[int, Query(ge=0, le=23, description="Opening hour, local.")] = 6,
    open_to: Annotated[int, Query(ge=1, le=24, description="Closing hour, local.")] = 18,
) -> MachineComparison:
    """Each electricity meter of the building against its main meter: energy, share, running
    hours, use while closed, highest hour and the default detector's events. Computed from the
    stored readings on request; nothing is stored and no model is involved."""
    try:
        hours = OpenHours(frozenset(int(d) for d in open_days.split(",")), open_from, open_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    found = session.execute(
        select(Building, Dataset)
        .join(Dataset, Building.dataset_id == Dataset.dataset_id)
        .where(Building.building_id == building_id)
    ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="building not found")
    building, dataset = found
    meters = session.scalars(
        select(Meter).where(Meter.building_id == building_id).order_by(Meter.meter_id)
    ).all()
    compared = [m.meter_id for m in meters if m.meter_type == "electricity" and m.unit == "kWh"]
    base: dict[str, Any] = {
        "building_id": building.building_id,
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.name,
        "data_kind": dataset.kind,
        "timezone": building.timezone,
        "open_days": sorted(hours.days),
        "open_from": hours.start,
        "open_to": hours.end,
        "not_compared": [m.meter_id for m in meters if m.meter_id not in set(compared)],
        "definitions": DEFINITIONS,
        "caveats": CAVEATS,
    }
    if main_meter_id is not None and main_meter_id not in compared:
        raise HTTPException(
            status_code=422,
            detail="main_meter_id is not one of this building's electricity meters in kWh",
        )
    rows = session.execute(
        select(Reading.meter_id, Reading.timestamp, Reading.value).where(
            Reading.meter_id.in_(compared)
        )
    ).all()
    readings = pd.DataFrame(rows, columns=["meter_id", "timestamp", "value"])
    readings["timestamp"] = pd.to_datetime(readings["timestamp"], utc=True)
    readings["value"] = pd.to_numeric(readings["value"], errors="coerce").astype(float)
    readings["building_id"] = building.building_id
    with_data = readings.loc[readings["value"].notna(), "meter_id"].nunique()
    if with_data < 2:
        return MachineComparison.model_validate(
            {
                **base,
                "available": False,
                "message": "A comparison needs at least two electricity meters in kWh with "
                f"readings; this building has {with_data}.",
                "first_reading": None,
                "last_reading": None,
                "main": None,
                "machines": [],
                "unmetered_kwh": None,
                "unmetered_share": None,
            }
        )
    result = compare(readings, building.timezone, hours, main_meter_id)
    present = readings.loc[readings["value"].notna(), "timestamp"]
    return MachineComparison.model_validate(
        {
            **base,
            **result,
            "available": True,
            "message": None,
            "first_reading": present.min().to_pydatetime(),
            "last_reading": present.max().to_pydatetime(),
        }
    )
