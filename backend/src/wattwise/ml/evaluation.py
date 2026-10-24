"""Evaluation harness: score a forecaster's predictions on a split (docs/EVALUATION.md, D021).

Predictions are scored only on the rows a split assigns to an evaluation role (validation, test,
test_unseen), never on training rows. They must cover exactly those rows: a missing prediction is
an explicit NaN, and it is counted. The error is `predicted - actual`, in the meters' unit.

- MAE, RMSE and bias (the mean error; a baseline that under-predicts would overstate excess
  energy later).
- WAPE = sum|error| / sum|actual|, reported only when sum|actual| reaches `wape_min_total`.
- Results per meter, per building (pooled over its meters), overall (pooled over all rows) and
  macro (the mean over meters).

The report records the forecaster, the split manifest, a fingerprint of the readings and the code
version. It holds no wall-clock time, so the same inputs give byte-identical reports.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from wattwise import __version__
from wattwise.ml.splits import Role, Split

EVALUATION_VERSION: Final = "1"
SCORED_ROLES: Final = (Role.VALIDATION, Role.TEST, Role.TEST_UNSEEN)
DECIMALS: Final = 6
FINGERPRINT_COLUMNS: Final = ("timestamp", "meter_id", "building_id", "meter_type", "unit", "value")
_BACKEND: Final = Path(__file__).resolve().parents[3]

FloatArray = npt.NDArray[np.float64]
Param = str | int | float | bool | None


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Thresholds(_Model):
    #: WAPE is reported only when sum|actual| over the scored rows reaches this, in the meters'
    #: unit. It stops near-zero meters from producing huge, meaningless percentages.
    wape_min_total: float = Field(1.0, gt=0)


class Metrics(_Model):
    scored: int  # rows with both an actual value and a prediction
    missing_actual: int  # rows without an actual value (never scored)
    missing_prediction: int  # rows with an actual value but no prediction
    total_actual: float  # sum|actual| over the scored rows
    mae: float | None
    rmse: float | None
    bias: float | None  # mean(predicted - actual); negative means under-prediction
    wape: float | None
    wape_note: str | None = None  # why WAPE is not reported


class Macro(_Model):
    meters: int  # meters with scored rows
    mae: float | None
    rmse: float | None
    bias: float | None
    wape: float | None
    wape_meters: int  # meters whose WAPE is reported (the mean is over these only)


class MeterScore(_Model):
    meter_id: str
    building_id: str
    metrics: Metrics


class BuildingScore(_Model):
    building_id: str
    meters: int
    metrics: Metrics


class RoleScore(_Model):
    fold: str
    role: Role
    unit: str
    overall: Metrics
    macro: Macro
    per_meter: tuple[MeterScore, ...]
    per_building: tuple[BuildingScore, ...]


class FoldSummary(_Model):
    """A role's pooled metrics across folds (one fold for a chronological split)."""

    role: Role
    folds: int
    mae_mean: float | None
    mae_min: float | None
    mae_max: float | None
    rmse_mean: float | None
    wape_mean: float | None
    wape_folds: int


class Forecaster(_Model):
    name: str
    params: dict[str, Param] = Field(default_factory=dict)


class CodeVersion(_Model):
    package_version: str
    git_commit: str | None = None
    git_dirty: bool | None = None  # changed or new (not git-ignored) files since the commit


class DataSummary(_Model):
    fingerprint: str
    rows: int
    meters: int
    first: str | None
    last: str | None


