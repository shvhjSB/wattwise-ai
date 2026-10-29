"""Model metadata, recorded metrics and analysis-run monitoring records."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wattwise.api.dependencies import get_app_settings, get_session
from wattwise.api.routes.catalog import Limit, Offset
from wattwise.api.schemas.catalog import Page
from wattwise.api.schemas.models import (
    METRIC_DEFINITIONS,
    AnalysisRunOut,
    ModelMetadataOut,
    ModelMetricsOut,
    RoleMetrics,
    Unavailable,
)
from wattwise.core.config import Settings
from wattwise.db.models import AnalysisRun
from wattwise.ml.registry import (
    IncompatibleModelError,
    Metadata,
    NoModelError,
    RegistryError,
    current,
    verify,
)

router = APIRouter(tags=["models"])

SERVES = "Expected consumption in POST /inference/analyze (D048): the evaluation model."
METRICS_NOTE = (
    "Recorded when the model was trained, on BDG2 readings in a chronological split: the test "
    "window is strictly later than training. They describe BDG2 buildings, not uploaded ones."
)


@lru_cache(maxsize=8)
def _verified(root: str, version: str) -> Metadata:
    """A version's verified metadata. Versions are immutable folders, so the (slow) hash check
    runs once per version; failures are not cached."""
    return verify(version, Path(root))


def promoted(root: Path) -> Metadata | Unavailable:
    """The promoted model's metadata, or why it is unavailable (without file paths)."""
    try:
        return _verified(str(root), current(root))
    except NoModelError:
        return Unavailable(reason="no_model_promoted", message="No model has been promoted.")
    except IncompatibleModelError:
        return Unavailable(
            reason="model_incompatible",
            message="The promoted model was made for another artifact or feature-set version.",
        )
    except RegistryError:
        return Unavailable(
            reason="model_invalid",
            message="The promoted model is missing or does not match its recorded hashes.",
        )


@router.get("/models/metadata", summary="The promoted model's metadata")
def model_metadata(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelMetadataOut | Unavailable:
    """What the served model is, how it was trained and on what. Without a usable model the
    answer is `available: false` with the reason, never invented values."""
    metadata = promoted(settings.registry_root)
    if isinstance(metadata, Unavailable):
        return metadata
    training = metadata.training.model_dump()
    split = training.pop("split_config")
    return ModelMetadataOut.model_validate(
        {
            "version": metadata.version,
            "created_at": metadata.created_at,
            "serves": SERVES,
            "model": metadata.model.model_dump(),
            "feature_set_version": metadata.feature_set_version,
            "horizon_hours": metadata.horizon_hours,
            "feature_columns": metadata.feature_columns,
            "training": training,
            "split": split,
            "code": metadata.code.model_dump(),
            "libraries": metadata.libraries,
        }
    )


@router.get("/models/metrics", summary="The promoted model's recorded metrics")
def model_metrics(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelMetricsOut | Unavailable:
    """Validation and test metrics as recorded at training time, with their windows and
    definitions. A role that was not recorded is null, not estimated."""
    metadata = promoted(settings.registry_root)
    if isinstance(metadata, Unavailable):
        return metadata
    time = metadata.training.split_config.get("time") or {}
    windows = {
        "validation": (time.get("validation_start"), time.get("test_start")),
        "test": (time.get("test_start"), time.get("test_end")),
    }
    roles = [
        RoleMetrics.model_validate(
            {
                "role": role,
                "window_start": windows[role][0],
                "window_end": windows[role][1],
                "metrics": metadata.metrics.get(role),
            }
        )
        for role in ("validation", "test")
    ]
    return ModelMetricsOut(
        version=metadata.version, roles=roles, definitions=METRIC_DEFINITIONS, note=METRICS_NOTE
    )


@router.get("/analysis-runs", summary="Monitoring records of analysis runs, newest first")
def list_analysis_runs(
    session: Annotated[Session, Depends(get_session)],
    limit: Limit = 50,
    offset: Offset = 0,
    model_version: str | None = None,
) -> Page[AnalysisRunOut]:
    """One record per `/inference/analyze` call: model version, time, input range and counts.
    The uploaded readings themselves are not stored."""
    query = select(AnalysisRun)
    if model_version is not None:
        query = query.where(AnalysisRun.model_version == model_version)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    runs = session.scalars(
        query.order_by(AnalysisRun.created_at.desc(), AnalysisRun.run_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[AnalysisRunOut](
        items=[
            AnalysisRunOut.model_validate({c: getattr(run, c) for c in AnalysisRunOut.model_fields})
            for run in runs
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )
