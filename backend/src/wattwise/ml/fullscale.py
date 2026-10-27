"""The best model at full scale (docs/EVALUATION.md, D036).

Trains on all 1,148 eligible BDG2 meters from the T042 feature store, without touching the test
window until the end:
1. **Training rows:** a seeded Bernoulli sample (SAMPLE_FRACTION) of each meter's
   quality-checked training hours. It fits in memory; validation and test use every row.
2. **Search on validation:** LightGBM, all features (the T014 "full" variant), over the SEARCH
   grid of losses and tree sizes, each with early stopping on sampled validation rows. The
   lowest validation MAE (all rows) wins. The results are written as soon as the search ends.
3. **Test, once:** the chosen model against seasonal-naive on the same rows, with T011 reports,
   per-site errors, and the sample-trained model (D026) for reference.
4. **Unseen buildings and sites:** the chosen settings under the T014 building and site
   holdouts.
5. **Production refit** on the training and validation windows with the tree count found by
   early stopping, scored once on test.
6. **Adoption (fixed before the run):** the refit is saved and, with `--promote`, promoted only
   if the validation-chosen model beats seasonal-naive on the test rows both predict.

Models train one at a time with THREADS cores each; two concurrent fits were tried and dropped
(they thrashed this machine's 15.3 GB RAM instead of using idle CPU, since each fit holds its own
copy of the input matrix) — see docs/EVALUATION.md.

    uv run python -m wattwise.ml.fullscale --store ../data/processed/features-all \\
        --data ../data/processed/bdg2/cleaned-all --promote
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.ml.baselines import DEFAULT_SPLIT
from wattwise.ml.evaluation import Forecaster, compute_metrics, evaluate, fingerprint, write_report
from wattwise.ml.features import FEATURE_SET_VERSION, feature_names
from wattwise.ml.models import HOLDOUTS, Family, FeatureModel, Variant
from wattwise.ml.registry import (
    DEFAULT_ROOT,
    NO_VALIDATION_WINDOW,
    NoModelError,
    RegistryError,
    Trained,
    TrainingInfo,
    current,
    load,
    promote,
    read_inputs,
    save,
    verify,
)
from wattwise.ml.scale import CATEGORIES, DEFAULT_STORE, KEY_COLUMNS, quality_mask
from wattwise.ml.splits import Chronological, Holdout, Role, Split, SplitConfig, make_split

IntArray = npt.NDArray[np.int64]

FULLSCALE_VERSION: Final = "1"
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/fullscale")
SAMPLE_FRACTION: Final = 0.25
SAMPLE_SEED: Final = 0
STOPPING_ROUNDS: Final = 100
THREADS: Final = 8  # results are reproducible for a fixed thread count on the same machine
PREDICT_CHUNK: Final = 500_000
BASE_SETTINGS: Final[Mapping[str, float | str]] = {
    "learning_rate": 0.05,
    "n_estimators": 3000,  # an upper bound; early stopping picks the count
    "min_child_samples": 100,
    "feature_fraction": 0.8,
    "n_jobs": THREADS,
}
# At 63 leaves, L1 loss needed 1,640 trees and 46,970 s to converge; at 255 leaves it needed fewer
# trees (1,384) and much less time (3,477 s) for a nearly identical validation MAE (15.283 vs
# 15.306). 63 leaves is dropped from the L1 search for that reason (docs/EVALUATION.md, T043).
SEARCH: Final = tuple(
    {**BASE_SETTINGS, "objective": objective, "num_leaves": leaves}
    for objective, leaves_tried in (
        ("regression", (63, 255)),
        ("regression_l1", (255,)),
        ("huber", (63, 255)),
    )
    for leaves in leaves_tried
)
NAIVE: Final = "seasonal-naive-1w"
#: Days of readings kept before a model's validation window when the downstream tools
#: (detectors, intervals, explanations, impact) read from the store: the rolling same-hour
#: score looks back 14 days and a long event's reference one week (T044a).
WINDOW_LEAD_DAYS: Final = 28
READING_COLUMNS: Final = ("timestamp", "meter_id", "building_id", "meter_type", "unit", "value")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_keys(store: Path) -> pd.DataFrame:
    """Every row's keys and value from the store, in store order (the row id is the index),
    with category identifiers and the canonical meter type and unit."""
    parts = json.loads((store / "manifest.json").read_text(encoding="utf-8"))["parts"]
    frames = [pd.read_parquet(store / p["file"], columns=list(KEY_COLUMNS)) for p in parts]
    keys = pd.concat(frames, ignore_index=True)
    keys["meter_type"] = "electricity"
    keys["unit"] = "kWh"
    return keys.astype(CATEGORIES)


def load_features(store: Path, ids: npt.ArrayLike) -> pd.DataFrame:
    """The float32 features of the given row ids (store order), indexed by row id. Part hashes
    and the feature-set version are checked."""
    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    if manifest["feature_set"]["feature_set_version"] != FEATURE_SET_VERSION:
        raise ValueError("The feature store was built for another feature set; rebuild it.")
    wanted = np.sort(np.asarray(ids, dtype=np.int64))
    columns = feature_names()
    frames, offset = [], 0
    for part in manifest["parts"]:
        path = store / part["file"]
        if sha256_of(path) != part["sha256"]:
            raise ValueError(f"{path} does not match its recorded SHA-256; rebuild the store.")
        rows = int(part["rows"])
        lo, hi = np.searchsorted(wanted, [offset, offset + rows])
        if hi > lo:
            local = wanted[lo:hi] - offset
            frame = pd.read_parquet(path, columns=columns).iloc[local]
            frame.index = pd.Index(wanted[lo:hi])
            frames.append(frame)
        offset += rows
    return pd.concat(frames) if frames else pd.DataFrame(columns=columns, dtype="float32")


def window_inputs(
    store: Path, data: Path, start: datetime, end: datetime
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Readings, buildings and features for [start, end) from the T042 store, shaped like
    `registry.read_inputs` returns them: canonical columns and dtypes, and one RangeIndex shared
    by readings and features.

    The features are the store's, computed on each meter's whole series, so the window's
    history features equal the full-scale ones; nothing is recomputed from the window."""
    keys = load_keys(store)
    stamps = keys["timestamp"]
    ids = np.flatnonzero(((stamps >= start) & (stamps < end)).to_numpy())
    features = load_features(store, ids)  # rows in store order, like `ids`
    readings = keys.loc[ids, list(READING_COLUMNS)].astype(
        {"meter_id": "str", "building_id": "str", "meter_type": "str", "unit": "str"}
    )
    readings.index = pd.RangeIndex(len(ids))
    features.index = pd.RangeIndex(len(ids))
    return readings, pd.read_parquet(data / "buildings.parquet"), features


