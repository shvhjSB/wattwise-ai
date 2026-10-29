"""Analyse one uploaded dataset: expected consumption and alerts (D048, T026).

Unlike `run_detection`, which detects in the model's own test window, this analyses whatever
period the uploaded readings cover:

- **Alerts** come from the default detector (D030), the rolling same-hour z-score, which needs
  only the readings themselves (14 days of history per hour before it can score). Events are
  classified into signatures as usual. No model is involved, so alerts never depend on whether a
  model is available.
- **Expected consumption** comes from the promoted model (`CURRENT`, the evaluation model,
  D039/D048), with features built from the uploaded readings, buildings and (optional) weather.
  The ERA5 enrichment is not available for uploads, so those features are missing, and so are
  holidays for sites the model does not know. The model was trained on BDG2 buildings; for an
  uploaded building its expectation is **an extrapolation that has not been validated**. Its lag
  features need history, so a meter's first days (251 hours on the synthetic sample) have no
  expectation. Without a model, the analysis still returns the alerts and says why there are no
  predictions.

Nothing here is stored, and nothing is retrained.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wattwise.ml.detection import (
    DETECTOR_DEFAULTS,
    Detector,
    DetectorConfig,
    detect,
    rolling_same_hour,
)
from wattwise.ml.features import build_features
from wattwise.ml.registry import RegistryError, load

PREDICTION_NOTE = (
    "Expected consumption from a model trained on BDG2 buildings. For an uploaded building it is "
    "an extrapolation that has not been validated, without the ERA5 weather enrichment, and "
    "without holidays for unknown sites."
)


@dataclass(frozen=True)
class Analysis:
    expected: pd.Series | None  # indexed like the readings; None without a model
    model_version: str | None
    prediction_note: str
    events: pd.DataFrame
    detector: Detector


def analyze(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    weather: pd.DataFrame | None,
    root: Path,
) -> Analysis:
    """Alerts for every reading of `readings` and, if a model is promoted, the expectation."""
    from wattwise.ml.signatures import classify  # signatures imports detection

    readings = readings.reset_index(drop=True)
    config = DetectorConfig(**DETECTOR_DEFAULTS[Detector.ROLLING_Z])  # type: ignore[arg-type]
    z, baseline = rolling_same_hour(readings, floor_fraction=config.scale_floor_fraction)
    every = np.ones(len(readings), dtype=bool)
    detection = detect(readings, baseline, None, every, config, z=z)
    events = classify(detection, buildings, config.z_off)

    expected: pd.Series | None = None
    version: str | None = None
    note = PREDICTION_NOTE
    try:
        features = build_features(readings, buildings, weather)
        loaded = load(features, root=root)
        expected = loaded.model.predict(readings.drop(columns="value"), readings)
        version = loaded.metadata.version
    except RegistryError as exc:  # no model promoted, or one that cannot be used
        note = f"No predictions: {type(exc).__name__}: {exc}"
    return Analysis(expected, version, note, events, Detector.ROLLING_Z)


def events_as_records(events: pd.DataFrame) -> list[dict[str, Any]]:
    """The events as JSON-ready records (UTC timestamps, evidence parsed)."""
    records = []
    for event in events.to_dict("records"):
        evidence = event["evidence"]
        records.append(
            {
                "meter_id": str(event["meter_id"]),
                "building_id": str(event["building_id"]),
                "direction": str(event["direction"]),
                "start": pd.Timestamp(event["start"]).to_pydatetime(),
                "end": pd.Timestamp(event["end"]).to_pydatetime(),
                "duration_hours": int(event["duration_hours"]),
                "flagged_hours": int(event["flagged_hours"]),
                "peak_score": float(event["peak_z"]),
                "signature": str(event["signature"]),
                "description": str(event["description"]),
                "evidence": json.loads(evidence) if isinstance(evidence, str) else evidence,
            }
        )
    return records
