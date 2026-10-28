"""Alerts and reviewers' feedback."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.routes.catalog import Limit, Offset
from wattwise.api.schemas.alerts import (
    CAVEATS,
    AlertDetail,
    AlertKind,
    AlertSummary,
    FeedbackIn,
    FeedbackOut,
    ReviewStatus,
    Severity,
)
from wattwise.api.schemas.catalog import Page
from wattwise.db.models import Alert, AlertFeedback, Building, Dataset, Meter
from wattwise.ml.signatures import Signature

router = APIRouter(tags=["alerts"])

SessionDep = Annotated[Session, Depends(get_session)]


def _alerts() -> Select[Any]:
    count = (
        select(func.count(AlertFeedback.feedback_id))
        .where(AlertFeedback.alert_id == Alert.alert_id)
        .scalar_subquery()
    )
    return (
        select(Alert, Meter.building_id, Building.dataset_id, Dataset.kind, count.label("n"))
        .join(Meter, Alert.meter_id == Meter.meter_id)
        .join(Building, Meter.building_id == Building.building_id)
        .join(Dataset, Building.dataset_id == Dataset.dataset_id)
    )


def _summary_fields(
    alert: Alert, building_id: str, dataset_id: str, kind: str, n: int
) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "meter_id": alert.meter_id,
        "building_id": building_id,
        "dataset_id": dataset_id,
        "data_kind": kind,
        "detector": alert.detector,
        "start": alert.start,
        "end": alert.end,
        "duration_hours": alert.duration_hours,
        "flagged_hours": alert.flagged_hours,
        "direction": alert.direction,
        "signature": alert.signature,
        "kind": alert.kind,
        "severity": alert.severity,
        "priority_score": alert.priority_score,
        "potential_excess_kwh": alert.potential_excess_kwh,
        "review_status": alert.review_status,
        "reviewed_at": alert.reviewed_at,
        "feedback_count": n,
        "superseded": alert.superseded,
    }


@router.get("/alerts", summary="List alerts, highest priority first")
def list_alerts(
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    building_id: Annotated[str | None, Query()] = None,
    meter_id: Annotated[str | None, Query()] = None,
    dataset_id: Annotated[str | None, Query()] = None,
    signature: Annotated[Signature | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    kind: Annotated[AlertKind | None, Query()] = None,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    start: Annotated[
        AwareDatetime | None, Query(description="Alerts ending after this time.")
    ] = None,
    end: Annotated[
        AwareDatetime | None, Query(description="Alerts starting before this time.")
    ] = None,
    include_superseded: Annotated[
        bool, Query(description="Include reviewed alerts a later detection no longer finds.")
    ] = False,
) -> Page[AlertSummary]:
    """Alerts overlapping [`start`, `end`), ordered by priority score (highest first), then id.
    The score orders review; it is not a probability that an alert is real."""
    if start is not None and end is not None and start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")
    query = _alerts()
    filters = {
        Meter.building_id: building_id,
        Alert.meter_id: meter_id,
        Building.dataset_id: dataset_id,
        Alert.signature: None if signature is None else signature.value,
        Alert.severity: severity,
        Alert.kind: kind,
        Alert.review_status: review_status,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    if start is not None:
        query = query.where(Alert.end > start)
    if end is not None:
        query = query.where(Alert.start < end)
    if not include_superseded:
        query = query.where(Alert.superseded.is_(False))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(Alert.priority_score.desc(), Alert.alert_id).limit(limit).offset(offset)
    ).all()
    return Page[AlertSummary](
        items=[AlertSummary.model_validate(_summary_fields(*row)) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


def _detail(session: Session, alert_id: int) -> AlertDetail:
    row = session.execute(_alerts().where(Alert.alert_id == alert_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    alert = row[0]
    feedback = session.scalars(
        select(AlertFeedback)
        .where(AlertFeedback.alert_id == alert_id)
        .order_by(AlertFeedback.feedback_id)
    ).all()
    return AlertDetail.model_validate(
        {
            **_summary_fields(*row),
            "model_version": alert.model_version,
            "explanation": alert.evidence.get("explanation"),
            "evidence": alert.evidence,
            "feedback": [
                {
                    "feedback_id": f.feedback_id,
                    "alert_id": f.alert_id,
                    "label": f.label,
                    "note": f.note,
                    "reviewer": f.reviewer,
                    "created_at": f.created_at,
                }
                for f in feedback
            ],
            "caveats": list(CAVEATS),
        }
    )


@router.get(
    "/alerts/{alert_id}",
    summary="One alert with its evidence and reviews",
    responses={404: {"description": "No such alert."}},
)
def get_alert(alert_id: int, session: SessionDep) -> AlertDetail:
    return _detail(session, alert_id)


@router.post(
    "/alerts/{alert_id}/feedback",
    summary="Record a reviewer's verdict",
    status_code=201,
    responses={
        404: {"description": "No such alert."},
        422: {"description": "An unknown label, or a note or reviewer that is invalid."},
    },
)
def add_feedback(alert_id: int, body: FeedbackIn, session: SessionDep) -> FeedbackOut:
    """Append a review and set the alert's review status to its label.

    Reviews are kept as a history (a new verdict does not overwrite an old one). They are
    stored for people and later evaluation; **no model is retrained from them** (D047)."""
    if session.get(Alert, alert_id) is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    feedback = AlertFeedback(
        alert_id=alert_id, label=body.label.value, note=body.note, reviewer=body.reviewer
    )
    session.add(feedback)
    session.flush()  # now() is the transaction's time: reviewed_at equals created_at
    session.execute(
        update(Alert)
        .where(Alert.alert_id == alert_id)
        .values(review_status=body.label.value, reviewed_at=func.now(), updated_at=func.now())
    )
    session.commit()
    session.refresh(feedback)
    return FeedbackOut.model_validate(
        {
            "feedback_id": feedback.feedback_id,
            "alert_id": feedback.alert_id,
            "label": feedback.label,
            "note": feedback.note,
            "reviewer": feedback.reviewer,
            "created_at": feedback.created_at,
        }
    )
