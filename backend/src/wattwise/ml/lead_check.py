"""Detector check against LEAD 1.0 human labels (docs/EVALUATION.md, D031).

**Real data, human labels without measured agreement.** LEAD's annotators marked anomalous hours
on BDG2 meters in 2016. Nobody has measured how often annotators agree, so a label is one
person's judgement, not ground truth. Only labels whose LEAD reading equals BDG2's raw reading
are used (D022): elsewhere the annotator saw different numbers from the ones scored here.

LEAD's year lies inside the adopted model's training period, so a separate model is trained for
this check, chronologically:
- **train:** January to May 2016
- **calibration:** June 2016 (the model detector's median and MAD)
- **detection:** July 2016 to the end of the year, where the labels are scored

Both detectors run with their standard settings (D030); nothing is tuned on the labels. The
readings are BDG2's **raw** variant, which is what LEAD labelled.

    uv run python -m wattwise.data.bdg2_prepare --variant raw --sample-meters 0
    uv run python -m wattwise.ml.lead_check --data ../data/processed/bdg2/raw \\
        --labels ../data/processed/lead/labels.parquet \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.ml.baselines import SeasonalNaive, run
from wattwise.ml.detection import (
    DETECTOR_DEFAULTS,
    Detector,
    DetectorConfig,
    calibrate,
    detect,
    rolling_same_hour,
)
from wattwise.ml.evaluation import compute_metrics
from wattwise.ml.features import build_features
from wattwise.ml.models import overall
from wattwise.ml.registry import train
from wattwise.ml.splits import Chronological, Role, SplitConfig, make_split

CHECK_VERSION: Final = "1"
LABEL: Final = "real data, human labels without measured agreement (LEAD 1.0)"
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/lead_check")
#: Train Jan-May 2016, calibrate in June, detect from July. The BDG2 local year ends up to 8 h
#: later in UTC, hence 2 January.
SPLIT: Final = SplitConfig(
    time=Chronological(
        train_start=datetime(2016, 1, 1, tzinfo=UTC),
        validation_start=datetime(2016, 6, 1, tzinfo=UTC),
        test_start=datetime(2016, 7, 1, tzinfo=UTC),
        test_end=datetime(2017, 1, 2, tzinfo=UTC),
    )
)
SEGMENT_LENGTHS: Final = (("1-2 h", 1, 2), ("3-23 h", 3, 23), ("24 h or more", 24, 10**9))


# ---------------------------------------------------------------------------
# Scoring against labels
# ---------------------------------------------------------------------------


def flagged_hours(events: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    """For each row (meter_id, timestamp): whether its hour lies inside an event of its meter."""
    if events.empty or rows.empty:
        return np.zeros(len(rows), dtype=bool)
    parts = [
        pd.DataFrame(
            {
                "meter_id": meter,
                "timestamp": pd.date_range(
                    pd.Timestamp(start), pd.Timestamp(end), freq="h", inclusive="left"
                ),
            }
        )
        for meter, start, end in zip(
            events["meter_id"], events["start"], events["end"], strict=True
        )
    ]
    covered = pd.MultiIndex.from_frame(
        pd.concat(parts, ignore_index=True).astype({"timestamp": rows["timestamp"].dtype})
    )
    wanted = pd.MultiIndex.from_frame(rows[["meter_id", "timestamp"]])
    return np.asarray(wanted.isin(covered), dtype=bool)


def segments(labels: pd.DataFrame) -> pd.DataFrame:
    """Runs of consecutive labelled-anomaly hours per meter: meter_id, start, end (exclusive),
    hours."""
    hits = labels[labels["anomaly"] == 1].sort_values(["meter_id", "timestamp"], kind="stable")
    if hits.empty:
        return pd.DataFrame(columns=["meter_id", "start", "end", "hours"])
    step = hits["timestamp"].diff() != pd.Timedelta(hours=1)
    new = step | (hits["meter_id"] != hits["meter_id"].shift())
    run_id = new.cumsum()
    grouped = hits.groupby(run_id)
    return pd.DataFrame(
        {
            "meter_id": grouped["meter_id"].first().to_numpy(),
            "start": grouped["timestamp"].min().to_numpy(),
            "end": (grouped["timestamp"].max() + pd.Timedelta(hours=1)).to_numpy(),
            "hours": grouped.size().to_numpy(),
        }
    )


def _overlaps(intervals: pd.DataFrame, events: pd.DataFrame) -> np.ndarray:
    """For each interval (meter_id, start, end): whether an event of its meter overlaps it."""
    found = np.zeros(len(intervals), dtype=bool)
    for meter, mine in events.groupby("meter_id"):
        rows = np.flatnonzero((intervals["meter_id"] == meter).to_numpy())
        for i in rows:
            s, e = intervals["start"].iloc[i], intervals["end"].iloc[i]
            found[i] = bool(((mine["start"] < e) & (mine["end"] > s)).any())
    return found


def score(events: pd.DataFrame, labels: pd.DataFrame, meter_weeks: float) -> dict[str, Any]:
    """Hour-, segment- and event-level agreement with the trusted labels of the detection rows.

    `labels` are the LEAD rows inside the detection window. Untrusted rows count neither way;
    an event is judged only on hours with a trusted label."""
    trusted = labels[labels["lead_reading_matches_bdg2_raw"]].reset_index(drop=True)
    anomaly = (trusted["anomaly"] == 1).to_numpy()
    flagged = flagged_hours(events, trusted)
    tp = int((flagged & anomaly).sum())
    fp = int((flagged & ~anomaly).sum())
    fn = int((~flagged & anomaly).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None

    runs = segments(trusted)
    found = _overlaps(runs, events) if len(runs) else np.zeros(0, dtype=bool)
    by_length = {}
    for name, low, high in SEGMENT_LENGTHS:
        mask = ((runs["hours"] >= low) & (runs["hours"] <= high)).to_numpy() if len(runs) else found
        by_length[name] = {
            "segments": int(mask.sum()),
            "recall": round(float(found[mask].mean()), 4) if mask.any() else None,
        }

    true_events = false_events = unjudged = 0
    untrusted_hits = labels[~labels["lead_reading_matches_bdg2_raw"] & (labels["anomaly"] == 1)]
    by_meter = {str(m): g.sort_values("timestamp") for m, g in trusted.groupby("meter_id")}
    doubtful_by_meter = {
        str(m): np.sort(g["timestamp"].to_numpy(dtype="datetime64[us]"))
        for m, g in untrusted_hits.groupby("meter_id")
    }
    for meter, mine_events in events.groupby("meter_id"):
        rows = by_meter.get(str(meter))
        times = (
            rows["timestamp"].to_numpy(dtype="datetime64[us]")
            if rows is not None
            else np.array([], "datetime64[us]")
        )
        flags = rows["anomaly"].to_numpy() if rows is not None else np.array([], dtype=np.int8)
        doubtful_times = doubtful_by_meter.get(str(meter), np.array([], "datetime64[us]"))
        for start, end in zip(mine_events["start"], mine_events["end"], strict=True):
            lo, hi = np.searchsorted(times, [start.to_datetime64(), end.to_datetime64()])
            d_lo, d_hi = np.searchsorted(
                doubtful_times, [start.to_datetime64(), end.to_datetime64()]
            )
            if (flags[lo:hi] == 1).any():
                true_events += 1
            elif hi > lo and d_hi == d_lo:
                false_events += 1
            else:
                unjudged += 1
    judged = true_events + false_events
    return {
        "trusted_label_hours": len(trusted),
        "trusted_anomaly_hours": int(anomaly.sum()),
        "chance_precision": round(float(anomaly.mean()), 4) if len(trusted) else None,
        "hours": {
            "flagged": int(flagged.sum()),
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(f1),
        },
        "segments": {
            "count": len(runs),
            "median_hours": float(runs["hours"].median()) if len(runs) else None,
            "recall": round(float(found.mean()), 4) if len(runs) else None,
            "by_length": by_length,
        },
        "events": {
            "count": len(events),
            "overlapping_a_labelled_anomaly": true_events,
            "on_labelled_normal_hours_only": false_events,
            "unjudged": unjudged,
            "precision": _round(true_events / judged if judged else None),
            "per_meter_week": round(len(events) / meter_weeks, 4) if meter_weeks else None,
        },
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    readings: pd.DataFrame
    buildings: pd.DataFrame
    weather: pd.DataFrame | None
    enrichment: pd.DataFrame | None
    labels: pd.DataFrame


def run_check(inputs: Inputs, split: SplitConfig = SPLIT) -> dict[str, Any]:
    """Train on the split's training window, then score both detectors against the labels in
    its test window."""
    time = split.time
    assert isinstance(time, Chronological) and time.validation_start is not None
    meters = sorted(set(inputs.labels["meter_id"]) & set(inputs.readings["meter_id"]))
    if not meters:
        raise ValueError("No labelled meter has readings: prepare the raw variant first.")
    readings = inputs.readings[
        inputs.readings["meter_id"].isin(meters) & (inputs.readings["timestamp"] < time.test_end)
    ].reset_index(drop=True)
    features = build_features(readings, inputs.buildings, inputs.weather, inputs.enrichment)
    trained = train(readings, inputs.buildings, features, split)

    split_rows = make_split(readings, split, inputs.buildings)
    naive = run(split_rows, [SeasonalNaive()], roles=(Role.TEST,))
    model_test = trained.metrics["test"]
    naive_test = overall(naive, SeasonalNaive().name, Role.TEST)
    test_rows = split_rows.folds[0].rows(Role.TEST)
    predicted = trained.model.predict(test_rows.drop(columns="value"), readings)
    lag = naive.predictions[SeasonalNaive().name][(split_rows.folds[0].fold.name, Role.TEST)]
    actual = test_rows["value"].to_numpy(dtype=float)
    common = ~(np.isnan(actual) | np.isnan(predicted.to_numpy()) | np.isnan(lag.to_numpy()))
    common_model = compute_metrics(actual[common], predicted.to_numpy()[common])
    common_naive = compute_metrics(actual[common], lag.to_numpy()[common])

    times = readings["timestamp"]
    calibration_rows = ((times >= time.validation_start) & (times < time.test_start)).to_numpy()
    detection_rows = ((times >= time.test_start) & (times < time.test_end)).to_numpy()
    window_labels = inputs.labels[
        inputs.labels["meter_id"].isin(meters)
        & (inputs.labels["timestamp"] >= time.test_start)
        & (inputs.labels["timestamp"] < time.test_end)
    ]
    labelled_meters = int(window_labels["meter_id"].nunique())
    weeks = (time.test_end - time.test_start) / pd.Timedelta(weeks=1)

    detectors: dict[str, Any] = {}
    for detector in Detector:
        config = DetectorConfig(**DETECTOR_DEFAULTS[detector])  # type: ignore[arg-type]
        if detector is Detector.MODEL:
            expected = trained.model.predict(readings.drop(columns="value"), readings)
            calibration = calibrate(readings, expected, calibration_rows, config)
            found = detect(readings, expected, calibration, detection_rows, config)
        else:
            z, baseline = rolling_same_hour(readings, floor_fraction=config.scale_floor_fraction)
            found = detect(readings, baseline, None, detection_rows, config, z=z)
        events = found.events[found.events["meter_id"].isin(set(window_labels["meter_id"]))]
        detectors[detector.value] = {
            "settings": config.model_dump(mode="json"),
            **score(events, window_labels, labelled_meters * weeks),
        }

    return {
        "label": LABEL,
        "check_version": CHECK_VERSION,
        "split": split.model_dump(mode="json"),
        "meters": len(meters),
        "meters_with_labels_in_detection_window": labelled_meters,
        "readings": len(readings),
        "label_rows_in_detection_window": len(window_labels),
        "untrusted_label_rows_in_detection_window": int(
            (~window_labels["lead_reading_matches_bdg2_raw"]).sum()
        ),
        "forecast_context": {
            "model": trained.model.name,
            "training_rows": trained.training.training_rows,
            "test_mae_model": model_test["mae"],
            "test_mae_seasonal_naive": naive_test["mae"],
            "common_rows": int(common.sum()),
            "common_rows_mae_model": common_model.mae,
            "common_rows_mae_seasonal_naive": common_naive.mae,
        },
        "detectors": detectors,
        "notes": [
            "Labels are one annotator's judgement; agreement between annotators is unmeasured.",
            "Only labels whose LEAD reading equals BDG2's raw reading are scored (D022).",
            "Detector settings are the T018 defaults; nothing was tuned on these labels.",
        ],
    }


def to_markdown(report: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "—" if value is None else f"{value:.1%}"

    f = report["forecast_context"]
    t = report["split"]["time"]
    lines = [
        "# Detector check against LEAD labels (T018b)",
        "",
        f"**{report['label']}.**",
        "",
        f"- Train {t['train_start']} to {t['validation_start']}; calibrate to {t['test_start']}; "
        f"detect to {t['test_end']}",
        f"- {report['meters']} labelled meters with raw BDG2 readings; "
        f"{report['meters_with_labels_in_detection_window']} labelled in the detection window; "
        f"{report['label_rows_in_detection_window']:,} label rows there, of which "
        f"{report['untrusted_label_rows_in_detection_window']:,} are untrusted",
        f"- Forecast context ({f['model']}): test MAE {f['test_mae_model']} against "
        f"{f['test_mae_seasonal_naive']} for seasonal-naive; on {f['common_rows']:,} common rows "
        f"{f['common_rows_mae_model']} against {f['common_rows_mae_seasonal_naive']}",
        "",
        "| Detector | Hour precision | Hour recall | Hour F1 | Chance precision | Segment "
        "recall | Event precision | Events per meter-week |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, d in report["detectors"].items():
        h, s, e = d["hours"], d["segments"], d["events"]
        lines.append(
            f"| {name} | {pct(h['precision'])} | {pct(h['recall'])} | {pct(h['f1'])} | "
            f"{pct(d['chance_precision'])} | {pct(s['recall'])} | {pct(e['precision'])} | "
            f"{e['per_meter_week']} |"
        )
    lines += ["", "| Detector | " + " | ".join(n for n, _, _ in SEGMENT_LENGTHS) + " |"]
    lines.append("|---|" + "---|" * len(SEGMENT_LENGTHS))
    for name, d in report["detectors"].items():
        cells = [
            f"{pct(v['recall'])} of {v['segments']}" for v in d["segments"]["by_length"].values()
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", *(f"- {n}" for n in report["notes"])]
    return "\n".join(lines) + "\n"


def _read(path: Path) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path.exists() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.lead_check",
        description="Score the detectors against LEAD 1.0 human labels (local data only).",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared raw BDG2 tables")
    parser.add_argument("--labels", type=Path, required=True, help="LEAD labels.parquet (T007c)")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        inputs = Inputs(
            readings=pd.read_parquet(args.data / "readings.parquet"),
            buildings=pd.read_parquet(args.data / "buildings.parquet"),
            weather=_read(args.data / "weather.parquet"),
            enrichment=_read(args.enrichment) if args.enrichment else None,
            labels=pd.read_parquet(args.labels),
        )
        report = run_check(inputs)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "lead_check.json").write_bytes(
        (json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    text = to_markdown(report)
    (args.output / "lead_check.md").write_bytes(text.encode("utf-8"))
    print(text)
    for name in ("lead_check.json", "lead_check.md"):
        print(f"{name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