def model_window_inputs(
    store: Path, data: Path, root: Path = DEFAULT_ROOT
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """`window_inputs` for what the promoted model's downstream tools need: WINDOW_LEAD_DAYS
    before its validation window (calibration) up to the end of its test window (detection)."""
    split = SplitConfig.model_validate(verify(current(root), root).training.split_config).time
    if not isinstance(split, Chronological) or split.validation_start is None:
        raise RegistryError(NO_VALIDATION_WINDOW)
    start = split.validation_start - timedelta(days=WINDOW_LEAD_DAYS)
    return window_inputs(store, data, start, split.test_end)


def downstream_inputs(
    data: Path, enrichment: Path | None, store: Path | None, root: Path = DEFAULT_ROOT
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Inputs for the downstream tools (detection, intervals, explanations, impact): built in
    memory from prepared tables (the 20-meter sample), or, with `store`, read from the T042 store
    for the promoted model's windows (full scale, where features do not fit in memory)."""
    if store is None:
        return read_inputs(data, enrichment)
    return model_window_inputs(store, data, root)


def sample_rows(candidates: npt.NDArray[np.bool_], fraction: float, seed: int) -> IntArray:
    """Row ids of a seeded Bernoulli sample of the candidate rows."""
    draw = np.random.default_rng(seed).random(len(candidates))
    return np.flatnonzero(candidates & (draw < fraction)).astype(np.int64)


def lagged(keys: pd.DataFrame, ids: npt.ArrayLike, hours: int = 168) -> pd.Series:
    """Seasonal-naive predictions: each row's meter reading `hours` earlier, NaN if missing."""
    codes = keys["meter_id"].cat.codes.to_numpy(dtype=np.int64)
    stamp = keys["timestamp"].to_numpy(dtype="datetime64[h]").astype(np.int64)
    key = codes * 10_000_000 + (stamp - stamp.min())
    lookup = pd.Index(key)
    target = np.asarray(ids, dtype=np.int64)
    position = lookup.get_indexer(pd.Index(key[target] - hours))
    values = keys["value"].to_numpy(dtype=float)
    out = np.where(position >= 0, values[np.maximum(position, 0)], np.nan)
    return pd.Series(out, index=pd.Index(target))


def predict(model: FeatureModel, keys: pd.DataFrame, ids: npt.ArrayLike) -> pd.Series:
    """Predictions for the given row ids, in chunks to bound memory."""
    target = np.asarray(ids, dtype=np.int64)
    parts = [
        model.predict(keys.loc[target[i : i + PREDICT_CHUNK]].drop(columns="value"), keys)
        for i in range(0, len(target), PREDICT_CHUNK)
    ]
    return pd.concat(parts) if parts else pd.Series(dtype=float)


def _metrics(actual: npt.ArrayLike, predicted: npt.ArrayLike) -> dict[str, Any]:
    m = compute_metrics(actual, predicted)
    return {"mae": m.mae, "rmse": m.rmse, "bias": m.bias, "wape": m.wape, "scored": m.scored}


def compare(
    keys: pd.DataFrame, ids: IntArray, model: pd.Series, naive: pd.Series
) -> dict[str, Any]:
    """The model against seasonal-naive on the rows both predicted and that have a value."""
    actual = keys["value"].to_numpy(dtype=float)[ids]
    a, b = model.reindex(ids).to_numpy(dtype=float), naive.reindex(ids).to_numpy(dtype=float)
    common = np.isfinite(actual) & np.isfinite(a) & np.isfinite(b)
    m, n = _metrics(actual[common], a[common]), _metrics(actual[common], b[common])
    return {
        "common_rows": int(common.sum()),
        "model": m,
        "seasonal_naive": n,
        "mae_reduction": None if not n["mae"] else round(1 - m["mae"] / n["mae"], 4),
    }


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rows:
    split: Split
    ok: npt.NDArray[np.bool_]  # the T042 quality mask
    roles: dict[Role, IntArray]
    train_ids: IntArray  # the seeded training sample
    stop_ids: IntArray  # the seeded early-stopping sample of validation rows


def _rows(
    keys: pd.DataFrame, split_config: SplitConfig, buildings: pd.DataFrame, fraction: float
) -> _Rows:
    """The split, and the seeded samples of quality-checked training and validation hours. Every
    command that must reproduce the T043 study's models samples through here."""
    split = make_split(keys, split_config, buildings)
    part = split.folds[0]
    ok = quality_mask(keys)
    roles = {role: np.asarray(part.positions[role], dtype=np.int64) for role in part.positions}
    finite = keys["value"].notna().to_numpy()
    in_role: dict[Role, npt.NDArray[np.bool_]] = {}
    for role in (Role.TRAIN, Role.VALIDATION):
        flags = np.zeros(len(keys), dtype=bool)
        flags[roles[role]] = True
        in_role[role] = flags
    return _Rows(
        split=split,
        ok=ok,
        roles=roles,
        train_ids=sample_rows(in_role[Role.TRAIN] & ok & finite, fraction, SAMPLE_SEED),
        stop_ids=sample_rows(in_role[Role.VALIDATION] & ok & finite, fraction, SAMPLE_SEED + 1),
    )


def run_study(
    store: Path,
    buildings: pd.DataFrame,
    output: Path,
    root: Path = DEFAULT_ROOT,
    split_config: SplitConfig = DEFAULT_SPLIT,
    search: Sequence[Mapping[str, float | str]] = SEARCH,
    holdouts: Sequence[Holdout] = HOLDOUTS,
    fraction: float = SAMPLE_FRACTION,
    stopping_rounds: int = STOPPING_ROUNDS,
    promote_if_adopted: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    started = time.perf_counter()
    keys = load_keys(store)
    rows = _rows(keys, split_config, buildings, fraction)
    split, ok, roles = rows.split, rows.ok, rows.roles
    train_ids, stop_ids = rows.train_ids, rows.stop_ids
    val_ids, test_ids = roles[Role.VALIDATION], roles[Role.TEST]
    needed = np.unique(np.concatenate([train_ids, stop_ids, val_ids, test_ids]))
    features = load_features(store, needed)
    log(
        f"{len(keys):,} rows; training sample {len(train_ids):,}; validation {len(val_ids):,}; "
        f"test {len(test_ids):,}; features loaded for {len(needed):,} rows "
        f"({time.perf_counter() - started:.0f} s)"
    )

    naive_val, naive_test = lagged(keys, val_ids), lagged(keys, test_ids)
    actual = keys["value"].to_numpy(dtype=float)
    quality_val = val_ids[ok[val_ids]]

    def fit(
        settings: Mapping[str, float | str],
        variant: Variant = Variant.FULL,
        train: IntArray = train_ids,
        stop: IntArray | None = stop_ids,
    ) -> tuple[FeatureModel, float]:
        t0 = time.perf_counter()
        model = FeatureModel(Family.LIGHTGBM, variant, settings, features)
        model.fit(
            keys.loc[train],
            validation=keys.loc[stop] if stop is not None else None,
            stopping_rounds=stopping_rounds if stop is not None else None,
        )
        return model, time.perf_counter() - t0

    def trial(settings: Mapping[str, float | str]) -> tuple[dict[str, Any], FeatureModel]:
        model, seconds = fit(settings)
        predicted = predict(model, keys, val_ids)
        scores = _metrics(actual[val_ids], predicted.reindex(val_ids).to_numpy())
        quality = _metrics(actual[quality_val], predicted.reindex(quality_val).to_numpy())
        log(
            f"  {model.name}: validation MAE {scores['mae']} (trees {model.best_iteration}, "
            f"{seconds:.0f} s)"
        )
        record = {
            "settings": dict(settings),
            "best_iteration": model.best_iteration,
            "seconds": round(seconds),
            "validation": scores,
            "validation_quality_rows": quality,
            "validation_vs_naive": compare(keys, val_ids, predicted, naive_val),
        }
        return record, model

    trials: list[dict[str, Any]] = []
    best: tuple[float, FeatureModel] | None = None
    for settings in search:
        record, model = trial(settings)
        trials.append(record)
        if record["validation"]["mae"] is not None and (
            best is None or record["validation"]["mae"] < best[0]
        ):
            best = (record["validation"]["mae"], model)
    assert best is not None
    chosen = best[1]
    chosen_settings = dict(chosen.settings)
    _checkpoint(output, "search", trials)

    conditions, _ = fit(chosen_settings, Variant.CONDITIONS)
    conditions_val = predict(conditions, keys, val_ids)
    log("  conditions variant scored on validation")

    test, report, naive_report = _score_test(
        chosen, keys, split, test_ids, naive_test, ok, buildings, root, features
    )
    write_report(report, output / "test", "chosen")
    write_report(naive_report, output / "test", NAIVE)

    # --- unseen buildings and sites ------------------------------------------------------------
    unseen = []
    building_of = keys["building_id"].astype(str).to_numpy()
    for holdout in holdouts:
        held_split = make_split(
            keys, SplitConfig(time=split_config.time, holdout=holdout), buildings
        )
        seen = ~np.isin(building_of, list(held_split.holdout))
        model, _ = fit(
            chosen_settings, train=train_ids[seen[train_ids]], stop=stop_ids[seen[stop_ids]]
        )
        h_part = held_split.folds[0]
        result: dict[str, Any] = {
            "holdout": holdout.model_dump(mode="json"),
            "held_out_buildings": len(held_split.holdout),
        }
        for role in (Role.TEST, Role.TEST_UNSEEN):
            ids = np.asarray(h_part.positions[role], dtype=np.int64)
            result[role.value] = compare(keys, ids, predict(model, keys, ids), naive_test)
        unseen.append(result)
        log(f"  {holdout.group_by} holdout scored")

    # --- production refit ----------------------------------------------------------------------
    trees = chosen.best_iteration or int(chosen_settings["n_estimators"])
    refit_settings = {**chosen_settings, "n_estimators": trees}
    refit, _ = fit(refit_settings, train=np.concatenate([train_ids, stop_ids]), stop=None)
    refit_test = predict(refit, keys, test_ids)
    test["refit"] = compare(keys, test_ids, refit_test, naive_test)

    adopted = bool(
        test["chosen"]["mae_reduction"] is not None and test["chosen"]["mae_reduction"] > 0
    )
    artifact = None
    if adopted:
        artifact = _save_refit(refit, keys, split_config, train_ids, stop_ids, refit_test, root)
        if promote_if_adopted:
            promote(artifact, root)
    summary = {
        "fullscale_version": FULLSCALE_VERSION,
        "rows": len(keys),
        "meters": int(keys["meter_id"].nunique()),
        "sample_fraction": fraction,
        "training_rows_sampled": len(train_ids),
        "early_stopping_rows": len(stop_ids),
        "threads": THREADS,
        "search": trials,
        "chosen": {
            "name": chosen.name,
            "settings": chosen_settings,
            "best_iteration": chosen.best_iteration,
        },
        "conditions_variant_validation": compare(keys, val_ids, conditions_val, naive_val),
        "test": test,
        "unseen": unseen,
        "decision": {
            "adopted": adopted,
            "rule": "Adopt (save the production refit) only if the validation-chosen model has a "
            "lower test MAE than seasonal-naive on the rows both predict.",
            "artifact": artifact,
            "promoted": bool(adopted and promote_if_adopted),
        },
        "seconds": round(time.perf_counter() - started),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "fullscale.json").write_bytes(
        (json.dumps(summary, indent=2, allow_nan=False, default=_json) + "\n").encode("utf-8")
    )
    (output / "fullscale.md").write_bytes(to_markdown(summary).encode("utf-8"))
    return summary


def _score_test(
    chosen: FeatureModel,
    keys: pd.DataFrame,
    split: Any,
    test_ids: IntArray,
    naive_test: pd.Series,
    ok: npt.NDArray[np.bool_],
    buildings: pd.DataFrame,
    root: Path,
    features: pd.DataFrame,
) -> tuple[dict[str, Any], Any, Any]:
    """The test window, scored once: the chosen model against seasonal-naive, the T011 reports,
    per-site errors and the sample-trained model (D026) for reference."""
    part = split.folds[0]
    test_pred = predict(chosen, keys, test_ids)
    test: dict[str, Any] = {
        "chosen": compare(keys, test_ids, test_pred, naive_test),
        "chosen_quality_rows": compare(keys, test_ids[ok[test_ids]], test_pred, naive_test),
    }
    report = evaluate(
        split,
        {(part.fold.name, Role.TEST): test_pred.reindex(test_ids).set_axis(test_ids)},
        Forecaster(name=chosen.name, params=chosen.params),
    )
    naive_report = evaluate(
        split,
        {(part.fold.name, Role.TEST): naive_test.reindex(test_ids).set_axis(test_ids)},
        Forecaster(name=NAIVE, params={"lag_hours": 168}),
    )
    test["per_site"] = _per_site(keys, buildings, test_ids, test_pred, naive_test)
    try:
        sample_model = load(features, root=root).model
        test["sample_trained_model"] = compare(
            keys, test_ids, predict(sample_model, keys, test_ids), naive_test
        )
        test["sample_trained_model"]["name"] = sample_model.name
    except (NoModelError, RegistryError) as exc:
        test["sample_trained_model"] = {"unavailable": str(exc)}
    return test, report, naive_report


def _checkpoint(output: Path, name: str, value: object) -> None:
    """Write a finished stage's results, so that a later failure does not lose them."""
    output.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, allow_nan=False, default=_json) + "\n"
    (output / f"{name}.json").write_bytes(text.encode("utf-8"))


def _per_site(
    keys: pd.DataFrame, buildings: pd.DataFrame, ids: IntArray, model: pd.Series, naive: pd.Series
) -> dict[str, Any]:
    site_of = dict(
        zip(buildings["building_id"].astype(str), buildings["site_id"].astype(str), strict=True)
    )
    sites = keys["building_id"].astype(str).map(site_of).to_numpy()[ids]
    out = {}
    for site in sorted(set(sites)):
        out[str(site)] = compare(keys, ids[sites == site], model, naive)
    return out


def _save_refit(
    refit: FeatureModel,
    keys: pd.DataFrame,
    split_config: SplitConfig,
    train_ids: IntArray,
    stop_ids: IntArray,
    refit_test: pd.Series,
    root: Path,
) -> str:
    """Save the production refit: trained on the training and validation windows, scored once on
    the test window. Its split has no validation window."""
    time_split = split_config.time
    assert isinstance(time_split, Chronological)
    refit_config = SplitConfig(
        time=Chronological(
            train_start=time_split.train_start,
            test_start=time_split.test_start,
            test_end=time_split.test_end,
        )
    )
    used = np.concatenate([train_ids, stop_ids])
    return _save_model(refit, keys, refit_config, used, {Role.TEST: refit_test}, root)


def _save_model(
    model: FeatureModel,
    keys: pd.DataFrame,
    split_config: SplitConfig,
    used_ids: IntArray,
    predicted: Mapping[Role, pd.Series],
    root: Path,
) -> str:
    """Save `model` with its training rows and its T011 metrics for each role in `predicted`."""
    split = make_split(keys, split_config)
    part = split.folds[0]
    predictions = {}
    for role, values in predicted.items():
        ids = np.asarray(part.positions[role], dtype=np.int64)
        predictions[(part.fold.name, role)] = values.reindex(ids).set_axis(ids)
    report = evaluate(split, predictions, Forecaster(name=model.name, params=model.params))
    metrics: dict[str, dict[str, float | int | None]] = {}
    for role in predicted:
        o = next(s for s in report.scores if s.role is role).overall
        metrics[role.value] = {
            "mae": o.mae,
            "rmse": o.rmse,
            "bias": o.bias,
            "wape": o.wape,
            "scored": o.scored,
            "missing_prediction": o.missing_prediction,
        }
    used = keys.loc[used_ids]
    used = used[model.usable(used) & used["value"].notna().to_numpy()]
    training = TrainingInfo(
        data_fingerprint=fingerprint(keys),
        data_rows=len(keys),
        training_rows=len(used),
        meters=int(used["meter_id"].nunique()),
        first=_iso(used["timestamp"].min()),
        last=_iso(used["timestamp"].max()),
        split_config_sha256=split_config.sha256(),
        split_config=split_config.model_dump(mode="json"),
    )
    return save(Trained(model=model, training=training, metrics=metrics), root)


def evaluation_model(
    store: Path,
    buildings: pd.DataFrame,
    study: Path = DEFAULT_OUTPUT,
    root: Path = DEFAULT_ROOT,
    split_config: SplitConfig = DEFAULT_SPLIT,
    fraction: float = SAMPLE_FRACTION,
    promote_if_reproduced: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Rebuild the T043 study's chosen model (trained on the training window only) and save it
    with its own split, so that its validation window is out-of-sample (T044a, D039).

    The production refit has seen the validation window, so calibrating intervals or a detector
    on that window would use in-sample residuals. The chosen model is retrained with the study's
    settings, sample and tree count; it is only promoted if it reproduces the study's recorded
    validation MAE, which shows it is the same model."""
    summary = json.loads((study / "fullscale.json").read_text(encoding="utf-8"))
    chosen = summary["chosen"]
    settings = {**chosen["settings"], "n_estimators": int(chosen["best_iteration"])}
    recorded = next(
        t["validation"]["mae"] for t in summary["search"] if t["settings"] == chosen["settings"]
    )
    keys = load_keys(store)
    rows = _rows(keys, split_config, buildings, fraction)
    val_ids, test_ids = rows.roles[Role.VALIDATION], rows.roles[Role.TEST]
    features = load_features(store, np.unique(np.concatenate([rows.train_ids, val_ids, test_ids])))
    t0 = time.perf_counter()
    model = FeatureModel(Family.LIGHTGBM, Variant.FULL, settings, features)
    model.fit(keys.loc[rows.train_ids])
    log(f"  refitted {model.name} in {time.perf_counter() - t0:.0f} s")
    predicted = {
        Role.VALIDATION: predict(model, keys, val_ids),
        Role.TEST: predict(model, keys, test_ids),
    }
    actual = keys["value"].to_numpy(dtype=float)
    validation = _metrics(actual[val_ids], predicted[Role.VALIDATION].reindex(val_ids).to_numpy())
    reproduced = validation["mae"] is not None and abs(validation["mae"] - recorded) <= 1e-6
    version = _save_model(model, keys, split_config, rows.train_ids, predicted, root)
    if reproduced and promote_if_reproduced:
        promote(version, root)
    result = {
        "version": version,
        "settings": settings,
        "validation_mae": validation["mae"],
        "recorded_validation_mae": recorded,
        "reproduced": reproduced,
        "promoted": bool(reproduced and promote_if_reproduced),
    }
    log(json.dumps(result, indent=2))
    return result


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(value: object) -> object:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def to_markdown(s: Mapping[str, Any]) -> str:
    def mae(c: Mapping[str, Any]) -> str:
        reduction = c["mae_reduction"]
        change = "n/a" if reduction is None else f"{reduction:+.1%}"
        return f"{c['model']['mae']:.3f} vs {c['seasonal_naive']['mae']:.3f} ({change})"

    lines = [
        "# Best model at full scale (T043)",
        "",
        f"{s['meters']} meters, {s['rows']:,} rows; training sample "
        f"{s['training_rows_sampled']:,} rows ({s['sample_fraction']:.0%} of quality-checked "
        f"training hours); {s['threads']} threads.",
        "",
        "## Search (validation)",
        "",
        "| Loss | Leaves | Trees (early stop) | Validation MAE | Against seasonal-naive "
        "(common rows) | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for trial in s["search"]:
        st = trial["settings"]
        lines.append(
            f"| {st['objective']} | {st['num_leaves']} | {trial['best_iteration']} | "
            f"{trial['validation']['mae']} | {mae(trial['validation_vs_naive'])} | "
            f"{trial['seconds']} |"
        )
    t = s["test"]
    lines += [
        "",
        f"Chosen: `{s['chosen']['name']}` (trees {s['chosen']['best_iteration']}). No-history "
        f"variant on validation: {mae(s['conditions_variant_validation'])}.",
        "",
        "## Test (scored once): MAE against seasonal-naive on common rows",
        "",
        f"- Chosen model: {mae(t['chosen'])} on {t['chosen']['common_rows']:,} rows",
        f"- Chosen model, quality rows: {mae(t['chosen_quality_rows'])}",
        f"- Production refit (training + validation windows): {mae(t['refit'])}",
    ]
    if "model" in t["sample_trained_model"]:
        lines.append(f"- Sample-trained model (D026): {mae(t['sample_trained_model'])}")
    lines += ["", "| Site | Rows | Model against seasonal-naive |", "|---|---|---|"]
    for site, c in t["per_site"].items():
        lines.append(f"| {site} | {c['common_rows']:,} | {mae(c)} |")
    lines += ["", "## Unseen buildings and sites", ""]
    for u in s["unseen"]:
        lines.append(
            f"- {u['holdout']['group_by']} holdout ({u['held_out_buildings']} buildings): seen "
            f"{mae(u['test'])}; unseen {mae(u['test_unseen'])}"
        )
    d = s["decision"]
    lines += ["", f"**Adopted: {'yes' if d['adopted'] else 'no'}.** {d['rule']}"]
    if d["artifact"]:
        lines.append(f"Artifact: `{d['artifact']}`; promoted: {'yes' if d['promoted'] else 'no'}.")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.fullscale",
        description="Search, test and refit the best model on every eligible meter.",
    )
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="T042 feature store")
    parser.add_argument("--data", type=Path, required=True, help="folder with buildings.parquet")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--promote", action="store_true", help="promote the result if it passes")
    parser.add_argument(
        "--evaluation-model",
        action="store_true",
        help="rebuild the study's chosen (training-window) model instead of running the study",
    )
    args = parser.parse_args(argv)
    try:
        buildings = pd.read_parquet(args.data / "buildings.parquet")
        if args.evaluation_model:
            result = evaluation_model(
                args.store, buildings, args.output, args.root,
                promote_if_reproduced=args.promote,
            )  # fmt: skip
            return 0 if result["reproduced"] else 1
        summary = run_study(
            args.store, buildings, args.output, args.root, promote_if_adopted=args.promote
        )
    except (FileNotFoundError, ValueError, RegistryError, KeyError, StopIteration) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(to_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
