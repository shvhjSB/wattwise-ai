"""Residual-based anomaly detection with hysteresis and event grouping (docs/DETECTION.md, D028).

For each meter and hour, the residual is observed minus expected consumption. It is turned into
a score with the meter's robust statistics from a **calibration** window that the model did not
train on: z = (residual - median) / (1.4826 * MAD). Detection runs on rows after calibration.

Events, separately for high (above expected) and low (below expected) deviations:
- an event **opens** at a score of at least `z_on`, and **stays open** while the score is at
  least `z_off` (hysteresis)
- gaps of up to `max_gap_hours` (scores below `z_off`, or no score) are bridged, so adjacent
  windows merge; a longer gap closes the event at its last flagged hour
- an event is **kept** if it has at least `min_hours` flagged hours (persistence), or a single
  score of at least `z_spike`

**Long events.** The adopted model's history features look back at least one week (D025). Once
an event has lasted `horizon_hours`, those features contain the anomaly itself, and the model
starts to expect it. From then on, the event is scored against a **pre-event reference**: the
meter's own reading at the same hour of the week, from the last week before the event started.
That residual has its own calibrated median and scale (from seasonal-naive residuals).

An event is an anomaly to investigate, not confirmed waste. Its residual sum is the deviation
from the baseline used, not verified excess energy (T021 estimates that with intervals).

    uv run python -m wattwise.ml.detection --data ../data/processed/bdg2/cleaned \
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from wattwise.data.acquisition import sha256_of
from wattwise.ml.registry import (
    DEFAULT_ROOT,
    Loaded,
    NoModelError,
    RegistryError,
    load,
    read_inputs,
)
from wattwise.ml.splits import Chronological, SplitConfig

FloatArray = npt.NDArray[np.float64]

DETECTOR_VERSION: Final = "1"
MAD_TO_SIGMA: Final = 1.4826
WEEK_HOURS: Final = 168
DEFAULT_OUTPUT: Final = Path("../data/processed/detection")
EVENT_COLUMNS: Final = (
    "meter_id",
    "building_id",
    "direction",
    "start",
    "end",
    "duration_hours",
    "flagged_hours",
    "missing_hours",
    "reference_hours",
    "peak_time",
    "peak_z",
    "peak_residual",
    "residual_sum",
    "ongoing",
)
HOUR_COLUMNS: Final = ("event", "timestamp", "value", "baseline", "score")


class DetectorConfig(BaseModel):
    """Provisional defaults, not tuned: the injected-anomaly benchmark (T018) evaluates them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    z_on: float = Field(4.0, gt=0)
    z_off: float = Field(2.0, gt=0)
    min_hours: int = Field(3, ge=1)
    z_spike: float = Field(8.0, gt=0)
    max_gap_hours: int = Field(2, ge=0)
    #: After this many hours of an event, score it against the pre-event reference. None turns
    #: the reference off (the model alone scores the whole event).
    horizon_hours: int | None = Field(WEEK_HOURS, ge=1)
    reference_weeks: int = Field(4, ge=1)  # how many weeks back to look for a pre-event reading
    #: The scale is at least this share of the meter's mean absolute reading in calibration, so
    #: a meter the model fits almost perfectly does not turn tiny deviations into alarms.
    scale_floor_fraction: float = Field(0.01, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.z_off < self.z_on <= self.z_spike:
            raise ValueError("Thresholds must satisfy z_off < z_on <= z_spike.")
        return self


@dataclass(frozen=True)
class Calibration:
    """Per meter: robust centre and scale of model residuals and of pre-event-reference
    (seasonal-naive) residuals, from the calibration rows only."""

    center: pd.Series
    scale: pd.Series
    reference_center: pd.Series
    reference_scale: pd.Series
    rows: pd.Series  # calibration rows with a model residual


@dataclass(frozen=True)
class Detection:
    events: pd.DataFrame  # EVENT_COLUMNS, sorted by meter, start, direction
    scores: pd.DataFrame  # meter_id, timestamp, value, expected, z (detection rows)
    #: Every hour of every event: event (row of `events`), timestamp, value, the baseline the
    #: detector used (expected, or the pre-event reference), and the score in the event's
    #: direction. Missing hours have NaN values.
    hours: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=HOUR_COLUMNS))


