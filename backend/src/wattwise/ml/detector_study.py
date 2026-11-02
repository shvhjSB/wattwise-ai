"""T054: can the default detector find more human-labelled anomalies within the alert budget?

The protocol is fixed in docs/reports/t054-detector-protocol.md (D072) **before** the held-out
window is scored, and the constants below are that protocol:

- **Data:** LEAD 1.0 trusted labels (D022) and BDG2 **raw** readings of the labelled meters, as in
  the T044c check. LEAD stays local; only aggregate results are published.
- **Detectors:** model-free only, the rolling same-hour z-score family (the default alert source,
  D030), so no model is trained and nothing depends on LEAD's year being inside a training window.
- **Windows (chronological):** development July to September 2016; held-out October 2016 to
  2 January 2017, strictly later and scored **once**. Earlier readings are history only.
- **Candidates:** 18 settings, crossing the baseline statistic (mean and standard deviation, or
  median and MAD), the opening threshold (3, 4, 5) and the short-event rule (an event shorter than
  `min_hours` is kept if its peak reaches `z_spike`: the opening threshold itself, 6 or 8).
  The current default is mean, 4, 8.
- **Selection (development only):** the highest segment recall among settings within the alert
  budget (0.5 events per meter-week, D030); ties within 0.001 go to fewer events, then the default.
- **Acceptance (held-out, all required):** segment recall at least 0.03 above the default's, with a
  meter-clustered bootstrap 95 % interval of the difference above zero; at most 0.5 events per
  meter-week; event precision at most 0.02 below the default's; no duration band's recall more
  than 0.05 below the default's.

    uv run python -m wattwise.ml.detector_study development --data ../data/processed/bdg2/raw \\
        --labels ../data/processed/lead/labels.parquet
    uv run python -m wattwise.ml.detector_study held-out --data ../data/processed/bdg2/raw \\
        --labels ../data/processed/lead/labels.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

from wattwise.ml.detection import (
    DETECTOR_DEFAULTS,
    Detector,
    DetectorConfig,
    detect,
    rolling_same_hour,
)
from wattwise.ml.lead_check import SEGMENT_LENGTHS, _overlaps, score, segments

STUDY_VERSION: Final = "1"
LABEL: Final = "real data, human labels without measured agreement (LEAD 1.0)"
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/detector_study")
#: Alert budget, events per meter-week (D030: a product assumption the owner can change).
BUDGET: Final = 0.5
HISTORY_START: Final = datetime(2016, 6, 1, tzinfo=UTC)  # history for the 14-day window
DEVELOPMENT: Final = (datetime(2016, 7, 1, tzinfo=UTC), datetime(2016, 10, 1, tzinfo=UTC))
HELD_OUT: Final = (datetime(2016, 10, 1, tzinfo=UTC), datetime(2017, 1, 2, tzinfo=UTC))
TIE: Final = 0.001
MIN_GAIN: Final = 0.03
MAX_PRECISION_LOSS: Final = 0.02
MAX_BAND_LOSS: Final = 0.05
RESAMPLES: Final = 2000
SEED: Final = 0


@dataclass(frozen=True)
class Candidate:
    statistic: str  # "mean" (mean and standard deviation) or "median" (median and MAD)
    z_on: float
    z_spike: float

    @property
    def name(self) -> str:
        return f"{self.statistic}-on{self.z_on:g}-spike{self.z_spike:g}"

    def config(self) -> DetectorConfig:
        settings = cast(dict[str, Any], DETECTOR_DEFAULTS[Detector.ROLLING_Z])
        return DetectorConfig(**settings, z_on=self.z_on, z_spike=self.z_spike)


DEFAULT: Final = Candidate("mean", 4.0, 8.0)
CANDIDATES: Final = tuple(
    Candidate(statistic, z_on, z_spike)
    for statistic in ("mean", "median")
    for z_on in (3.0, 4.0, 5.0)
    for z_spike in (z_on, 6.0, 8.0)
)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def window_rows(readings: pd.DataFrame, window: tuple[datetime, datetime]) -> np.ndarray:
    times = readings["timestamp"]
    return ((times >= window[0]) & (times < window[1])).to_numpy()


def window_labels(labels: pd.DataFrame, window: tuple[datetime, datetime]) -> pd.DataFrame:
    inside = (labels["timestamp"] >= window[0]) & (labels["timestamp"] < window[1])
    return labels[inside].reset_index(drop=True)


def per_meter_segments(events: pd.DataFrame, labels: pd.DataFrame) -> dict[str, list[int]]:
    """For each meter with trusted labelled segments: [segments, segments found]."""
    trusted = labels[labels["lead_reading_matches_bdg2_raw"]]
    runs = segments(trusted)
    if runs.empty:
        return {}
    found = _overlaps(runs, events)
    table = pd.DataFrame({"meter_id": runs["meter_id"].astype(str), "found": found})
    grouped = table.groupby("meter_id")["found"].agg(["size", "sum"])
    return {str(m): [int(r["size"]), int(r["sum"])] for m, r in grouped.iterrows()}


def evaluate(
    readings: pd.DataFrame,
    labels: pd.DataFrame,
    window: tuple[datetime, datetime],
    candidates: Sequence[Candidate],
) -> dict[str, dict[str, Any]]:
    """Each candidate's agreement with the trusted labels inside `window`, scored with the T018b
    rules (`lead_check.score`), plus per-meter segment counts for the bootstrap."""
    rows = window_rows(readings, window)
    here = window_labels(labels, window)
    meters = set(here["meter_id"])
    weeks = (window[1] - window[0]) / pd.Timedelta(weeks=1)
    results: dict[str, dict[str, Any]] = {}
    for statistic in sorted({c.statistic for c in candidates}):
        z, baseline = rolling_same_hour(readings, statistic=statistic)
        for candidate in (c for c in candidates if c.statistic == statistic):
            found = detect(readings, baseline, None, rows, candidate.config(), z=z)
            events = found.events[found.events["meter_id"].isin(meters)]
            results[candidate.name] = {
                "candidate": candidate.__dict__,
                **score(events, here, len(meters) * weeks),
                "per_meter": per_meter_segments(events, here),
            }
    return results


def select(results: Mapping[str, Mapping[str, Any]], budget: float = BUDGET) -> str:
    """The development choice: the highest segment recall within the budget; ties (within TIE)
    go to fewer events per meter-week, then the default. The default if nothing is within it."""
    within = {
        name: r
        for name, r in results.items()
        if r["events"]["per_meter_week"] is not None and r["events"]["per_meter_week"] <= budget
    }
    if not within:
        return DEFAULT.name
    best = max(r["segments"]["recall"] or 0.0 for r in within.values())
    ties = [n for n, r in within.items() if (r["segments"]["recall"] or 0.0) >= best - TIE]
    return min(ties, key=lambda n: (within[n]["events"]["per_meter_week"], n != DEFAULT.name, n))


def bootstrap_difference(
    baseline: Mapping[str, Sequence[int]],
    candidate: Mapping[str, Sequence[int]],
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> tuple[float, float]:
    """95 % interval of candidate minus baseline segment recall, resampling meters (paired:
    both detectors see the same labelled segments)."""
    meters = sorted(set(baseline) | set(candidate))
    if not meters:
        return (float("nan"), float("nan"))
    total = np.array([baseline.get(m, candidate.get(m, [0, 0]))[0] for m in meters], dtype=float)
    hits_a = np.array([baseline.get(m, [0, 0])[1] for m in meters], dtype=float)
    hits_b = np.array([candidate.get(m, [0, 0])[1] for m in meters], dtype=float)
    draw = np.random.default_rng(seed).integers(0, len(meters), size=(resamples, len(meters)))
    segments_drawn = total[draw].sum(axis=1)
    keep = segments_drawn > 0
    differences = (hits_b[draw].sum(axis=1) - hits_a[draw].sum(axis=1))[keep] / segments_drawn[keep]
    low, high = np.quantile(differences, [0.025, 0.975])
    return (round(float(low), 4), round(float(high), 4))


def accept(
    default: Mapping[str, Any], chosen: Mapping[str, Any], interval: tuple[float, float]
) -> dict[str, Any]:
    """The four predeclared criteria on the held-out window, each with its result."""
    gain = (chosen["segments"]["recall"] or 0.0) - (default["segments"]["recall"] or 0.0)
    precision_change = (chosen["events"]["precision"] or 0.0) - (
        default["events"]["precision"] or 0.0
    )
    band_changes = {
        name: round(
            (chosen["segments"]["by_length"][name]["recall"] or 0.0)
            - (default["segments"]["by_length"][name]["recall"] or 0.0),
            4,
        )
        for name, _, _ in SEGMENT_LENGTHS
    }
    criteria = {
        "recall_gain_at_least_0.03": gain >= MIN_GAIN,
        "bootstrap_interval_above_zero": interval[0] > 0,
        "within_budget": chosen["events"]["per_meter_week"] <= BUDGET,
        "event_precision_loss_at_most_0.02": precision_change >= -MAX_PRECISION_LOSS,
        "no_band_loses_more_than_0.05": all(v >= -MAX_BAND_LOSS for v in band_changes.values()),
    }
    return {
        "segment_recall_gain": round(gain, 4),
        "bootstrap_95_interval": list(interval),
        "event_precision_change": round(precision_change, 4),
        "band_recall_changes": band_changes,
        "criteria": criteria,
        "passed": all(criteria.values()),
    }


# ---------------------------------------------------------------------------
# Why short segments are missed (development window, default setting)
# ---------------------------------------------------------------------------


def diagnose_short_misses(readings: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    """For the 1-2 h labelled segments the default misses in the development window: the largest
    |z| inside the segment, in bands that say which rule stopped it."""
    here = window_labels(labels, DEVELOPMENT)
    rows = window_rows(readings, DEVELOPMENT)
    z, baseline = rolling_same_hour(readings)
    found = detect(readings, baseline, None, rows, DEFAULT.config(), z=z)
    events = found.events[found.events["meter_id"].isin(set(here["meter_id"]))]
    runs = segments(here[here["lead_reading_matches_bdg2_raw"]])
    short = runs[runs["hours"] <= 2].reset_index(drop=True)
    missed = short[~_overlaps(short, events)] if len(short) else short
    keyed = pd.DataFrame(
        {
            "meter_id": readings["meter_id"].astype(str).to_numpy(),
            "timestamp": readings["timestamp"].to_numpy(),
            "z": z.to_numpy(),
            "value": readings["value"].to_numpy(dtype=float),
        }
    ).set_index(["meter_id", "timestamp"])
    bands = {"no score": 0, "below 4": 0, "4 to 8": 0, "8 or more": 0}
    zero = above = below = 0
    for meter, start, hours in zip(
        missed["meter_id"].astype(str), missed["start"], missed["hours"], strict=True
    ):
        stamps = pd.date_range(pd.Timestamp(start), periods=int(hours), freq="h")
        index = pd.MultiIndex.from_arrays([[meter] * len(stamps), stamps])
        inside = keyed.reindex(index)
        scores = inside["z"].to_numpy(dtype=float)
        values = inside["value"].to_numpy(dtype=float)
        if np.isnan(scores).all():
            bands["no score"] += 1
        else:
            peak = float(np.nanmax(np.abs(scores)))
            bands["below 4" if peak < 4 else "4 to 8" if peak < 8 else "8 or more"] += 1
            signed = scores[np.nanargmax(np.abs(scores))]
            above += int(signed > 0)
            below += int(signed < 0)
        zero += int(np.nanmin(values) == 0) if not np.isnan(values).all() else 0
    return {
        "short_segments": len(short),
        "missed": len(missed),
        "missed_by_peak_abs_z": bands,
        "missed_with_a_zero_reading": zero,
        "missed_above_baseline": above,
        "missed_below_baseline": below,
        "note": "4 to 8: an event opened (z >= 4) but was dropped, because fewer than 3 hours "
        "reached z >= 2 and its peak stayed below z_spike = 8. Below 4: the deviation was within "
        "four of the baseline's standard deviations, so no event opened.",
    }


# ---------------------------------------------------------------------------
# Running the two phases
# ---------------------------------------------------------------------------


def load_inputs(data: Path, labels_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The labelled meters' raw readings from HISTORY_START to the held-out end, and the labels."""
    labels = pd.read_parquet(labels_path)
    meters = sorted(set(labels["meter_id"]))
    readings = pd.read_parquet(
        data / "readings.parquet",
        columns=["timestamp", "meter_id", "building_id", "meter_type", "unit", "value"],
        filters=[
            ("meter_id", "in", meters),
            ("timestamp", ">=", pd.Timestamp(HISTORY_START)),
            ("timestamp", "<", pd.Timestamp(HELD_OUT[1])),
        ],
    )
    readings = readings.sort_values(["meter_id", "timestamp"], kind="stable").reset_index(drop=True)
    labels = labels[labels["meter_id"].isin(set(readings["meter_id"]))].reset_index(drop=True)
    return readings, labels


