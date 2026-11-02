"""A dataset's stored data-quality audit (T047)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_session
from wattwise.api.routes.catalog import Limit, Offset
from wattwise.api.schemas.catalog import Page
from wattwise.api.schemas.quality import (
    CHECK_DEFINITIONS,
    CheckOut,
    DatasetQualityOut,
    FindingOut,
    MeterQualityOut,
    QualityNotAssessed,
)
from wattwise.data.quality import QualityCheck
from wattwise.db.models import Dataset, DatasetQuality

router = APIRouter(tags=["data"])

NOT_ASSESSED = (
    "This dataset was loaded before audits were stored. Run `python -m wattwise.db.quality "
    "--dataset-id {dataset_id}` to audit its stored readings."
)


def _meter(meter: dict[str, Any]) -> MeterQualityOut:
    findings = [FindingOut.model_validate(f) for f in meter["findings"]]
    return MeterQualityOut.model_validate(
        {
            **{k: v for k, v in meter.items() if k != "findings"},
            "findings": findings,
            "warnings": sum(1 for f in findings if f.severity == "warning"),
        }
    )


@router.get(
    "/datasets/{dataset_id}/quality",
    summary="A dataset's data-quality audit, with its meters",
    responses={404: {"description": "No such dataset."}},
)
def dataset_quality(
    dataset_id: str,
    session: Annotated[Session, Depends(get_session)],
    limit: Limit = 50,
    offset: Offset = 0,
    check: Annotated[
        QualityCheck | None, Query(description="Only meters with this check's findings.")
    ] = None,
    warnings_only: Annotated[
        bool, Query(description="Only meters with at least one warning.")
    ] = False,
) -> DatasetQualityOut | QualityNotAssessed:
    """The audit stored when the dataset was loaded: what was checked, with which thresholds,
    and every meter's coverage and findings (warnings first, then by meter). Findings describe
    the data, not the building; a cause in a message is a hypothesis to check."""
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    audit = session.scalar(select(DatasetQuality).where(DatasetQuality.dataset_id == dataset_id))
    if audit is None:
        return QualityNotAssessed(
            dataset_id=dataset_id,
            name=dataset.name,
            data_kind=dataset.kind,  # type: ignore[arg-type]
            message=NOT_ASSESSED.format(dataset_id=dataset_id),
        )
    meters = [_meter(m) for m in audit.meters]
    affected = {
        c: sum(1 for m in meters if any(f.check == c for f in m.findings))
        for c in CHECK_DEFINITIONS
    }
    selected = [
        m
        for m in meters
        if (check is None or any(f.check == check for f in m.findings))
        and (not warnings_only or m.warnings > 0)
    ]
    selected.sort(key=lambda m: (-m.warnings, m.meter_id))
    return DatasetQualityOut(
        dataset_id=dataset_id,
        name=dataset.name,
        data_kind=dataset.kind,  # type: ignore[arg-type]
        assessed_at=audit.assessed_at,
        quality_version=audit.quality_version,
        contract_version=audit.contract_version,
        thresholds=audit.thresholds,
        summary=audit.summary,
        checks=[
            CheckOut(check=c, definition=d, meters=affected[c])
            for c, d in CHECK_DEFINITIONS.items()
        ],
        meters=Page[MeterQualityOut](
            items=selected[offset : offset + limit],
            total=len(selected),
            limit=limit,
            offset=offset,
        ),
    )
