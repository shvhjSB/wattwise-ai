"""Injected-anomaly benchmark for the detectors (docs/EVALUATION.md, D030).

Known anomalies are injected into **real BDG2 readings**, and the detectors must find them. This
is a **synthetic benchmark on a real background**: the anomalies are made up, the consumption
around them is not. Real data has its own unlabelled anomalies, so alerts outside the injected
windows are an **upper bound** on false alerts, not a false-alert count.

Procedure, with the promoted model's split:
- **Calibration:** the model's validation window (as in T016), from uninjected data.
- **Tuning:** each replicate injects one anomaly per meter into the first third of the test
  window, rebuilds the features (so the model's history sees the injection, as it would in
  reality) and runs every detector setting. The chosen setting is the one with the highest
  mean recall over patterns whose alert rate outside injections stays within the alert budget.
- **Evaluation:** fresh replicates in the rest of the test window, scored once, for the chosen
  setting and the T016 default.

Detectors: the model-based detector (T016) and a **rolling same-hour z-score**: each reading
against the mean and standard deviation of the same hour on the previous 14 days. Both group
events with the same hysteresis rules and get the same signatures, so only the score differs.

    uv run python -m wattwise.ml.benchmark --data ../data/processed/bdg2/cleaned \
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.ml.detection import (
    ROLLING_DAYS,
    ROLLING_MIN_DAYS,
    Calibration,
    Detector,
    DetectorConfig,
    adaptive_scores,
    calibrate,
    detect,
    rolling_same_hour,
)
from wattwise.ml.features import build_features
from wattwise.ml.registry import (
    DEFAULT_ROOT,
    NO_VALIDATION_WINDOW,
    RegistryError,
    current,
    load,
    verify,
)
from wattwise.ml.signatures import Signature, SignatureConfig, classify
from wattwise.ml.splits import Chronological, SplitConfig

FloatArray = npt.NDArray[np.float64]

BENCHMARK_VERSION: Final = "1"
DEFAULT_OUTPUT: Final = Path("../data/processed/benchmark")
DEFAULT_REPLICATES: Final = 12
DEFAULT_SEED: Final = 0
#: Alerts outside injected windows per meter and week. A product assumption, not a measured
#: fact: about one alert per meter every two weeks. The owner can change it.
DEFAULT_ALERT_BUDGET: Final = 0.5
#: Readings before a window that features (4 weeks) and pre-event references (4 weeks) use.
HISTORY_MARGIN: Final = timedelta(weeks=5)
EDGE_MARGIN: Final = timedelta(hours=24)  # injections start and end this far inside a window
LABEL: Final = "synthetic benchmark: injected anomalies on real BDG2 readings"
#: Alert rates at which the detectors' best tuning recall is compared like for like.
RATE_LIMITS: Final = (0.2, 0.3, 0.5, 1.0)
RATE_LABELS: Final = tuple(f"{limit:g}" for limit in RATE_LIMITS)
RULE: Final = (
    "Keep the model-based detector only if, with both detectors tuned to the same alert "
    "budget, its mean recall over patterns on the evaluation window is higher than the "
    "rolling z-score's, and it stays within the budget in tuning and in evaluation."
)
#: The rule as first written. It checked the budget in tuning only, so a detector whose
#: alert rate doubles out of season could pass. Reported for transparency (D030).
FIRST_RULE: Final = "higher evaluation recall, and within the budget in tuning only"


class Pattern(StrEnum):
    SPIKE = "spike"
    SUSTAINED = "sustained"
    LONG_SUSTAINED = "long_sustained"
    OVERNIGHT = "overnight"
    DRIFT = "drift"
    FLATLINE = "flatline"
    DROPOUT = "dropout"


@dataclass(frozen=True)
class PatternSpec:
    hours: int
    magnitude: float  # a share of the meter's level (its median reading in calibration)
    signature: Signature  # the signature a correct classification gives
    description: str


PATTERNS: Final[Mapping[Pattern, PatternSpec]] = {
    Pattern.SPIKE: PatternSpec(2, 1.0, Signature.SPIKE, "+100% of the meter's level for 2 h"),
    Pattern.SUSTAINED: PatternSpec(72, 0.3, Signature.SUSTAINED, "+30% for 3 days"),
    Pattern.LONG_SUSTAINED: PatternSpec(336, 0.3, Signature.SUSTAINED, "+30% for 14 days"),
    Pattern.OVERNIGHT: PatternSpec(
        168, 0.3, Signature.OVERNIGHT_EXCESS, "+30% in local night hours, on 7 nights"
    ),
    Pattern.DRIFT: PatternSpec(168, 0.5, Signature.DRIFT, "a ramp from 0 to +50% over 7 days"),
    Pattern.FLATLINE: PatternSpec(24, 0.0, Signature.FLATLINE, "the first reading repeated 24 h"),
    Pattern.DROPOUT: PatternSpec(30, 0.0, Signature.DATA_FAULT, "zero readings for 30 h"),
}


#: Settings tried in tuning, for both detectors. The rolling z-score has no pre-event reference.
GRID: Final = tuple(
    {"z_on": z_on, "z_off": z_off, "min_hours": hours}
    for z_on, z_off, hours in itertools.product((4.0, 5.0, 6.0, 8.0), (2.0, 3.0), (3, 6))
)


def detector_config(detector: Detector, settings: Mapping[str, float]) -> DetectorConfig:
    horizon = {} if detector is not Detector.ROLLING_Z else {"horizon_hours": None}
    return DetectorConfig(**settings, **horizon)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Injection:
    replicate: int
    meter_id: str
    pattern: Pattern
    start: pd.Timestamp
    hours: int
    level: float

    @property
    def end(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(hours=self.hours)


# ---------------------------------------------------------------------------
# Injections
# ---------------------------------------------------------------------------


def plan(
    levels: Mapping[str, float],
    window: tuple[pd.Timestamp, pd.Timestamp],
    replicate: int,
    seed: int = DEFAULT_SEED,
) -> tuple[list[Injection], list[dict[str, Any]]]:
    """One injection per meter, patterns rotating across meters and replicates, at a seeded
    random start inside the window. Returns the injections and the (meter, pattern) pairs that
    did not fit the window."""
    rng = np.random.default_rng([seed, replicate])
    patterns = list(Pattern)
    injections, skipped = [], []
    for i, meter in enumerate(sorted(levels)):
        level = levels[meter]
        pattern = patterns[(i + replicate) % len(patterns)]
        spec = PATTERNS[pattern]
        first = window[0] + EDGE_MARGIN
        latest = window[1] - EDGE_MARGIN - pd.Timedelta(hours=spec.hours)
        if not np.isfinite(level) or level <= 0 or latest < first:
            skipped.append({"replicate": replicate, "meter_id": meter, "pattern": pattern.value})
            rng.integers(0, 2)  # keep the random stream aligned across meters
            continue
        offset = int(rng.integers(0, (latest - first) // pd.Timedelta(hours=1) + 1))
        start = first + pd.Timedelta(hours=offset)
        injections.append(Injection(replicate, meter, pattern, start, spec.hours, level))
    return injections, skipped


def inject(
    readings: pd.DataFrame,
    injections: Sequence[Injection],
    timezones: Mapping[str, str],
    night_hours: Sequence[int] = SignatureConfig().night_hours,
) -> pd.DataFrame:
    """A copy of `readings` with the injections applied. Missing readings stay missing."""
    values = readings["value"].to_numpy(dtype=float).copy()
    times = pd.DatetimeIndex(readings["timestamp"])
    meters = readings["meter_id"].astype(str).to_numpy()
    buildings = readings["building_id"].astype(str).to_numpy()
    for inj in injections:
        rows = np.flatnonzero((meters == inj.meter_id) & (times >= inj.start) & (times < inj.end))
        if rows.size == 0:
            continue
        spec = PATTERNS[inj.pattern]
        amount = spec.magnitude * inj.level
        if inj.pattern in (Pattern.SPIKE, Pattern.SUSTAINED, Pattern.LONG_SUSTAINED):
            values[rows] += amount
        elif inj.pattern is Pattern.OVERNIGHT:
            local = times[rows].tz_convert(timezones.get(buildings[rows[0]], "UTC"))
            values[rows[np.isin(local.hour, night_hours)]] += amount
        elif inj.pattern is Pattern.DRIFT:
            elapsed = np.asarray((times[rows] - inj.start) / pd.Timedelta(hours=1), dtype=float)
            values[rows] += amount * elapsed / max(spec.hours - 1, 1)
        elif inj.pattern is Pattern.FLATLINE:
            first = values[rows[0]]
            stuck = first if np.isfinite(first) else inj.level
            values[rows] = np.where(np.isnan(values[rows]), np.nan, stuck)
        else:  # dropout
            values[rows] = np.where(np.isnan(values[rows]), np.nan, 0.0)
    return readings.assign(value=values)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_injections(injections: Sequence[Injection], events: pd.DataFrame) -> list[dict[str, Any]]:
    """For each injection: whether an event of the same meter overlaps it, how soon, how much of
    it is covered, by how many events, and with which signature."""
    out = []
    for inj in injections:
        mine = events[
            (events["meter_id"] == inj.meter_id)
            & (events["start"] < inj.end)
            & (events["end"] > inj.start)
        ]
        row: dict[str, Any] = {
            "replicate": inj.replicate,
            "meter_id": inj.meter_id,
            "pattern": inj.pattern.value,
            "start": inj.start,
            "hours": inj.hours,
            "detected": bool(len(mine)),
            "latency_hours": None,
            "coverage": 0.0,
            "events": len(mine),
            "signature": None,
            "signature_match": False,
            "signature_any": False,
        }
        if len(mine):
            starts = mine["start"].where(mine["start"] > inj.start, inj.start)
            ends = mine["end"].where(mine["end"] < inj.end, inj.end)
            overlap = pd.to_timedelta(ends - starts).dt.total_seconds() / 3600
            covered = np.zeros(inj.hours, dtype=bool)
            for s, e in zip(starts, ends, strict=True):
                a = int((s - inj.start) / pd.Timedelta(hours=1))
                b = int((e - inj.start) / pd.Timedelta(hours=1))
                covered[a:b] = True
            main = mine.iloc[int(np.argmax(overlap.to_numpy()))]
            expected = PATTERNS[inj.pattern].signature.value
            row |= {
                "latency_hours": int((starts.min() - inj.start) / pd.Timedelta(hours=1)),
                "coverage": round(float(covered.mean()), 4),
                "signature": str(main["signature"]),
                "signature_match": main["signature"] == expected,
                "signature_any": any(expected in str(s).split(";") for s in mine["signatures"]),
            }
        out.append(row)
    return out


def outside_alerts(injections: Sequence[Injection], events: pd.DataFrame) -> int:
    """Events that overlap no injection of their meter."""
    if events.empty:
        return 0
    hit = np.zeros(len(events), dtype=bool)
    for inj in injections:
        hit |= (
            (events["meter_id"] == inj.meter_id)
            & (events["start"] < inj.end)
            & (events["end"] > inj.start)
        ).to_numpy()
    return int((~hit).sum())


def summarise(
    scored: Sequence[Mapping[str, Any]], alerts: int, meter_weeks: float
) -> dict[str, Any]:
    """Recall and the rest per pattern, their mean over patterns, and the outside alert rate."""
    table = pd.DataFrame(list(scored))
    per_pattern: dict[str, Any] = {}
    for pattern in Pattern:
        rows = table[table["pattern"] == pattern.value] if len(table) else table
        if not len(rows):
            continue
        found = rows[rows["detected"]]
        per_pattern[pattern.value] = {
            "injections": len(rows),
            "recall": round(float(rows["detected"].mean()), 4),
            "median_latency_hours": float(found["latency_hours"].median()) if len(found) else None,
            "mean_coverage": round(float(found["coverage"].mean()), 4) if len(found) else None,
            "mean_events_when_found": round(float(found["events"].mean()), 3)
            if len(found)
            else None,
            "signature_match": round(float(found["signature_match"].mean()), 4)
            if len(found)
            else None,
            "signature_any": round(float(found["signature_any"].mean()), 4) if len(found) else None,
        }
    recalls = [p["recall"] for p in per_pattern.values()]
    return {
        "mean_recall": round(float(np.mean(recalls)), 4) if recalls else None,
        "alerts_outside_injections": alerts,
        "alerts_per_meter_week": round(alerts / meter_weeks, 4) if meter_weeks else None,
        "patterns": per_pattern,
    }


def choose(results: Sequence[Mapping[str, Any]], budget: float) -> tuple[int, bool]:
    """The index of the setting with the highest mean recall among those within the alert
    budget (ties: fewer alerts, then grid order), and whether any setting met the budget. If
    none did, the setting with the fewest alerts."""
    within = [
        i
        for i, r in enumerate(results)
        if r["alerts_per_meter_week"] is not None and r["alerts_per_meter_week"] <= budget
    ]
    if within:
        best = max(
            within,
            key=lambda i: (results[i]["mean_recall"], -results[i]["alerts_per_meter_week"], -i),
        )
        return best, True
    return min(range(len(results)), key=lambda i: (results[i]["alerts_per_meter_week"], i)), False


# ---------------------------------------------------------------------------
# Running the benchmark
# ---------------------------------------------------------------------------


Window = tuple[pd.Timestamp, pd.Timestamp]


@dataclass(frozen=True)
class Inputs:
    readings: pd.DataFrame
    buildings: pd.DataFrame
    weather: pd.DataFrame | None
    enrichment: pd.DataFrame | None

    @property
    def timezones(self) -> dict[str, str]:
        return dict(
            zip(
                self.buildings["building_id"].astype(str),
                self.buildings["timezone"].astype(str),
                strict=True,
            )
        )


def windows(root: Path) -> tuple[Window, Window, Window]:
    """Calibration (the model's validation window), tuning (the first third of its test window)
    and evaluation (the rest), from the promoted model's split."""
    metadata = verify(current(root), root)
    split = SplitConfig.model_validate(metadata.training.split_config).time
    if not isinstance(split, Chronological) or split.validation_start is None:
        raise RegistryError(NO_VALIDATION_WINDOW)
    test_start, test_end = pd.Timestamp(split.test_start), pd.Timestamp(split.test_end)
    third = ((test_end - test_start) / 3).floor("h")
    return (
        (pd.Timestamp(split.validation_start), test_start),
        (test_start, test_start + third),
        (test_start + third, test_end),
    )


@dataclass
class Tally:
    """What one detector setting found across replicates."""

    scored: list[dict[str, Any]] = field(default_factory=list)
    alerts: int = 0


def run_replicates(
    inputs: Inputs,
    root: Path,
    window: Window,
    replicates: Sequence[int],
    settings: Mapping[Detector, Sequence[Mapping[str, float]]],
    calibration: Calibration,
    levels: Mapping[str, float],
    first_residual_time: pd.Timestamp,
    seed: int = DEFAULT_SEED,
    with_injections: bool = True,
    log: Callable[[str], None] = print,
) -> tuple[dict[tuple[Detector, int], Tally], list[dict[str, Any]], float]:
    """Run every setting of every detector on each replicate. Returns the tallies keyed by
    (detector, setting index), the injections that did not fit, and the meter-weeks observed."""
    tallies = {(d, i): Tally() for d, group in settings.items() for i in range(len(group))}
    skipped: list[dict[str, Any]] = []
    times = inputs.readings["timestamp"]
    in_window = (times >= window[0]) & (times < window[1])
    meters = int(inputs.readings.loc[in_window, "meter_id"].nunique())
    weeks = (window[1] - window[0]) / pd.Timedelta(weeks=1)
    nearby = ((times >= window[0] - HISTORY_MARGIN) & (times < window[1])).to_numpy()
    for replicate in replicates:
        started = time.perf_counter()
        injections: list[Injection] = []
        if with_injections:
            injections, missed = plan(levels, window, replicate, seed)
            skipped += missed
        data = inject(inputs.readings, injections, inputs.timezones)
        features = build_features(data, inputs.buildings, inputs.weather, inputs.enrichment)
        model = load(features, root=root).model
        subset = data[nearby]
        rows = ((subset["timestamp"] >= window[0]) & (subset["timestamp"] < window[1])).to_numpy()
        expected = model.predict(subset.drop(columns="value"), data)
        rolling_z, rolling_mean = rolling_same_hour(subset)
        adaptive_z = adaptive_scores(
            subset, expected, features["rolling_mean_168h"], first_residual_time
        )
        for detector, group in settings.items():
            for i, setting in enumerate(group):
                config = detector_config(detector, setting)
                if detector is Detector.MODEL:
                    found = detect(subset, expected, calibration, rows, config)
                elif detector is Detector.MODEL_ADAPTIVE:
                    found = detect(subset, expected, calibration, rows, config, z=adaptive_z)
                else:
                    found = detect(subset, rolling_mean, None, rows, config, z=rolling_z)
                events = classify(found, inputs.buildings, config.z_off)
                tally = tallies[(detector, i)]
                tally.scored += score_injections(injections, events)
                tally.alerts += outside_alerts(injections, events)
        seconds = time.perf_counter() - started
        log(f"  replicate {replicate}: {len(injections)} injections ({seconds:.1f} s)")
    return tallies, skipped, meters * weeks * len(replicates)


def run_benchmark(
    inputs: Inputs,
    root: Path = DEFAULT_ROOT,
    replicates: int = DEFAULT_REPLICATES,
    budget: float = DEFAULT_ALERT_BUDGET,
    seed: int = DEFAULT_SEED,
    grid: Sequence[Mapping[str, float]] = GRID,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Tune on the tuning window, evaluate once on the evaluation window, and report."""
    calibration_window, tuning_window, evaluation_window = windows(root)
    readings = inputs.readings
    features = build_features(readings, inputs.buildings, inputs.weather, inputs.enrichment)
    loaded = load(features, root=root)
    times = readings["timestamp"]
    calibration_rows = (
        (times >= calibration_window[0]) & (times < calibration_window[1])
    ).to_numpy()
    expected = loaded.model.predict(readings[calibration_rows].drop(columns="value"), readings)
    calibration = calibrate(readings, expected, calibration_rows)
    levels = {
        str(k): float(v)
        for k, v in readings[calibration_rows].groupby("meter_id")["value"].median().items()
    }

    def replicate_runs(
        window: Window,
        ids: Sequence[int],
        settings: Mapping[Detector, Sequence[Mapping[str, float]]],
        with_injections: bool = True,
    ) -> tuple[dict[tuple[Detector, int], Tally], list[dict[str, Any]], float]:
        return run_replicates(
            inputs,
            root,
            window,
            ids,
            settings,
            calibration,
            levels,
            calibration_window[0],
            seed,
            with_injections,
            log,
        )

    log(f"tuning on {_iso(tuning_window[0])} to {_iso(tuning_window[1])}")
    tuned, skipped_tuning, tuning_weeks = replicate_runs(
        tuning_window, range(replicates), {d: list(grid) for d in Detector}
    )
    tuning: dict[str, list[dict[str, Any]]] = {}
    chosen: dict[Detector, Mapping[str, float]] = {}
    met_budget: dict[str, bool] = {}
    for detector in Detector:
        results = [
            {**grid[i], **summarise(t.scored, t.alerts, tuning_weeks)}
            for i, t in ((i, tuned[(detector, i)]) for i in range(len(grid)))
        ]
        index, met = choose(results, budget)
        tuning[detector.value] = results
        chosen[detector] = grid[index]
        met_budget[detector.value] = met

    base = DetectorConfig()
    default = {"z_on": base.z_on, "z_off": base.z_off, "min_hours": base.min_hours}
    final = {d: [chosen[d], default] for d in Detector}
    log(f"evaluating on {_iso(evaluation_window[0])} to {_iso(evaluation_window[1])}")
    evaluated, skipped_evaluation, evaluation_weeks = replicate_runs(
        evaluation_window, range(replicates, 2 * replicates), final
    )
    log("evaluation window without injections")
    clean, _, clean_weeks = replicate_runs(evaluation_window, [0], final, with_injections=False)
    evaluation: dict[str, Any] = {}
    for detector in Detector:
        evaluation[detector.value] = {}
        for i, name in enumerate(("chosen", "t016_default")):
            tally = evaluated[(detector, i)]
            evaluation[detector.value][name] = {
                "settings": dict(final[detector][i]),
                **summarise(tally.scored, tally.alerts, evaluation_weeks),
                "alerts_per_meter_week_without_injections": round(
                    clean[(detector, i)].alerts / clean_weeks, 4
                ),
            }
    rolling = evaluation[Detector.ROLLING_Z.value]["chosen"]
    candidates: dict[str, dict[str, Any]] = {}
    for detector in Detector:
        if detector is Detector.ROLLING_Z:
            continue
        chosen_result = evaluation[detector.value]["chosen"]
        better = bool(
            chosen_result["mean_recall"] is not None
            and rolling["mean_recall"] is not None
            and chosen_result["mean_recall"] > rolling["mean_recall"]
        )
        within = (
            chosen_result["alerts_per_meter_week"] is not None
            and chosen_result["alerts_per_meter_week"] <= budget
        )
        candidates[detector.value] = {
            "keep": better and met_budget[detector.value] and within,
            "higher_recall_than_rolling_z": better,
            "within_budget_in_tuning": met_budget[detector.value],
            "within_budget_on_evaluation": within,
            "first_rule_result": better and met_budget[detector.value],
        }
    keep = candidates[Detector.MODEL.value]["keep"]
    return {
        "label": LABEL,
        "benchmark_version": BENCHMARK_VERSION,
        "model_version": loaded.metadata.version,
        "windows_utc": {
            "calibration": [_iso(t) for t in calibration_window],
            "tuning": [_iso(t) for t in tuning_window],
            "evaluation": [_iso(t) for t in evaluation_window],
        },
        "replicates_per_window": replicates,
        "seed": seed,
        "alert_budget_per_meter_week": budget,
        "patterns": {
            p.value: {
                "hours": s.hours,
                "magnitude": s.magnitude,
                "expected_signature": s.signature.value,
                "description": s.description,
            }
            for p, s in PATTERNS.items()
        },
        "rolling_z": {"days": ROLLING_DAYS, "min_days": ROLLING_MIN_DAYS},
        "skipped_injections": {"tuning": skipped_tuning, "evaluation": skipped_evaluation},
        "tuning": tuning,
        "chosen": {d.value: dict(chosen[d]) for d in Detector},
        "budget_met_in_tuning": met_budget,
        "evaluation": evaluation,
        "best_tuning_recall_within_alert_rate": {
            detector.value: {
                f"{limit:g}": _best_within(tuning[detector.value], limit) for limit in RATE_LIMITS
            }
            for detector in Detector
        },
        "decision": {
            "keep_model_detector": keep,
            "rule": RULE,
            "first_rule_result": candidates[Detector.MODEL.value]["first_rule_result"],
            "first_rule": FIRST_RULE,
            "model_within_budget_on_evaluation": candidates[Detector.MODEL.value][
                "within_budget_on_evaluation"
            ],
            "candidates": candidates,
        },
    }


def to_markdown(report: Mapping[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "—" if value is None else f"{value:.0%}"

    w = report["windows_utc"]
    lines = [
        "# Detector benchmark (T018)",
        "",
        f"**{report['label']}.** Alerts outside injections are an upper bound on false alerts: "
        "real data has its own, unlabelled anomalies.",
        "",
        f"- Model `{report['model_version']}`; {report['replicates_per_window']} replicates per "
        f"window, one injection per meter each; seed {report['seed']}",
        f"- Calibration {w['calibration'][0]} to {w['calibration'][1]}; tuning {w['tuning'][0]} "
        f"to {w['tuning'][1]}; evaluation {w['evaluation'][0]} to {w['evaluation'][1]}",
        f"- Alert budget: {report['alert_budget_per_meter_week']} alerts per meter-week outside "
        "injections",
        "",
        "## Tuning",
        "",
        "| Detector | z_on | z_off | Min hours | Mean recall | Alerts per meter-week |",
        "|---|---|---|---|---|---|",
    ]
    for detector, rows in report["tuning"].items():
        for r in rows:
            lines.append(
                f"| {detector} | {r['z_on']:g} | {r['z_off']:g} | {r['min_hours']:g} | "
                f"{pct(r['mean_recall'])} | {r['alerts_per_meter_week']} |"
            )
    chosen = "; ".join(
        f"{d}: z_on {s['z_on']:g}, z_off {s['z_off']:g}, min hours {s['min_hours']:g}"
        + ("" if report["budget_met_in_tuning"][d] else " (budget NOT met)")
        for d, s in report["chosen"].items()
    )
    lines += [
        "",
        f"Chosen: {chosen}",
        "",
        "## Evaluation (scored once)",
        "",
        "| Detector | Setting | Mean recall | Alerts per meter-week | Without injections |",
        "|---|---|---|---|---|",
    ]
    for detector, by_setting in report["evaluation"].items():
        for name, r in by_setting.items():
            lines.append(
                f"| {detector} | {name} | {pct(r['mean_recall'])} | "
                f"{r['alerts_per_meter_week']} | {r['alerts_per_meter_week_without_injections']} |"
            )
    detectors = list(report["evaluation"])
    lines += [
        "",
        "Recall per pattern, chosen settings (signature match in brackets):",
        "",
        "| Pattern | Injected | " + " | ".join(detectors) + " |",
        "|---|---|" + "---|" * len(detectors),
    ]
    for pattern in report["patterns"]:
        found = [report["evaluation"][d]["chosen"]["patterns"].get(pattern, {}) for d in detectors]
        cells = [f"{pct(f.get('recall'))} ({pct(f.get('signature_match'))})" for f in found]
        lines.append(f"| {pattern} | {found[0].get('injections', 0)} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Best tuning recall within an alert rate (alerts per meter-week):",
        "",
        "| Detector | " + " | ".join(f"<= {k}" for k in RATE_LABELS) + " |",
        "|---|" + "---|" * len(RATE_LABELS),
    ]
    for detector, best in report["best_tuning_recall_within_alert_rate"].items():
        lines.append(f"| {detector} | " + " | ".join(pct(best[k]) for k in RATE_LABELS) + " |")
    decision = report["decision"]
    lines += ["", f"Rule: {decision['rule']}", ""]
    for name, result in decision["candidates"].items():
        verdict = "yes" if result["keep"] else "no"
        lines.append(
            f"- **{name}: keep {verdict}.** Higher recall than rolling-z: "
            f"{'yes' if result['higher_recall_than_rolling_z'] else 'no'}; within the budget in "
            f"tuning: {'yes' if result['within_budget_in_tuning'] else 'no'}; in evaluation: "
            f"{'yes' if result['within_budget_on_evaluation'] else 'no'}."
        )
    lines += [
        "",
        f"For the static model detector, the first rule ({decision['first_rule']}) would have "
        f"said {'yes' if decision['first_rule_result'] else 'no'}.",
    ]
    return "\n".join(lines) + "\n"


def _best_within(results: Sequence[Mapping[str, Any]], limit: float) -> float | None:
    """The best tuning recall among settings at or below an alert rate; None if none is."""
    recalls = [
        r["mean_recall"]
        for r in results
        if r["alerts_per_meter_week"] is not None and r["alerts_per_meter_week"] <= limit
    ]
    return max(recalls) if recalls else None


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path.exists() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.benchmark",
        description="Benchmark the detectors on anomalies injected into prepared data.",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--alert-budget", type=float, default=DEFAULT_ALERT_BUDGET)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    try:
        inputs = Inputs(
            readings=pd.read_parquet(args.data / "readings.parquet"),
            buildings=pd.read_parquet(args.data / "buildings.parquet"),
            weather=_read(args.data / "weather.parquet"),
            enrichment=_read(args.enrichment) if args.enrichment else None,
        )
        report = run_benchmark(inputs, args.root, args.replicates, args.alert_budget, args.seed)
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "benchmark.json").write_bytes(
        (json.dumps(report, indent=2, allow_nan=False, default=str) + "\n").encode("utf-8")
    )
    text = to_markdown(report)
    (args.output / "benchmark.md").write_bytes(text.encode("utf-8"))
    print(text)
    for name in ("benchmark.json", "benchmark.md"):
        print(f"{name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