def _public(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Results without per-meter counts: those are only for the bootstrap and are not written,
    so no output lists LEAD meters one by one."""
    return {n: {k: v for k, v in r.items() if k != "per_meter"} for n, r in results.items()}


def development(readings: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    results = evaluate(readings, labels, DEVELOPMENT, CANDIDATES)
    return {
        "label": LABEL,
        "study_version": STUDY_VERSION,
        "window": [w.isoformat() for w in DEVELOPMENT],
        "budget": BUDGET,
        "meters": int(labels["meter_id"].nunique()),
        "selected": select(results),
        "default": DEFAULT.name,
        "candidates": _public(results),
        "short_misses": diagnose_short_misses(readings, labels),
    }


def held_out(readings: pd.DataFrame, labels: pd.DataFrame, selected: str) -> dict[str, Any]:
    """Scores the default and the development choice once on the held-out window."""
    chosen = next(c for c in CANDIDATES if c.name == selected)
    results = evaluate(
        readings, labels, HELD_OUT, [DEFAULT] if chosen == DEFAULT else [DEFAULT, chosen]
    )
    default, picked = results[DEFAULT.name], results[chosen.name]
    interval = bootstrap_difference(default["per_meter"], picked["per_meter"])
    return {
        "label": LABEL,
        "study_version": STUDY_VERSION,
        "window": [w.isoformat() for w in HELD_OUT],
        "budget": BUDGET,
        "selected": selected,
        "default": DEFAULT.name,
        "results": _public(results),
        "acceptance": accept(default, picked, interval),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.detector_study",
        description="T054: compare detector settings on LEAD labels (local data only).",
    )
    parser.add_argument("phase", choices=["development", "held-out"])
    parser.add_argument("--data", type=Path, required=True, help="prepared raw BDG2 tables")
    parser.add_argument("--labels", type=Path, required=True, help="LEAD labels.parquet (T007c)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    dev_file, held_file = args.output / "development.json", args.output / "held_out.json"
    if args.phase == "held-out":
        if held_file.exists():
            print(f"error: {held_file} exists: the held-out window is scored once", file=sys.stderr)
            return 1
        if not dev_file.exists():
            print("error: run the development phase first", file=sys.stderr)
            return 1
    readings, labels = load_inputs(args.data, args.labels)
    if args.phase == "development":
        report = development(readings, labels)
        target = dev_file
    else:
        selected = json.loads(dev_file.read_text(encoding="utf-8"))["selected"]
        report = held_out(readings, labels, selected)
        target = held_file
    target.write_bytes((json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("candidates", "results")}, indent=1
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
