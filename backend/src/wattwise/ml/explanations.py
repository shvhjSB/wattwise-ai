"""Evidence and plain-language explanations for every alert (docs/DETECTION.md, D034).

Each detected event gets an evidence bundle and a short explanation:
- **what was compared:** the event's readings against the detector's baseline (for the default
  rolling z-score, the same hour on the previous 14 days)
- **model context:** the model's expected consumption under the observed conditions, with its
  rolling 90% interval (T019), and how often that interval held over the detection window
- **persistence and pattern:** duration, flagged hours, the signature and its evidence (T017)
- **influences:** the largest contributions to the model's expected value (LightGBM TreeSHAP,
  in kWh). These describe how the model arrives at its expectation: associations, not causes
- **things to check:** hypotheses for a person to verify, by signature

Wording rules (tested): no sentence states a cause, calls an event waste, or claims certainty.
Without contributions (another model family, or a failure) the explanation is still produced,
without the influences section.

    uv run python -m wattwise.ml.explanations --data ../data/processed/bdg2/cleaned \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.ml.detection import Detector, Run, run_detection
from wattwise.ml.features import FEATURES
from wattwise.ml.fullscale import downstream_inputs
from wattwise.ml.impact import estimate_impact
from wattwise.ml.intervals import coverage, rolling_bounds, usable_level
from wattwise.ml.registry import DEFAULT_ROOT, NoModelError, RegistryError
from wattwise.ml.scale import quality_mask
from wattwise.ml.signatures import DESCRIPTIONS, METER_PROBLEMS, Signature

FloatArray = npt.NDArray[np.float64]

EXPLANATIONS_VERSION: Final = "1"
INTERVAL_ALPHA: Final = 0.1  # the model interval shown with each alert: nominal 90%
TOP_INFLUENCES: Final = 5
DEFAULT_OUTPUT: Final = Path("../data/processed/detection/explanations")
#: Words an explanation must never use: they state causes, certainty or confirmed waste.
FORBIDDEN: Final = (
    "because",
    "caused",
    "due to",
    "the cause",
    "the reason",
    "proves",
    "proven",
    "confirmed",
    "definitely",
    "certainly",
    "waste",
)
BASELINES: Final = {
    Detector.ROLLING_Z: "its level at the same hour on the previous 14 days",
    Detector.MODEL: "the model's expected consumption",
    Detector.MODEL_ADAPTIVE: "the model's expected consumption",
}
#: Things to check, by signature and direction. Phrased as checks, never as findings.
CHECKS: Final[Mapping[Signature, Mapping[str, str]]] = {
    Signature.DATA_FAULT: {
        "any": "Check the meter and its data feed (logger, wiring, unit settings) before treating "
        "these readings as consumption.",
    },
    Signature.FLATLINE: {
        "any": "Check whether the meter or logger is stuck, or reporting estimated values.",
    },
    Signature.SPIKE: {
        "high": "Check for a short event such as equipment start-up, testing, or a data glitch.",
        "low": "Check for a short interruption, such as a brief shutdown or a data glitch.",
    },
    Signature.OVERNIGHT_EXCESS: {
        "any": "Check whether equipment, lighting or HVAC ran outside occupied hours.",
    },
    Signature.DRIFT: {
        "high": "Check for gradual changes, such as degrading equipment, setpoint changes or "
        "growing occupancy.",
        "low": "Check for gradual changes, such as equipment being retired or falling occupancy.",
    },
    Signature.SUSTAINED: {
        "high": "Check for schedule changes, events, occupancy changes, or equipment left on.",
        "low": "Check for closures, holidays, equipment shutdowns, or a partial meter outage.",
    },
    Signature.UNCLASSIFIED: {
        "any": "Compare with building records for the period (occupancy, events, maintenance).",
    },
}
DERIVED_COLUMNS: Final = {
    "log_scale": "the meter's recent level (log of the past week's mean)",
    "profile_ratio": "the meter's usual consumption at this hour of the week",
}
_DESCRIPTIONS: Final = {f.name: f.description for f in FEATURES}


def check_for(signature: str, direction: str) -> str:
    options = CHECKS[Signature(signature)]
    return options.get(direction, options.get("any", ""))


def describe_feature(name: str) -> str:
    return DERIVED_COLUMNS.get(name) or _DESCRIPTIONS.get(name, name)


def wording_problems(text: str) -> list[str]:
    """Forbidden phrases found in `text` (case-insensitive)."""
    lowered = text.lower()
    return [word for word in FORBIDDEN if word in lowered]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _hours(start: pd.Timestamp, hours: int) -> str:
    return f"{hours} h from {start:%Y-%m-%d %H:%M} UTC"


def _number(value: float | None, unit: str = "kWh") -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:,.0f} {unit}" if abs(value) >= 10 else f"{value:,.1f} {unit}"


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.floating):
        return _finite(float(value))
    if isinstance(value, np.integer):
        return int(value)
    return value


def explain(
    run: Run,
    readings: pd.DataFrame,
    features: pd.DataFrame,
    top: int = TOP_INFLUENCES,
) -> list[dict[str, Any]]:
    """An evidence bundle and explanation for every event of `run`, in event order.

    The intervals are the ones `wattwise.ml.intervals` reports: calibrated on quality rows only
    (D035) and only where the recent level is a usable scale (D041). With `top=0` the
    influences (TreeSHAP, the slow part at full scale) are not computed."""
    model = run.model.model
    times = readings["timestamp"]
    since = (times >= run.calibration_window[0]).to_numpy()
    part = readings[since]
    predicted_part = model.predict(part.drop(columns="value"), readings)
    level = features["rolling_mean_168h"].reindex(part.index).to_numpy(dtype=float)
    level = usable_level(part, level, *run.calibration_window)
    lower, upper = rolling_bounds(
        part, predicted_part.to_numpy(dtype=float), level, INTERVAL_ALPHA,
        first_score_time=run.calibration_window[0], usable=quality_mask(readings)[since],
    )  # fmt: skip
    window = (
        (part["timestamp"] >= run.detection_window[0])
        & (part["timestamp"] < run.detection_window[1])
    ).to_numpy()
    held, _ = coverage(part["value"].to_numpy(dtype=float)[window], lower[window], upper[window])
    bounds = pd.DataFrame(
        {"expected": predicted_part.to_numpy(dtype=float), "lower": lower, "upper": upper},
        index=part.index,
    )
    position = pd.Series(
        readings.index, index=pd.MultiIndex.from_frame(readings[["meter_id", "timestamp"]])
    )
    interval_note = {
        "nominal": 1 - INTERVAL_ALPHA,
        "measured_coverage_in_detection_window": None if held is None else round(held, 4),
    }
    bundles = []
    for i, event in enumerate(run.events.itertuples(index=False)):
        hours = run.detection.hours[run.detection.hours["event"] == i]
        keys = pd.MultiIndex.from_arrays(
            [np.full(len(hours), event.meter_id), pd.DatetimeIndex(hours["timestamp"])]
        )
        rows = readings.loc[position.reindex(keys).dropna().astype("int64").to_numpy()]
        bundles.append(
            _bundle(run, event, hours, rows, bounds, features, interval_note, model, top)
        )
    return bundles


def _bundle(
    run: Run,
    event: Any,
    hours: pd.DataFrame,
    rows: pd.DataFrame,
    bounds: pd.DataFrame,
    features: pd.DataFrame,
    interval_note: Mapping[str, Any],
    model: Any,
    top: int,
) -> dict[str, Any]:
    actual = rows["value"].to_numpy(dtype=float)
    context = bounds.reindex(rows.index)
    expected = context["expected"].to_numpy(dtype=float)
    lower, upper = context["lower"].to_numpy(dtype=float), context["upper"].to_numpy(dtype=float)
    both = np.isfinite(actual) & np.isfinite(expected)
    boxed = np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
    baseline = hours["baseline"].to_numpy(dtype=float)
    observed = hours["value"].to_numpy(dtype=float)
    compared = np.isfinite(observed) & np.isfinite(baseline)
    evidence = json.loads(event.evidence)
    influences, note = _influences(model, rows, features, top)
    impact = estimate_impact(actual, upper)  # T021: kWh above the upper bound, potential only
    meter_problem = Signature(event.signature) in METER_PROBLEMS  # D029: not consumption
    bundle: dict[str, Any] = {
        "event": {
            "meter_id": event.meter_id,
            "building_id": event.building_id,
            "direction": event.direction,
            "start": f"{event.start:%Y-%m-%dT%H:%M:%SZ}",
            "end": f"{event.end:%Y-%m-%dT%H:%M:%SZ}",
            "duration_hours": int(event.duration_hours),
            "flagged_hours": int(event.flagged_hours),
            "missing_hours": int(event.missing_hours),
            "peak_time": f"{event.peak_time:%Y-%m-%dT%H:%M:%SZ}",
            "peak_z": float(event.peak_z),
        },
        "detector": {
            "name": run.detector.value,
            "baseline": BASELINES[run.detector],
            "observed_kwh": float(observed[compared].sum()),
            "baseline_kwh": float(baseline[compared].sum()),
            "hours_compared": int(compared.sum()),
        },
        "model": {
            "version": run.model.metadata.version,
            "observed_kwh": float(actual[both].sum()) if both.any() else None,
            "expected_kwh": float(expected[both].sum()) if both.any() else None,
            "hours_with_expectation": int(both.sum()),
            "interval": dict(interval_note),
            "hours_above_upper_bound": int((actual[boxed] > upper[boxed]).sum()),
            "hours_below_lower_bound": int((actual[boxed] < lower[boxed]).sum()),
            "hours_with_interval": int(boxed.sum()),
            "agrees_with_detector": None,
        },
        "signature": {
            "primary": event.signature,
            "all": str(event.signatures).split(";"),
            "description": DESCRIPTIONS[Signature(event.signature)],
            "evidence": evidence,
        },
        "influences": influences,
        "influences_note": note,
        "impact": {
            "status": impact.status.value,
            "meter_problem": meter_problem,
            # A meter or data problem is never presented as consumption (D029, D040): its kWh
            # above the bound is kept, apart, and is not a potential excess.
            "potential_excess_kwh": None if meter_problem else impact.excess_kwh,
            "kwh_above_bound_not_counted": impact.excess_kwh if meter_problem else None,
            "hours_with_interval": impact.hours_with_interval,
            "hours_above_upper_bound": impact.hours_above_upper_bound,
            "cost": impact.cost,
            "currency": impact.currency,
            "carbon_kg": impact.carbon_kg,
        },
        "check": check_for(event.signature, event.direction),
    }
    model_view = bundle["model"]
    if model_view["hours_with_interval"]:
        outside = model_view[
            "hours_above_upper_bound" if event.direction == "high" else "hours_below_lower_bound"
        ]
        model_view["agrees_with_detector"] = bool(outside > 0)
    bundle["explanation"] = render(bundle)
    finite: dict[str, Any] = _finite(bundle)
    return finite


def _influences(
    model: Any, rows: pd.DataFrame, features: pd.DataFrame, top: int
) -> tuple[list[dict[str, Any]], str]:
    if top <= 0:
        return [], "Influences were not computed for this run."
    try:
        contributions = model.contributions(rows)
    except Exception as exc:  # the explanation must not fail with its optional part
        return [], f"Influences unavailable: {type(exc).__name__}."
    if contributions is None:
        return [], "Influences unavailable for this model family."
    if contributions.empty:
        return [], "The model had no expected value for these hours."
    mean = contributions.drop(columns="bias").mean()
    order = mean.abs().sort_values(ascending=False, kind="stable").index[:top]
    values = features.reindex(contributions.index)
    out = []
    for name in order:
        value = (
            float(values[name].mean()) if name in values.columns and values[name].notna().any()
            else None
        )  # fmt: skip
        out.append(
            {
                "feature": name,
                "description": describe_feature(name),
                "mean_value": value,
                "mean_contribution_kwh": round(float(mean[name]), 3),
            }
        )
    return out, (
        "Contributions to the model's expected value (LightGBM TreeSHAP, per hour, averaged over "
        "the event). They show how the model arrives at its expectation: associations, not causes."
    )


def render(bundle: Mapping[str, Any]) -> str:
    """The plain-language explanation of a bundle."""
    e, d, m, s = bundle["event"], bundle["detector"], bundle["model"], bundle["signature"]
    way = "above" if e["direction"] == "high" else "below"
    start = pd.Timestamp(e["start"])
    lines = [
        f"{e['meter_id']}: consumption was {way} {d['baseline']} for "
        f"{_hours(start, e['duration_hours'])} ({e['flagged_hours']} flagged hours, peak score "
        f"{e['peak_z']:.1f}). Recorded {_number(d['observed_kwh'])} against "
        f"{_number(d['baseline_kwh'])} for the comparison.",
        f"Pattern: {s['primary'].replace('_', ' ')}. {s['description']}",
    ]
    if m["expected_kwh"] is not None:
        coverage_note = m["interval"]["measured_coverage_in_detection_window"]
        held = f"{coverage_note:.0%}" if coverage_note is not None else "unmeasured"
        lines.append(
            f"Under the observed conditions the model expected {_number(m['expected_kwh'])} for "
            f"the {m['hours_with_expectation']} hours it could estimate; "
            f"{_number(m['observed_kwh'])} was recorded. {m['hours_above_upper_bound']} of "
            f"{m['hours_with_interval']} hours were above the upper bound and "
            f"{m['hours_below_lower_bound']} below the lower bound of its "
            f"{m['interval']['nominal']:.0%} interval (it held for {held} of hours in this "
            "detection window)."
        )
        outside = (
            m["hours_above_upper_bound"]
            if e["direction"] == "high"
            else m["hours_below_lower_bound"]
        )
        if m["hours_with_interval"] and outside == 0:
            lines.append(
                "The model, which accounts for weather and the calendar, found every hour within "
                "its interval: the deviation may reflect conditions the comparison does not see."
            )
        impact = bundle.get("impact")
        if impact is not None and (impact["potential_excess_kwh"] or 0) > 0:
            lines.append(
                f"Potential excess above the upper bound: {_number(impact['potential_excess_kwh'])}"
                " (an estimate from the interval, not a verified figure)."
            )
    else:
        lines.append("The model had no expected value for these hours.")
    if bundle["influences"]:
        parts = []
        for item in bundle["influences"][:3]:
            sign = "+" if item["mean_contribution_kwh"] >= 0 else ""
            parts.append(
                f"{item['feature']} ({sign}{item['mean_contribution_kwh']:.1f} kWh per hour)"
            )
        lines.append(
            "Largest influences on the model's expected value, which are associations within the "
            "model and not causes: " + ", ".join(parts) + "."
        )
    lines.append(f"Possible explanations to check: {bundle['check']}")
    lines.append("This is an anomaly to investigate, not a finding about energy use.")
    return " ".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def to_markdown(bundles: Sequence[Mapping[str, Any]], limit: int = 20) -> str:
    lines = [
        "# Alert explanations (T020)",
        "",
        f"{len(bundles)} events, each with an evidence bundle in explanations.json. The "
        f"{min(limit, len(bundles))} longest:",
        "",
    ]
    ranked = sorted(bundles, key=lambda b: -b["event"]["duration_hours"])[:limit]
    for b in ranked:
        lines += [f"- {b['explanation']}", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.explanations",
        description="Detect events and write an evidence bundle and explanation for each.",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument(
        "--store", type=Path, help="T042 feature store: read full-scale inputs from it"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--detector", type=Detector, choices=list(Detector), default=Detector.ROLLING_Z
    )
    parser.add_argument(
        "--no-influences",
        action="store_true",
        help="skip the TreeSHAP influences (the slow part at full scale)",
    )
    args = parser.parse_args(argv)
    try:
        readings, buildings, features = downstream_inputs(
            args.data, args.enrichment, args.store, args.root
        )
        run = run_detection(readings, buildings, features, args.root, detector=args.detector)
        bundles = explain(run, readings, features, top=0 if args.no_influences else TOP_INFLUENCES)
    except NoModelError as exc:
        print(f"error: {exc} Train and promote one first.", file=sys.stderr)
        return 1
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    problems = [p for b in bundles for p in wording_problems(b["explanation"])]
    if problems:
        print(f"error: forbidden wording in explanations: {sorted(set(problems))}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {"explanations_version": EXPLANATIONS_VERSION, "events": bundles}
    (args.output / "explanations.json").write_bytes(
        (json.dumps(payload, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    (args.output / "explanations.md").write_bytes(to_markdown(bundles).encode("utf-8"))
    print(f"{len(bundles)} events explained -> {args.output}")
    for name in ("explanations.json", "explanations.md"):
        print(f"  {name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