class EvaluationReport(_Model):
    evaluation_version: str = EVALUATION_VERSION
    forecaster: Forecaster
    code: CodeVersion
    data: DataSummary
    thresholds: Thresholds
    split: dict[str, Any]  # the split manifest (wattwise.ml.splits)
    scores: tuple[RoleScore, ...]
    fold_summaries: tuple[FoldSummary, ...]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_metrics(
    actual: npt.ArrayLike, predicted: npt.ArrayLike, thresholds: Thresholds | None = None
) -> Metrics:
    """Metrics over the rows where both values are present."""
    limits = thresholds or Thresholds()
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if a.shape != p.shape:
        raise ValueError(f"actual and predicted differ in shape: {a.shape} vs {p.shape}")
    has_actual, has_prediction = ~np.isnan(a), ~np.isnan(p)
    scored = has_actual & has_prediction
    counts = {
        "scored": int(scored.sum()),
        "missing_actual": int((~has_actual).sum()),
        "missing_prediction": int((has_actual & ~has_prediction).sum()),
    }
    if not scored.any():
        return Metrics(
            **counts,
            total_actual=0.0,
            mae=None,
            rmse=None,
            bias=None,
            wape=None,
            wape_note="no scored rows",
        )
    error = p[scored] - a[scored]
    absolute = np.abs(error)
    total = float(np.abs(a[scored]).sum())
    wape, note = None, None
    if total >= limits.wape_min_total:
        wape = _round(float(absolute.sum()) / total)
    else:
        note = f"total actual {total:g} is below the {limits.wape_min_total:g} threshold"
    return Metrics(
        **counts,
        total_actual=_round(total),
        mae=_round(float(absolute.mean())),
        rmse=_round(float(np.sqrt(np.mean(error**2)))),
        bias=_round(float(error.mean())),
        wape=wape,
        wape_note=note,
    )


