"""Full-scale data: a quality mask, a batched float32 feature store, and full-scale baselines
(docs/EVALUATION.md, D035).

Until T042 every result came from a seeded sample of 20 meters. Here every eligible meter is
used, within this machine's memory:
- **Quality mask:** readings that should not teach a model or calibrate a detector:
  - negative readings
  - runs of at least 24 consecutive zero readings (the data-quality engine's length, T008)
  - runs of at least 24 consecutive identical non-zero readings: a whole day of one value is a
    stuck meter or filled data (such as a daily total spread over 24 hours), not hourly use
  Shorter identical runs are kept. T008 and the T017 signature flag runs from 6 hours, but on
  BDG2 many 6-23-hour runs are steady loads on coarse meters (resolution 0.1-6 kWh), so they
  are not dropped from training. The mask is policy, computed when needed; detection still sees
  every reading.
- **Feature store:** features are built per batch of meters and written as float32 parquet
  parts. A meter's features depend only on its own readings and its site's weather, so batching
  does not change them (tested).
- **Baselines** at full scale, scored on all rows and on quality-checked rows.

    uv run python -m wattwise.data.bdg2_prepare --sample-meters 0 \\
        --output ../data/processed/bdg2/cleaned-all
    uv run python -m wattwise.ml.scale features --data ../data/processed/bdg2/cleaned-all \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet
    uv run python -m wattwise.ml.scale baselines --data ../data/processed/bdg2/cleaned-all
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.data.quality import QualityThresholds
from wattwise.ml.baselines import DEFAULT_SPLIT, common_rows_comparison, default_baselines, run
from wattwise.ml.evaluation import write_report
from wattwise.ml.features import FEATURE_SET_VERSION, build_features, feature_manifest
from wattwise.ml.features import FeatureConfig as _FeatureConfig
from wattwise.ml.splits import Role, SplitConfig, make_split

BoolArray = npt.NDArray[np.bool_]

STORE_VERSION: Final = "1"
DEFAULT_STORE: Final = Path("../data/processed/features-all")
DEFAULT_BASELINES: Final = Path("../data/processed/evaluation/baselines-all")
DEFAULT_BATCH_METERS: Final = 100
KEY_COLUMNS: Final = ("timestamp", "meter_id", "building_id", "value")
_QUALITY: Final = QualityThresholds()
#: Identical non-zero readings for this long are masked from training (see the module notes).
MASK_FLATLINE_HOURS: Final = 24
#: Identifier columns as categories: at full scale, 20 million strings would take about 2.3 GB
#: and push the machine into swapping (the first full-scale baseline run took 5 hours).
#: Reports are identical either way (checked on 100 meters).
CATEGORIES: Final = {
    "meter_id": "category",
    "building_id": "category",
    "meter_type": "category",
    "unit": "category",
}


# ---------------------------------------------------------------------------
# Quality mask
# ---------------------------------------------------------------------------


def _run_lengths(member: BoolArray, continues: BoolArray) -> npt.NDArray[np.int64]:
    """For rows in order: the length of the run each member row belongs to (0 for non-members).
    `continues[i]` says row i extends the run of row i - 1."""
    starts = member & ~continues
    run_id = np.cumsum(starts)
    lengths = np.bincount(run_id[member], minlength=int(run_id.max()) + 1 if len(run_id) else 1)
    out = np.zeros(len(member), dtype=np.int64)
    out[member] = lengths[run_id[member]]
    return out


def quality_mask(
    readings: pd.DataFrame,
    zero_run_hours: int = _QUALITY.zero_run_min_intervals,
    flatline_hours: int = MASK_FLATLINE_HOURS,
    tolerance: float = _QUALITY.flatline_tolerance,
) -> BoolArray:
    """True where a reading may be used as a training target or for calibration, aligned with
    `readings`' rows. Missing readings are False."""
    order = np.lexsort((readings["timestamp"].to_numpy(), readings["meter_id"].to_numpy()))
    meters = readings["meter_id"].to_numpy()[order]
    times = readings["timestamp"].to_numpy(dtype="datetime64[us]")[order]
    values = readings["value"].to_numpy(dtype=float)[order]
    present = np.isfinite(values)
    linked = np.zeros(len(values), dtype=bool)
    if len(values) > 1:
        linked[1:] = (meters[1:] == meters[:-1]) & (
            times[1:] - times[:-1] == np.timedelta64(1, "h")
        )
    zero = present & (values == 0)
    zero_continues = np.zeros_like(zero)
    zero_continues[1:] = zero[1:] & zero[:-1] & linked[1:]
    flat = present & (values != 0)
    flat_continues = np.zeros_like(flat)
    flat_continues[1:] = (
        flat[1:] & flat[:-1] & linked[1:] & (np.abs(values[1:] - values[:-1]) <= tolerance)
    )
    bad = (
        (present & (values < 0))
        | (_run_lengths(zero, zero_continues) >= zero_run_hours)
        | (_run_lengths(flat, flat_continues) >= flatline_hours)
    )
    ok_sorted = present & ~bad
    ok = np.empty(len(values), dtype=bool)
    ok[order] = ok_sorted
    return ok


