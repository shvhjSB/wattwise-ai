"""Signature rules: explainable patterns for detected events (docs/DETECTION.md, D029).

Each rule looks at an event's hours, as the detector saw them: the reading, the baseline it was
compared with, and the score. A rule returns whether it matched and the measurements behind the
decision, so every label can be checked by hand. An event gets every matching signature; its
**primary** signature is the first match in this order:

1. `data_fault`: negative readings, a long run of zero readings, mostly missing hours, or a
   deviation too large to be plausible behaviour
2. `flatline`: the same non-zero reading repeated for hours (a stuck meter)
3. `spike`: a deviation of only a few hours
4. `overnight_excess`: a high event whose excess falls mostly in local night hours
5. `drift`: the deviation grows steadily through a long event
6. `sustained`: a deviation that lasts a day or more
7. `unclassified`: no rule matched

Meter problems come first, so they are never presented as consumption. Signatures name patterns,
not causes: a cause is a hypothesis for someone to check (T020).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from wattwise.data.quality import QualityThresholds
from wattwise.ml.detection import Detection

FloatArray = npt.NDArray[np.float64]

SIGNATURES_VERSION: Final = "1"
_QUALITY = QualityThresholds()


class Signature(StrEnum):
    DATA_FAULT = "data_fault"
    FLATLINE = "flatline"
    SPIKE = "spike"
    OVERNIGHT_EXCESS = "overnight_excess"
    DRIFT = "drift"
    SUSTAINED = "sustained"
    UNCLASSIFIED = "unclassified"


#: Signatures that say the meter or its data is the problem, not the building's consumption.
#: Such events never count as potential excess energy, cost or carbon (D029, D040).
METER_PROBLEMS: Final = frozenset({Signature.DATA_FAULT, Signature.FLATLINE})


#: Plain descriptions shown with each signature. They describe the pattern, never a cause.
DESCRIPTIONS: Final = {
    Signature.DATA_FAULT: "The readings look like a metering or data problem (negative values, "
    "a long run of zeros, mostly missing data, or an implausibly large deviation). Check the "
    "meter before treating this as consumption.",
    Signature.FLATLINE: "The meter repeated the same reading for many hours, as a stuck meter "
    "would. Check the meter before treating this as consumption.",
    Signature.SPIKE: "A short deviation of a few hours.",
    Signature.OVERNIGHT_EXCESS: "Most of the excess fell in local night hours, when "
    "consumption is usually at its base load.",
    Signature.DRIFT: "The deviation grew steadily during the event.",
    Signature.SUSTAINED: "Consumption stayed away from the baseline for a day or more.",
    Signature.UNCLASSIFIED: "No signature rule matched.",
}
PRECEDENCE: Final = tuple(Signature)


class SignatureConfig(BaseModel):
    """Documented, provisional thresholds. Flatline and zero-run lengths default to the data
    quality engine's (T008) so that both describe the same problem the same way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    zero_run_min_hours: int = Field(_QUALITY.zero_run_min_intervals, ge=2)
    max_missing_share: float = Field(0.5, gt=0, le=1)
    implausible_z: float = Field(50.0, gt=0)
    flatline_min_hours: int = Field(_QUALITY.flatline_min_intervals, ge=2)
    flatline_tolerance: float = Field(_QUALITY.flatline_tolerance, ge=0)
    flatline_min_share: float = Field(0.5, gt=0, le=1)
    spike_max_hours: int = Field(3, ge=1)
    night_hours: tuple[int, ...] = (22, 23, 0, 1, 2, 3, 4, 5)  # local wall-clock hours
    overnight_min_share: float = Field(0.7, gt=0, le=1)
    drift_min_hours: int = Field(72, ge=3)
    drift_min_growth: float = Field(0.5, gt=0)  # (last third - first third) / last third
    sustained_min_hours: int = Field(24, ge=1)
    sustained_min_flagged_share: float = Field(0.6, gt=0, le=1)


@dataclass(frozen=True)
class EventHours:
    """One event's hours, in order. `score` is in the event's direction (positive = deviating)."""

    direction: str
    times: pd.DatetimeIndex  # UTC
    local_hours: npt.NDArray[np.int64]
    value: FloatArray
    baseline: FloatArray
    score: FloatArray
    z_off: float


Evidence = dict[str, Any]