def macro_average(meters: Sequence[MeterScore]) -> Macro:
    """The unweighted mean over meters, so small meters count as much as large ones."""
    scored = [m.metrics for m in meters if m.metrics.scored]
    wapes = [m.wape for m in scored if m.wape is not None]

    def mean(values: Sequence[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return _round(float(np.mean(present))) if present else None

    return Macro(
        meters=len(scored),
        mae=mean([m.mae for m in scored]),
        rmse=mean([m.rmse for m in scored]),
        bias=mean([m.bias for m in scored]),
        wape=mean(wapes),
        wape_meters=len(wapes),
    )


# ---------------------------------------------------------------------------
# Scoring a split
# ---------------------------------------------------------------------------


def evaluate(
    split: Split,
    predictions: Mapping[tuple[str, Role], pd.Series],
    forecaster: Forecaster,
    thresholds: Thresholds | None = None,
    code: CodeVersion | None = None,
) -> EvaluationReport:
    """Score predictions keyed by (fold name, role). Each series must be indexed by exactly the
    index labels of that role's rows (`split.folds[i].rows(role)`), with NaN where no prediction
    was made."""
    limits = thresholds or Thresholds()
    if not predictions:
        raise ValueError("No predictions to score.")
    readings = split.folds[0].readings
    if not readings.index.is_unique:
        raise ValueError("The readings index must be unique to align predictions; reset it.")
    folds = {part.fold.name: (i, part) for i, part in enumerate(split.folds)}

    def order(key: tuple[str, Role]) -> tuple[int, int]:
        fold, role = key
        return (folds[fold][0] if fold in folds else -1, list(Role).index(role))

    scores = []
    for fold, role in sorted(predictions, key=order):
        if role not in SCORED_ROLES:
            raise ValueError(
                f"{role} rows are never scored: a training score is not an evaluation."
            )
        if fold not in folds:
            raise ValueError(f"Unknown fold {fold!r}; the split has {sorted(folds)}.")
        part = folds[fold][1]
        if role not in part.positions:
            raise ValueError(f"Fold {fold!r} has no {role} role.")
        rows = part.rows(role)
        scores.append(
            _score_role(fold, role, rows, _aligned(rows, predictions[(fold, role)]), limits)
        )
    return EvaluationReport(
        forecaster=forecaster,
        code=code or code_version(),
        data=_data_summary(readings),
        thresholds=limits,
        split=split.manifest(),
        scores=tuple(scores),
        fold_summaries=_fold_summaries(scores),
    )


def _aligned(rows: pd.DataFrame, predicted: pd.Series) -> FloatArray:
    missing = rows.index.difference(predicted.index)
    extra = predicted.index.difference(rows.index)
    if predicted.index.has_duplicates or len(missing) or len(extra):
        raise ValueError(
            f"Predictions must cover exactly the {len(rows)} rows of the role: {len(missing)} "
            f"missing, {len(extra)} extra, duplicates {predicted.index.has_duplicates}. Use NaN "
            "for rows without a prediction."
        )
    return np.asarray(predicted.reindex(rows.index), dtype=float)


def _score_role(
    fold: str, role: Role, rows: pd.DataFrame, predicted: FloatArray, limits: Thresholds
) -> RoleScore:
    units = sorted(set(rows["unit"].astype(str)))
    if len(units) != 1:
        raise ValueError(f"{fold} {role}: one unit is required to score, found {units}.")
    frame = pd.DataFrame(
        {
            "meter_id": rows["meter_id"].astype(str).to_numpy(),
            "building_id": rows["building_id"].astype(str).to_numpy(),
            "actual": rows["value"].to_numpy(dtype=float),
            "predicted": predicted,
        }
    )
    per_meter = tuple(
        MeterScore(
            meter_id=str(meter),
            building_id=str(group["building_id"].iloc[0]),
            metrics=compute_metrics(group["actual"], group["predicted"], limits),
        )
        for meter, group in frame.groupby("meter_id", sort=True)
    )
    per_building = tuple(
        BuildingScore(
            building_id=str(building),
            meters=int(group["meter_id"].nunique()),
            metrics=compute_metrics(group["actual"], group["predicted"], limits),
        )
        for building, group in frame.groupby("building_id", sort=True)
    )
    return RoleScore(
        fold=fold,
        role=role,
        unit=units[0],
        overall=compute_metrics(frame["actual"], frame["predicted"], limits),
        macro=macro_average(per_meter),
        per_meter=per_meter,
        per_building=per_building,
    )


def _fold_summaries(scores: Sequence[RoleScore]) -> tuple[FoldSummary, ...]:
    summaries = []
    for role in SCORED_ROLES:
        overall = [s.overall for s in scores if s.role is role]
        if not overall:
            continue
        maes = [m.mae for m in overall if m.mae is not None]
        rmses = [m.rmse for m in overall if m.rmse is not None]
        wapes = [m.wape for m in overall if m.wape is not None]
        summaries.append(
            FoldSummary(
                role=role,
                folds=len(overall),
                mae_mean=_round(float(np.mean(maes))) if maes else None,
                mae_min=min(maes) if maes else None,
                mae_max=max(maes) if maes else None,
                rmse_mean=_round(float(np.mean(rmses))) if rmses else None,
                wape_mean=_round(float(np.mean(wapes))) if wapes else None,
                wape_folds=len(wapes),
            )
        )
    return tuple(summaries)


# ---------------------------------------------------------------------------
# Provenance: data fingerprint and code version
# ---------------------------------------------------------------------------


def fingerprint(readings: pd.DataFrame) -> str:
    """SHA-256 of the canonical readings' content, independent of row order and index.

    The rows are sorted by (meter_id, timestamp). Numbers are hashed as little-endian bytes with
    one NaN bit pattern and +0.0 for -0.0; text columns are hashed as sorted labels plus codes."""
    frame = readings[list(FINGERPRINT_COLUMNS)].sort_values(
        ["meter_id", "timestamp"], kind="stable"
    )
    digest = hashlib.sha256(f"wattwise-readings-v1;{len(frame)}\n".encode())
    times = frame["timestamp"].to_numpy(dtype="datetime64[us]").astype("<i8")
    digest.update(times.tobytes())
    values = frame["value"].to_numpy(dtype=float) + 0.0  # -0.0 becomes +0.0
    values[np.isnan(values)] = np.nan
    digest.update(values.astype("<f8").tobytes())
    for column in ("meter_id", "building_id", "meter_type", "unit"):
        codes, labels = pd.factorize(frame[column].astype(str), sort=True)
        digest.update(("\x1f".join(map(str, labels)) + "\n").encode())
        digest.update(codes.astype("<i8").tobytes())
    return digest.hexdigest()


def code_version(directory: Path = _BACKEND) -> CodeVersion:
    """The package version and, when run from a git checkout, the commit and whether any file
    that is not git-ignored has changed or been added since it."""

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *args], cwd=directory, capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    # New, uncommitted source files count as changes; git-ignored data folders do not.
    status = git("status", "--porcelain") if commit else None
    return CodeVersion(
        package_version=__version__,
        git_commit=commit or None,
        git_dirty=None if status is None else bool(status),
    )


def _data_summary(readings: pd.DataFrame) -> DataSummary:
    times = readings["timestamp"]
    return DataSummary(
        fingerprint=fingerprint(readings),
        rows=len(readings),
        meters=int(readings["meter_id"].nunique()),
        first=_iso(times.min()) if len(readings) else None,
        last=_iso(times.max()) if len(readings) else None,
    )


# ---------------------------------------------------------------------------
# Report files
# ---------------------------------------------------------------------------


def to_json(report: EvaluationReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2) + "\n"


def to_markdown(report: EvaluationReport) -> str:
    split = report.split
    kind = split["config"]["time"]["kind"]
    code = report.code
    commit = "not a git checkout" if code.git_commit is None else code.git_commit[:12]
    if code.git_dirty:
        commit += " (uncommitted changes)"
    unit = report.scores[0].unit if report.scores else "unit"
    lines = [
        f"# Evaluation: {report.forecaster.name}",
        "",
        f"- **Forecaster:** `{report.forecaster.name}`"
        + (f" with {_params(report.forecaster.params)}" if report.forecaster.params else ""),
        f"- **Data:** {report.data.rows:,} readings, {report.data.meters} meters, "
        f"{report.data.first} to {report.data.last}; fingerprint `{report.data.fingerprint[:16]}`",
        f"- **Split:** {kind}, {len(split['folds'])} fold(s), config "
        f"`{split['config_sha256'][:12]}`, {len(split['holdout_building_ids'])} held-out "
        "building(s)",
        f"- **Code:** wattwise {code.package_version}, {commit}",
        f"- **Errors** are predicted minus actual, in {unit}. WAPE is shown only when the total "
        f"actual is at least {report.thresholds.wape_min_total:g} {unit}.",
        "",
        "## Summary",
        "",
        "| Fold | Role | Meters | Scored | Missing prediction | MAE | RMSE | Bias | WAPE | "
        "Macro MAE | Macro WAPE (meters) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in report.scores:
        o, m = s.overall, s.macro
        lines.append(
            f"| {s.fold} | {s.role.value} | {m.meters} | {o.scored:,} | {o.missing_prediction:,} "
            f"| {_num(o.mae)} | {_num(o.rmse)} | {_num(o.bias)} | {_pct(o.wape)} | "
            f"{_num(m.mae)} | {_pct(m.wape)} ({m.wape_meters}) |"
        )
    for s in report.scores:
        lines += [
            "",
            f"## {s.fold} · {s.role.value}",
            "",
            "| Meter | Building | Scored | Missing actual | Missing prediction | MAE | RMSE | Bias "
            "| WAPE |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for meter in s.per_meter:
            x = meter.metrics
            wape = _pct(x.wape) if x.wape is not None else f"- ({x.wape_note})"
            lines.append(
                f"| `{meter.meter_id}` | `{meter.building_id}` | {x.scored:,} | "
                f"{x.missing_actual:,} | {x.missing_prediction:,} | {_num(x.mae)} | "
                f"{_num(x.rmse)} | {_num(x.bias)} | {wape} |"
            )
    return "\n".join(lines) + "\n"


def write_report(report: EvaluationReport, directory: Path, name: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"{name}.json", directory / f"{name}.md"]
    paths[0].write_bytes(to_json(report).encode("utf-8"))
    paths[1].write_bytes(to_markdown(report).encode("utf-8"))
    return paths


def _round(value: float) -> float:
    return round(value, DECIMALS)


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _params(params: Mapping[str, Param]) -> str:
    return ", ".join(f"`{k}={v}`" for k, v in sorted(params.items()))


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