def _robust(values: pd.Series, floor: float) -> tuple[float, float]:
    clean = values.dropna().to_numpy(dtype=float)
    if clean.size == 0:
        return np.nan, np.nan
    center = float(np.median(clean))
    mad = float(np.median(np.abs(clean - center))) * MAD_TO_SIGMA
    return center, max(mad, floor)


def calibrate(
    readings: pd.DataFrame,
    expected: pd.Series,
    rows: npt.NDArray[np.bool_] | pd.Series,
    config: DetectorConfig | None = None,
) -> Calibration:
    """Robust statistics per meter from the `rows` of `readings` (a boolean mask), with
    `expected` indexed like `readings`. Reference residuals use the reading one week earlier."""
    config = config or DetectorConfig()
    mask = np.asarray(rows, dtype=bool)
    frame = readings[["meter_id", "timestamp", "value"]].assign(
        expected=expected.reindex(readings.index).to_numpy(dtype=float)
    )
    observed = frame.set_index(["meter_id", "timestamp"])["value"]
    observed = observed[~observed.index.duplicated()]
    week_ago = pd.MultiIndex.from_arrays(
        [frame["meter_id"], frame["timestamp"] - pd.Timedelta(hours=WEEK_HOURS)]
    )
    frame["reference"] = observed.reindex(week_ago).to_numpy(dtype=float)
    part = frame[mask]
    center, scale, ref_center, ref_scale, counts = {}, {}, {}, {}, {}
    for meter, group in part.groupby("meter_id", sort=True):
        floor = max(config.scale_floor_fraction * float(group["value"].abs().mean()), 1e-9)
        residual = group["value"] - group["expected"]
        center[meter], scale[meter] = _robust(residual, floor)
        ref_center[meter], ref_scale[meter] = _robust(group["value"] - group["reference"], floor)
        counts[meter] = int(residual.notna().sum())
    return Calibration(
        center=pd.Series(center, dtype=float),
        scale=pd.Series(scale, dtype=float),
        reference_center=pd.Series(ref_center, dtype=float),
        reference_scale=pd.Series(ref_scale, dtype=float),
        rows=pd.Series(counts, dtype="int64"),
    )


def detect(
    readings: pd.DataFrame,
    expected: pd.Series,
    calibration: Calibration,
    rows: npt.NDArray[np.bool_] | pd.Series,
    config: DetectorConfig | None = None,
) -> Detection:
    """Events among the `rows` of `readings` (a boolean mask). Earlier readings of the same
    meter serve only as pre-event references."""
    config = config or DetectorConfig()
    mask = np.asarray(rows, dtype=bool)
    frame = readings[["meter_id", "building_id", "timestamp", "value"]].assign(
        expected=expected.reindex(readings.index).to_numpy(dtype=float), detect=mask
    )
    events: list[dict[str, Any]] = []
    scores: list[pd.DataFrame] = []
    for meter, group in frame.groupby("meter_id", sort=True):
        if not group["detect"].any() or meter not in calibration.scale.index:
            continue
        hours = pd.date_range(group["timestamp"].min(), group["timestamp"].max(), freq="h")
        grid = group.set_index("timestamp").reindex(hours)
        actual = grid["value"].to_numpy(dtype=float)
        base = grid["expected"].to_numpy(dtype=float)
        active = grid["detect"].eq(True).to_numpy(dtype=bool)
        z = (actual - base - calibration.center[meter]) / calibration.scale[meter]
        building = str(group["building_id"].iloc[0])
        for sign, direction in ((1.0, "high"), (-1.0, "low")):
            events += _scan(
                hours, actual, base, sign * z, active, sign, direction, str(meter), building,
                calibration, config,
            )  # fmt: skip
        detected = group[group["detect"]]
        position = hours.get_indexer(pd.DatetimeIndex(detected["timestamp"]))
        scores.append(
            pd.DataFrame(
                {
                    "meter_id": str(meter),
                    "timestamp": detected["timestamp"].to_numpy(),
                    "value": detected["value"].to_numpy(dtype=float),
                    "expected": detected["expected"].to_numpy(dtype=float),
                    "z": z[position],
                }
            )
        )
    events.sort(key=lambda e: (e["meter_id"], e["start"], e["direction"]))
    table = pd.DataFrame([{k: e[k] for k in EVENT_COLUMNS} for e in events], columns=EVENT_COLUMNS)
    hour_parts = [
        pd.DataFrame(e["_hours"], columns=HOUR_COLUMNS[1:]).assign(event=i)
        for i, e in enumerate(events)
    ]
    hour_table = (
        pd.concat(hour_parts, ignore_index=True)[list(HOUR_COLUMNS)]
        if hour_parts
        else pd.DataFrame(columns=HOUR_COLUMNS)
    )
    score_table = (
        pd.concat(scores, ignore_index=True)
        if scores
        else pd.DataFrame(columns=["meter_id", "timestamp", "value", "expected", "z"])
    )
    return Detection(events=table, scores=score_table, hours=hour_table)