def data_fault(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    present = ~np.isnan(e.value)
    negatives = int((e.value[present] < 0).sum())
    zero_run = _longest_run(present & (e.value == 0))
    missing_share = float(1 - present.mean())
    peak = float(np.nanmax(e.score)) if np.isfinite(e.score).any() else float("nan")
    reasons = [
        name
        for name, hit in (
            ("negative_readings", negatives > 0),
            ("zero_run", zero_run >= c.zero_run_min_hours),
            ("mostly_missing", missing_share >= c.max_missing_share),
            ("implausible_deviation", peak >= c.implausible_z),
        )
        if hit
    ]
    return bool(reasons), {
        "reasons": reasons,
        "negative_readings": negatives,
        "longest_zero_run_hours": zero_run,
        "missing_share": round(missing_share, 3),
        "peak_z": round(peak, 3),
        "thresholds": {
            "zero_run_min_hours": c.zero_run_min_hours,
            "max_missing_share": c.max_missing_share,
            "implausible_z": c.implausible_z,
        },
    }


def flatline(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    steady = np.zeros(len(e.value), dtype=bool)
    if len(e.value) > 1:
        same = np.abs(np.diff(e.value)) <= c.flatline_tolerance  # NaN compares False
        nonzero = (e.value[1:] != 0) & (e.value[:-1] != 0)
        steady[1:] = same & nonzero
    run = _longest_run(steady) + 1 if steady.any() else 0  # n equal steps join n + 1 readings
    share = run / len(e.value) if len(e.value) else 0.0
    return run >= c.flatline_min_hours and share >= c.flatline_min_share, {
        "longest_constant_run_hours": run,
        "share_of_event": round(share, 3),
        "thresholds": {
            "flatline_min_hours": c.flatline_min_hours,
            "flatline_min_share": c.flatline_min_share,
        },
    }


def spike(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    hours = len(e.times)
    return hours <= c.spike_max_hours, {
        "duration_hours": hours,
        "thresholds": {"spike_max_hours": c.spike_max_hours},
    }


def overnight_excess(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    excess = np.clip(np.nan_to_num(e.value - e.baseline), 0.0, None)
    night = np.isin(e.local_hours, c.night_hours)
    total = float(excess.sum())
    share = float(excess[night].sum() / total) if total > 0 else 0.0
    matched = e.direction == "high" and total > 0 and share >= c.overnight_min_share
    return matched, {
        "night_share_of_excess": round(share, 3),
        "night_hours_local": list(c.night_hours),
        "thresholds": {"overnight_min_share": c.overnight_min_share},
    }


def drift(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    sign = 1.0 if e.direction == "high" else -1.0
    deviation = sign * (e.value - e.baseline)
    thirds = [_nanmean(part) for part in np.array_split(deviation, 3)]
    first, middle, last = thirds
    growth = (last - first) / last if last > 0 else float("nan")
    matched = (
        len(e.times) >= c.drift_min_hours
        and first < middle < last
        and np.isfinite(growth)
        and growth >= c.drift_min_growth
    )
    return bool(matched), {
        "mean_deviation_by_third": [round(v, 3) for v in thirds],
        "growth": round(growth, 3),
        "thresholds": {
            "drift_min_hours": c.drift_min_hours,
            "drift_min_growth": c.drift_min_growth,
        },
    }


def sustained(e: EventHours, c: SignatureConfig) -> tuple[bool, Evidence]:
    hours = len(e.times)
    flagged_share = float(np.mean(e.score >= e.z_off)) if hours else 0.0  # NaN counts as not
    matched = hours >= c.sustained_min_hours and flagged_share >= c.sustained_min_flagged_share
    return matched, {
        "duration_hours": hours,
        "flagged_share": round(flagged_share, 3),
        "thresholds": {
            "sustained_min_hours": c.sustained_min_hours,
            "sustained_min_flagged_share": c.sustained_min_flagged_share,
        },
    }


RULES: Final = {
    Signature.DATA_FAULT: data_fault,
    Signature.FLATLINE: flatline,
    Signature.SPIKE: spike,
    Signature.OVERNIGHT_EXCESS: overnight_excess,
    Signature.DRIFT: drift,
    Signature.SUSTAINED: sustained,
}


def classify_event(e: EventHours, config: SignatureConfig | None = None) -> dict[str, Any]:
    """The primary signature, all matches, and the evidence of every rule."""
    config = config or SignatureConfig()
    evidence: dict[str, Any] = {}
    matched: list[Signature] = []
    for signature, rule in RULES.items():
        hit, measured = rule(e, config)
        evidence[signature.value] = {"matched": hit, **measured}
        if hit:
            matched.append(signature)
    primary = matched[0] if matched else Signature.UNCLASSIFIED
    return {
        "signature": primary.value,
        "signatures": ";".join(s.value for s in matched) or Signature.UNCLASSIFIED.value,
        "description": DESCRIPTIONS[primary],
        "evidence": json.dumps(_finite(evidence), sort_keys=True, allow_nan=False),
    }


def classify(
    detection: Detection,
    buildings: pd.DataFrame,
    z_off: float,
    config: SignatureConfig | None = None,
) -> pd.DataFrame:
    """The detection's events with `signature`, `signatures`, `description` and `evidence`
    columns. `buildings` gives each building's time zone for local night hours."""
    config = config or SignatureConfig()
    zones = dict(
        zip(buildings["building_id"].astype(str), buildings["timezone"].astype(str), strict=True)
    )
    events = detection.events
    hours = detection.hours
    rows = []
    for i, event in enumerate(events.itertuples(index=False)):
        part = hours[hours["event"] == i]
        times = pd.DatetimeIndex(part["timestamp"])
        local = times.tz_convert(zones.get(str(event.building_id), "UTC"))
        rows.append(
            classify_event(
                EventHours(
                    direction=str(event.direction),
                    times=times,
                    local_hours=np.asarray(local.hour, dtype=np.int64),
                    value=part["value"].to_numpy(dtype=float),
                    baseline=part["baseline"].to_numpy(dtype=float),
                    score=part["score"].to_numpy(dtype=float),
                    z_off=z_off,
                ),
                config,
            )
        )
    labels = pd.DataFrame(rows, columns=["signature", "signatures", "description", "evidence"])
    return pd.concat([events.reset_index(drop=True), labels], axis=1)


def _longest_run(flags: npt.NDArray[np.bool_]) -> int:
    best = current = 0
    for flag in flags.tolist():
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def _nanmean(values: FloatArray) -> float:
    clean = values[~np.isnan(values)]
    return float(clean.mean()) if clean.size else float("nan")


def _finite(value: Any) -> Any:
    """NaN becomes None (JSON null): "not measurable", never a made-up number."""
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value
