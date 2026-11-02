"""Data drift in the model lab (T048): how readings and the model's errors move over the stored
evaluation window, compared with the training period. Everything is computed from the stored
readings and expectations, in SQL, so it scales to millions of rows."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.routes.catalog import Limit, Offset
from wattwise.api.schemas.catalog import Page
from wattwise.api.schemas.drift import (
    DriftOut,
    DriftUnavailable,
    MeterDrift,
    Period,
    PeriodDrift,
)
from wattwise.db.models import Dataset, ExpectationSet

router = APIRouter(tags=["models"])

#: WAPE needs a meaningful denominator (as in the T011 harness): at least this much consumption.
WAPE_MIN_TOTAL: Final = 1.0
#: Windows shorter than this are shown by week, longer ones by month.
WEEKLY_UNDER: Final = timedelta(days=120)

_PER_METER = text(
    """
    WITH ds AS (
        SELECT m.meter_id
        FROM meters m JOIN buildings b ON b.building_id = m.building_id
        WHERE b.dataset_id = :dataset_id
    ),
    ref AS (
        SELECT r.meter_id, avg(r.value) AS level
        FROM readings r JOIN ds ON ds.meter_id = r.meter_id
        WHERE r."timestamp" < :reference_end AND r.value IS NOT NULL
        GROUP BY r.meter_id
    ),
    pairs AS (
        SELECT e.meter_id,
               date_trunc(:period, e."timestamp" AT TIME ZONE 'UTC') AS period,
               r.value AS observed, e.expected, e.lower, e.upper
        FROM expectations e
        JOIN ds ON ds.meter_id = e.meter_id
        JOIN readings r ON r.meter_id = e.meter_id AND r."timestamp" = e."timestamp"
        WHERE r.value IS NOT NULL AND e.expected IS NOT NULL
    )
    SELECT p.period, p.meter_id, count(*) AS n, avg(p.observed) AS observed,
           sum(abs(p.observed - p.expected)) AS abs_error, sum(abs(p.observed)) AS total,
           sum(p.expected - p.observed) AS bias_sum,
           count(*) FILTER (WHERE p.lower IS NOT NULL AND p.upper IS NOT NULL) AS with_interval,
           count(*) FILTER (WHERE p.observed BETWEEN p.lower AND p.upper) AS inside,
           ref.level
    FROM pairs p LEFT JOIN ref ON ref.meter_id = p.meter_id
    GROUP BY 1, 2, ref.level
    ORDER BY 1, 2
    """
)


def _ratio(observed: float, level: float | None) -> float | None:
    return round(observed / level, 4) if level is not None and level > 0 else None


def _share(part: float, whole: float, minimum: float = 0.0) -> float | None:
    return round(part / whole, 4) if whole > minimum and whole > 0 else None


def _aggregate(rows: list[Any]) -> tuple[list[PeriodDrift], dict[datetime, list[MeterDrift]]]:
    grouped: dict[datetime, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.period.replace(tzinfo=UTC)].append(row)
    periods, meters = [], {}
    for start in sorted(grouped):
        group = grouped[start]
        n = sum(r.n for r in group)
        total = sum(float(r.total) for r in group)
        ratios = [x for r in group if (x := _ratio(float(r.observed), r.level)) is not None]
        periods.append(
            PeriodDrift(
                start=start,
                readings=n,
                meters=len(group),
                median_level_ratio=round(statistics.median(ratios), 4) if ratios else None,
                wape=_share(sum(float(r.abs_error) for r in group), total, WAPE_MIN_TOTAL),
                bias=round(sum(float(r.bias_sum) for r in group) / n, 4) if n else None,
                coverage=_share(sum(r.inside for r in group), sum(r.with_interval for r in group)),
            )
        )
        meters[start] = [
            MeterDrift(
                meter_id=r.meter_id,
                readings=r.n,
                level_ratio=_ratio(float(r.observed), r.level),
                wape=_share(float(r.abs_error), float(r.total), WAPE_MIN_TOTAL),
                coverage=_share(r.inside, r.with_interval),
            )
            for r in group
        ]
    return periods, meters


@router.get(
    "/models/drift",
    summary="Data drift over the stored evaluation window",
    responses={404: {"description": "No such dataset."}},
)
def model_drift(
    session: Annotated[Session, Depends(get_session)],
    dataset_id: Annotated[
        str | None, Query(description="A dataset with stored expectations; default the first.")
    ] = None,
    period: Annotated[
        Period | None, Query(description="week or month; default by the window's length.")
    ] = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> DriftOut | DriftUnavailable:
    """Per week or month of the window the model's expectations are stored for: how far meters'
    readings moved from their training-period level, and the model's WAPE, bias and interval
    coverage. Then every meter in the latest period, largest level change first. Drift describes
    change, not failure."""
    sets = {s.dataset_id: s for s in session.scalars(select(ExpectationSet))}
    available = sorted(sets)
    if dataset_id is None:
        if not available:
            return DriftUnavailable(
                message="No dataset has stored expectations, so there is nothing to compare. "
                "Expectations are stored when a model's evaluation is loaded (T030).",
                datasets=[],
            )
        dataset_id = available[0]
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    chosen = sets.get(dataset_id)
    if chosen is None:
        return DriftUnavailable(
            message=f"{dataset_id} has no stored expectations to compare against.",
            datasets=available,
        )
    window_start = chosen.window_start.astimezone(UTC)
    window_end = chosen.window_end.astimezone(UTC)
    unit: Period = period or ("week" if window_end - window_start < WEEKLY_UNDER else "month")
    rows = list(
        session.execute(
            _PER_METER,
            {"dataset_id": dataset_id, "reference_end": window_start, "period": unit},
        )
    )
    periods, meters = _aggregate(rows)
    latest = periods[-1].start if periods else None
    ranked = sorted(
        meters.get(latest, []) if latest is not None else [],
        key=lambda m: (
            m.level_ratio is None,
            -abs((m.level_ratio or 1.0) - 1.0),
            m.meter_id,
        ),
    )
    return DriftOut(
        dataset_id=dataset_id,
        data_kind=dataset.kind,  # type: ignore[arg-type]
        datasets=available,
        model_version=chosen.model_version,
        interval_nominal=chosen.interval_nominal,
        period=unit,
        reference_end=window_start,
        window_start=window_start,
        window_end=window_end,
        periods=periods,
        latest_period=latest,
        meters=Page[MeterDrift](
            items=ranked[offset : offset + limit], total=len(ranked), limit=limit, offset=offset
        ),
    )