def mask_summary(readings: pd.DataFrame, ok: BoolArray) -> dict[str, Any]:
    present = readings["value"].notna().to_numpy()
    per_meter = (
        pd.DataFrame({"meter_id": readings["meter_id"].to_numpy(), "masked": present & ~ok})
        .groupby("meter_id")["masked"]
        .mean()
    )
    return {
        "readings": int(present.sum()),
        "masked": int((present & ~ok).sum()),
        "masked_share": round(int((present & ~ok).sum()) / max(int(present.sum()), 1), 4),
        "meters_with_masked_readings": int((per_meter > 0).sum()),
        "meters_over_10_percent_masked": int((per_meter > 0.1).sum()),
    }


# ---------------------------------------------------------------------------
# Feature store
# ---------------------------------------------------------------------------


def build_store(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    weather: pd.DataFrame | None,
    enrichment: pd.DataFrame | None,
    output: Path,
    batch_meters: int = DEFAULT_BATCH_METERS,
    log: Any = print,
) -> dict[str, Any]:
    """Write keys, the quality flag and float32 features in parquet parts of `batch_meters`
    meters each, with a manifest. Returns the manifest."""
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("part-*.parquet"):
        stale.unlink()
    meters = sorted(readings["meter_id"].astype(str).unique())
    parts: list[dict[str, Any]] = []
    for k in range(0, len(meters), batch_meters):
        started = time.perf_counter()
        batch = meters[k : k + batch_meters]
        rows = readings[readings["meter_id"].isin(batch)].astype(
            {"meter_id": "str", "building_id": "str"}
        )
        features = build_features(rows, buildings, weather, enrichment).astype("float32")
        table = pd.concat(
            [
                rows[list(KEY_COLUMNS)].reset_index(drop=True),
                features.reset_index(drop=True),
            ],
            axis=1,
        )
        name = f"part-{k // batch_meters:04d}.parquet"
        table.to_parquet(output / name, index=False)
        parts.append(
            {
                "file": name,
                "meters": len(batch),
                "rows": len(table),
                "sha256": sha256_of(output / name),
            }
        )
        log(
            f"  {name}: {len(batch)} meters, {len(table):,} rows "
            f"({time.perf_counter() - started:.1f} s)"
        )
    manifest = {
        "store_version": STORE_VERSION,
        "feature_set": feature_manifest(_FeatureConfig()),
        "dtype": "float32",
        "batch_meters": batch_meters,
        "meters": len(meters),
        "rows": sum(int(p["rows"]) for p in parts),
        "parts": parts,
    }
    (output / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    return manifest


def load_store(
    store: Path, columns: Sequence[str] | None = None, meters: Sequence[str] | None = None
) -> pd.DataFrame:
    """The store's rows (all parts, in order), optionally restricted to columns and meters.
    Part hashes are checked against the manifest."""
    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("feature_set", {}).get("feature_set_version") != FEATURE_SET_VERSION:
        raise ValueError("The feature store was built for another feature set; rebuild it.")
    frames = []
    for part in manifest["parts"]:
        path = store / part["file"]
        if sha256_of(path) != part["sha256"]:
            raise ValueError(f"{path} does not match its recorded SHA-256; rebuild the store.")
        frame = pd.read_parquet(path, columns=list(columns) if columns else None)
        if meters is not None:
            frame = frame[frame["meter_id"].isin(meters)]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Baselines at full scale
# ---------------------------------------------------------------------------


def full_scale_baselines(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    output: Path,
    split_config: SplitConfig = DEFAULT_SPLIT,
) -> dict[str, Any]:
    """The T012 baselines on every meter, scored on all rows and on quality-checked rows (masked
    readings set missing, for targets and history alike)."""
    results: dict[str, Any] = {}
    ok = quality_mask(readings)
    for name, data in (
        ("all_rows", readings),
        ("quality_rows", readings.assign(value=readings["value"].where(ok))),
    ):
        split = make_split(data, split_config, buildings)
        outcome = run(split, default_baselines(buildings))
        folder = output / name
        for report in outcome.reports:
            write_report(report, folder, report.forecaster.name)
        results[name] = {
            report.forecaster.name: {
                score.role.value: {
                    "mae": score.overall.mae,
                    "rmse": score.overall.rmse,
                    "wape": score.overall.wape,
                    "macro_mae": score.macro.mae,
                    "scored": score.overall.scored,
                    "missing_prediction": score.overall.missing_prediction,
                    "meters": score.macro.meters,
                }
                for score in report.scores
                if score.role in (Role.VALIDATION, Role.TEST)
            }
            for report in outcome.reports
        }
        results[name]["common_rows"] = common_rows_comparison(outcome)
    results["quality_mask"] = mask_summary(readings, ok)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_bytes(
        (json.dumps(results, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    return results


def _read(path: Path) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path.exists() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.scale",
        description="Full-scale feature store, quality mask and baselines.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features", help="build the float32 feature store")
    features.add_argument("--data", type=Path, required=True)
    features.add_argument("--enrichment", type=Path)
    features.add_argument("--store", type=Path, default=DEFAULT_STORE)
    features.add_argument("--batch-meters", type=int, default=DEFAULT_BATCH_METERS)
    baselines = commands.add_parser("baselines", help="score the baselines on every meter")
    baselines.add_argument("--data", type=Path, required=True)
    baselines.add_argument("--output", type=Path, default=DEFAULT_BASELINES)
    args = parser.parse_args(argv)
    try:
        # Categories keep 20 million identifiers small; batches are converted back to str.
        readings = pd.read_parquet(args.data / "readings.parquet").astype(CATEGORIES)
        buildings = pd.read_parquet(args.data / "buildings.parquet")
        if args.command == "features":
            manifest = build_store(
                readings,
                buildings,
                _read(args.data / "weather.parquet"),
                _read(args.enrichment) if args.enrichment else None,
                args.store,
                args.batch_meters,
            )
            print(f"{manifest['meters']} meters, {manifest['rows']:,} rows -> {args.store}")
            print(json.dumps(mask_summary(readings, quality_mask(readings)), indent=1))
            return 0
        result = full_scale_baselines(readings, buildings, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result["quality_mask"], indent=1))
    for name in ("all_rows", "quality_rows"):
        for forecaster, roles in result[name].items():
            if forecaster == "common_rows":
                continue
            for role, m in roles.items():
                print(
                    f"{name:12s} {forecaster:22s} {role:10s} MAE {m['mae']} WAPE {m['wape']} "
                    f"macro MAE {m['macro_mae']} meters {m['meters']} scored {m['scored']:,}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
