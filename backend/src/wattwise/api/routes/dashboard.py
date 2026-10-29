"""The dashboard summary."""

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.schemas.catalog import AlertTotals, DashboardSummary, DatasetSummary, KindSummary
from wattwise.db.models import UNREVIEWED, Alert, Building, Dataset, Meter

router = APIRouter(tags=["dashboard"])

#: Observed data first: it is the real data; synthetic data is for demonstration.
KIND_ORDER = ("observed", "synthetic")
OPEN_STATUSES = (UNREVIEWED, "needs_investigation")


def _alert_totals(session: Session) -> dict[str, AlertTotals]:
    """Alert totals per data kind, from the alerts table (thousands of rows, not readings)."""
    consumption = Alert.kind != "meter_problem"
    model = Alert.evidence["model"]
    rows = session.execute(
        select(
            Dataset.kind,
            Alert.kind,
            Alert.review_status,
            Alert.severity,
            func.count(),
            func.coalesce(func.sum(Alert.potential_excess_kwh), 0.0),
            func.coalesce(
                func.sum(case((consumption, cast(model["observed_kwh"].astext, Float)), else_=0.0)),
                0.0,
            ),
            func.coalesce(
                func.sum(case((consumption, cast(model["expected_kwh"].astext, Float)), else_=0.0)),
                0.0,
            ),
        )
        .join(Meter, Alert.meter_id == Meter.meter_id)
        .join(Building, Meter.building_id == Building.building_id)
        .join(Dataset, Building.dataset_id == Dataset.dataset_id)
        .where(Alert.superseded.is_(False))
        .group_by(Dataset.kind, Alert.kind, Alert.review_status, Alert.severity)
    ).all()
    totals: dict[str, dict[str, Any]] = {}
    for kind, alert_kind, status, severity, n, excess, observed, expected in rows:
        t = totals.setdefault(
            kind,
            {
                "alerts": 0,
                "open": 0,
                "high_severity": 0,
                "by_review_status": {},
                "by_kind": {},
                "potential_excess_kwh": 0.0,
                "observed_kwh_in_alerts": 0.0,
                "expected_kwh_in_alerts": 0.0,
            },
        )
        t["alerts"] += n
        t["by_review_status"][status] = t["by_review_status"].get(status, 0) + n
        t["by_kind"][alert_kind] = t["by_kind"].get(alert_kind, 0) + n
        if status in OPEN_STATUSES:
            t["open"] += n
            if severity == "high":
                t["high_severity"] += n
        t["potential_excess_kwh"] += float(excess)
        t["observed_kwh_in_alerts"] += float(observed)
        t["expected_kwh_in_alerts"] += float(expected)
    return {kind: AlertTotals.model_validate(t) for kind, t in totals.items()}


def _empty_alerts() -> AlertTotals:
    return AlertTotals(
        alerts=0,
        open=0,
        high_severity=0,
        by_review_status={},
        by_kind={},
        potential_excess_kwh=0.0,
        observed_kwh_in_alerts=0.0,
        expected_kwh_in_alerts=0.0,
    )


@router.get("/dashboard/summary", summary="Totals of the stored data")
def dashboard_summary(session: Annotated[Session, Depends(get_session)]) -> DashboardSummary:
    """Counts, measured energy and alert totals, per dataset and per kind of data (observed and
    synthetic are never added together).

    Dataset totals are stored when a dataset is loaded, so this does not scan the readings (it took
    11 s at 20 million rows when it did). Potential excess is an estimate, not a verified
    saving."""
    building_counts = {
        dataset_id: n
        for dataset_id, n in session.execute(
            select(Building.dataset_id, func.count()).group_by(Building.dataset_id)
        ).tuples()
    }
    meter_counts = {
        dataset_id: n
        for dataset_id, n in session.execute(
            select(Building.dataset_id, func.count())
            .select_from(Meter)
            .join(Building)
            .group_by(Building.dataset_id)
        ).tuples()
    }
    datasets = [
        DatasetSummary.model_validate(
            {
                "dataset_id": d.dataset_id,
                "name": d.name,
                "kind": d.kind,
                "buildings": building_counts.get(d.dataset_id, 0),
                "meters": meter_counts.get(d.dataset_id, 0),
                "readings": d.reading_count,
                "missing_values": d.missing_count,
                "first_reading": d.first_reading,
                "last_reading": d.last_reading,
                "measured_kwh": d.measured_kwh,
            }
        )
        for d in session.scalars(select(Dataset).order_by(Dataset.dataset_id))
    ]
    by_type: dict[str, int] = {
        meter_type: int(n)
        for meter_type, n in session.execute(
            select(Meter.meter_type, func.count())
            .group_by(Meter.meter_type)
            .order_by(Meter.meter_type)
        ).tuples()
    }
    alerts = _alert_totals(session)
    by_kind = []
    for kind in KIND_ORDER:
        group = [d for d in datasets if d.kind == kind]
        if not group:
            continue
        readings = sum(d.readings for d in group)
        missing = sum(d.missing_values for d in group)
        by_kind.append(
            KindSummary.model_validate(
                {
                    "kind": kind,
                    "datasets": len(group),
                    "buildings": sum(d.buildings for d in group),
                    "meters": sum(d.meters for d in group),
                    "readings": readings,
                    "missing_values": missing,
                    "missing_share": missing / readings if readings else None,
                    "first_reading": _earliest(d.first_reading for d in group),
                    "last_reading": _latest(d.last_reading for d in group),
                    "measured_kwh": sum(d.measured_kwh for d in group),
                    "alerts": alerts.get(kind, _empty_alerts()),
                }
            )
        )
    return DashboardSummary.model_validate(
        {
            "datasets": datasets,
            "data_kinds": sorted({d.kind for d in datasets}),
            "by_kind": by_kind,
            "buildings": sum(d.buildings for d in datasets),
            "meters": sum(d.meters for d in datasets),
            "meters_by_type": by_type,
            "readings": sum(d.readings for d in datasets),
            "missing_values": sum(d.missing_values for d in datasets),
            "first_reading": _earliest(d.first_reading for d in datasets),
            "last_reading": _latest(d.last_reading for d in datasets),
        }
    )


def _earliest(values: Iterable[datetime | None]) -> datetime | None:
    return min((v for v in values if v is not None), default=None)


def _latest(values: Iterable[datetime | None]) -> datetime | None:
    return max((v for v in values if v is not None), default=None)