def _scan(
    hours: pd.DatetimeIndex,
    actual: FloatArray,
    base: FloatArray,
    score: FloatArray,
    active: npt.NDArray[np.bool_],
    sign: float,
    direction: str,
    meter: str,
    building: str,
    calibration: Calibration,
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    """The hysteresis state machine for one meter and direction."""
    found: list[dict[str, Any]] = []
    positions = np.flatnonzero(active)
    if positions.size == 0:
        return found
    last_active = int(positions[-1])
    ref_center = calibration.reference_center.get(meter, np.nan)
    ref_scale = calibration.reference_scale.get(meter, np.nan)
    start: int | None = None
    last = 0
    for t in positions.tolist():
        if start is None:
            if score[t] >= config.z_on:
                start, last = t, t
            continue
        if t - last > config.max_gap_hours + 1:  # the gap since the last flagged hour is too long
            found += _close(start, last, hours, actual, base, score, sign, direction, meter,
                            building, ref_center, ref_scale, config, ongoing=False)  # fmt: skip
            start = t if score[t] >= config.z_on else None
            last = t
            continue
        value = _event_score(t, start, actual, score, sign, ref_center, ref_scale, config)
        if value >= config.z_off:
            last = t
    if start is not None:
        ongoing = last_active - last <= config.max_gap_hours
        found += _close(start, last, hours, actual, base, score, sign, direction, meter,
                        building, ref_center, ref_scale, config, ongoing=ongoing)  # fmt: skip
    return found


def _reference(t: int, start: int, actual: FloatArray, weeks: int) -> float:
    """The meter's reading at the same hour of the week, in the last week before `start`."""
    k = (t - start) // WEEK_HOURS + 1
    for extra in range(weeks):
        j = t - (k + extra) * WEEK_HOURS
        if j < 0:
            break
        if j < start and not np.isnan(actual[j]):
            return float(actual[j])
    return np.nan


def _uses_reference(t: int, start: int, config: DetectorConfig) -> bool:
    return config.horizon_hours is not None and t - start >= config.horizon_hours


def _event_score(
    t: int,
    start: int,
    actual: FloatArray,
    score: FloatArray,
    sign: float,
    ref_center: float,
    ref_scale: float,
    config: DetectorConfig,
) -> float:
    if not _uses_reference(t, start, config):
        return float(score[t])
    reference = _reference(t, start, actual, config.reference_weeks)
    return float(sign * (actual[t] - reference - ref_center) / ref_scale)


def _close(
    start: int,
    last: int,
    hours: pd.DatetimeIndex,
    actual: FloatArray,
    base: FloatArray,
    score: FloatArray,
    sign: float,
    direction: str,
    meter: str,
    building: str,
    ref_center: float,
    ref_scale: float,
    config: DetectorConfig,
    ongoing: bool,
) -> list[dict[str, Any]]:
    flagged = missing = reference_hours = 0
    total = 0.0
    peak_value, peak_at, peak_residual = -np.inf, start, np.nan
    recorded: list[tuple[pd.Timestamp, float, float, float]] = []
    for t in range(start, last + 1):
        uses_reference = _uses_reference(t, start, config)
        value = _event_score(t, start, actual, score, sign, ref_center, ref_scale, config)
        baseline = (
            _reference(t, start, actual, config.reference_weeks) if uses_reference else base[t]
        )
        recorded.append((hours[t], float(actual[t]), float(baseline), value))
        if np.isnan(value):
            missing += 1
            continue
        reference_hours += uses_reference
        flagged += value >= config.z_off
        total += actual[t] - baseline
        if value > peak_value:
            peak_value, peak_at, peak_residual = value, t, actual[t] - baseline
    if flagged < config.min_hours and peak_value < config.z_spike:
        return []
    return [
        {
            "meter_id": meter,
            "building_id": building,
            "direction": direction,
            "start": hours[start],
            "end": hours[last] + pd.Timedelta(hours=1),
            "duration_hours": last - start + 1,
            "flagged_hours": int(flagged),
            "missing_hours": missing,
            "reference_hours": int(reference_hours),
            "peak_time": hours[peak_at],
            "peak_z": round(float(peak_value), 3),
            "peak_residual": round(float(peak_residual), 3),
            "residual_sum": round(total, 3),
            "ongoing": ongoing,
            "_hours": recorded,
        }
    ]


# ---------------------------------------------------------------------------
# Running on prepared data with the promoted model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    model: Loaded
    calibration: Calibration
    detection: Detection
    events: pd.DataFrame  # detection.events with signatures (T017)
    calibration_window: tuple[datetime, datetime]
    detection_window: tuple[datetime, datetime]


def run_detection(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    features: pd.DataFrame,
    root: Path = DEFAULT_ROOT,
    config: DetectorConfig | None = None,
) -> Run:
    """Calibrate on the promoted model's validation window, detect in its test window (both
    out-of-sample for the model), and classify the events into signatures."""
    from wattwise.ml.signatures import classify  # imported here: signatures imports this module

    config = config or DetectorConfig()
    loaded = load(features, root=root)
    split = SplitConfig.model_validate(loaded.metadata.training.split_config).time
    if not isinstance(split, Chronological) or split.validation_start is None:
        raise RegistryError("The model's split has no validation window to calibrate on.")
    expected = loaded.model.predict(readings.drop(columns="value"), readings)
    times = readings["timestamp"]
    calibration_rows = (times >= split.validation_start) & (times < split.test_start)
    detection_rows = (times >= split.test_start) & (times < split.test_end)
    calibration = calibrate(readings, expected, calibration_rows, config)
    detection = detect(readings, expected, calibration, detection_rows, config)
    return Run(
        model=loaded,
        calibration=calibration,
        detection=detection,
        events=classify(detection, buildings, config.z_off),
        calibration_window=(split.validation_start, split.test_start),
        detection_window=(split.test_start, split.test_end),
    )


def summary(run: Run, config: DetectorConfig) -> dict[str, Any]:
    events = run.events
    per_meter = (
        events.groupby(["meter_id", "direction"]).size().unstack(fill_value=0)
        if len(events)
        else pd.DataFrame()
    )
    scored = run.detection.scores["z"].notna()
    return {
        "detector_version": DETECTOR_VERSION,
        "config": config.model_dump(mode="json"),
        "model_version": run.model.metadata.version,
        "model": run.model.metadata.model.name,
        "calibration_window_utc": [_iso(t) for t in run.calibration_window],
        "detection_window_utc": [_iso(t) for t in run.detection_window],
        "calibration_rows": {k: int(v) for k, v in run.calibration.rows.items()},
        "detection_rows": len(run.detection.scores),
        "detection_rows_scored": int(scored.sum()),
        "events": len(events),
        "events_by_direction": {d: int((events["direction"] == d).sum()) for d in ("high", "low")},
        "event_hours": int(events["duration_hours"].sum()) if len(events) else 0,
        "events_using_pre_event_reference": int((events["reference_hours"] > 0).sum())
        if len(events)
        else 0,
        "events_by_signature": {
            str(k): int(v) for k, v in events["signature"].value_counts().sort_index().items()
        }
        if len(events)
        else {},
        "events_per_meter": {
            str(m): {str(d): int(n) for d, n in row.items()} for m, row in per_meter.iterrows()
        },
        "interpretation": "Events are anomalies to investigate, not confirmed waste. Residual "
        "sums are deviations from the baseline used, not verified excess energy.",
    }


def to_markdown(data: dict[str, Any], events: pd.DataFrame) -> str:
    c = data["config"]
    lines = [
        "# Anomaly events (T016)",
        "",
        data["interpretation"],
        "",
        f"- Model: `{data['model_version']}` ({data['model']})",
        f"- Calibration window (UTC): {' to '.join(data['calibration_window_utc'])}; detection "
        f"window: {' to '.join(data['detection_window_utc'])}",
        f"- Thresholds: open at |z| >= {c['z_on']}, stay open at >= {c['z_off']}, bridge gaps of "
        f"up to {c['max_gap_hours']} h, keep with >= {c['min_hours']} flagged hours or a spike "
        f">= {c['z_spike']}; pre-event reference after {c['horizon_hours']} h",
        f"- Rows scored: {data['detection_rows_scored']:,} of {data['detection_rows']:,}",
        f"- Events: {data['events']} ({data['events_by_direction']['high']} high, "
        f"{data['events_by_direction']['low']} low), {data['event_hours']:,} event hours; "
        f"{data['events_using_pre_event_reference']} used the pre-event reference",
        "",
        "- Signatures (primary): "
        + (", ".join(f"{k} {v}" for k, v in data["events_by_signature"].items()) or "none"),
        "",
        "| Meter | Direction | Signature | Start (UTC) | Hours | Flagged | Peak z | Residual sum "
        "| Ongoing |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    top = events.sort_values("duration_hours", ascending=False, kind="stable").head(25)
    for e in top.itertuples():
        lines.append(
            f"| {e.meter_id} | {e.direction} | {e.signature} | {_iso(e.start)} | "
            f"{e.duration_hours} | {e.flagged_hours} | {e.peak_z} | {e.residual_sum} | "
            f"{'yes' if e.ongoing else 'no'} |"
        )
    if len(events) > len(top):
        lines.append(f"\nThe {len(top)} longest of {len(events)} events; all are in events.csv.")
    return "\n".join(lines) + "\n"


def write(run: Run, config: DetectorConfig, output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    events = run.events.copy()
    for column in ("start", "end", "peak_time"):
        events[column] = events[column].map(_iso)
    events.to_csv(output / "events.csv", index=False, lineterminator="\n")
    run.detection.scores.to_parquet(output / "scores.parquet", index=False)
    data = summary(run, config)
    (output / "summary.json").write_bytes(
        (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    (output / "report.md").write_bytes(to_markdown(data, run.events).encode("utf-8"))
    return {
        name: sha256_of(output / name)
        for name in ("events.csv", "scores.parquet", "summary.json", "report.md")
    }


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.detection",
        description="Detect anomaly events with the promoted model (out-of-sample windows).",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    config = DetectorConfig()
    try:
        readings, buildings, features = read_inputs(args.data, args.enrichment)
        result = run_detection(readings, buildings, features, args.root, config)
    except NoModelError as exc:
        print(f"error: {exc} Train and promote one: python -m wattwise.ml.registry train "
              "--promote ...", file=sys.stderr)  # fmt: skip
        return 1
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    digests = write(result, config, args.output)
    print(to_markdown(summary(result, config), result.events))
    for name, digest in digests.items():
        print(f"{name}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
