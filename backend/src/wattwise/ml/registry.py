"""Versioned model artifacts and the registry the API loads from (docs/MODELS.md, D027).

An artifact is a folder `<root>/<version>/` holding:
- `model.txt`: the LightGBM model in LightGBM's own text format
- `state.json`: what the model learned besides the trees (the conditions variant's meter scales
  and weekly profiles; empty for the full variant)
- `metadata.json`: what it is and how it was made: model, settings, features, training data
  fingerprint and period, split, code version, library versions, metrics and `created_at`,
  plus the SHA-256 of the two files above

No file is ever unpickled: loading parses text and JSON only, after checking the hashes. So only
LightGBM models can be saved; scikit-learn models have no safe format.

Writes are atomic. A version folder is written under a temporary name and renamed into place,
and `CURRENT` (the promoted version) is replaced with an atomic rename after the version
verifies. Older versions are kept, so promoting one again rolls back. Without a promoted model,
`load` raises NoModelError, which callers turn into "no model available".

    uv run python -m wattwise.ml.registry train --data ../data/processed/bdg2/cleaned \
        --enrichment ../data/processed/era5/weather_enrichment.parquet --promote
    uv run python -m wattwise.ml.registry evaluate --data ... --enrichment ...
    uv run python -m wattwise.ml.registry list
    uv run python -m wattwise.ml.registry promote <version>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lightgbm
import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from wattwise.ml.baselines import DEFAULT_SPLIT, run, utc_argument
from wattwise.ml.evaluation import CodeVersion, Forecaster, code_version, evaluate, fingerprint
from wattwise.ml.features import (
    DEFAULT_HORIZON_HOURS,
    FEATURE_SET_VERSION,
    build_features,
    feature_names,
)
from wattwise.ml.models import (
    GRID,
    MIN_SCALE,
    VARIANT_GROUPS,
    Family,
    FeatureModel,
    Variant,
    overall,
)
from wattwise.ml.splits import Chronological, Role, SplitConfig, make_split

ARTIFACT_VERSION: Final = "1"
DEFAULT_ROOT: Final = Path("../artifacts/models")
CURRENT: Final = "CURRENT"
MODEL_FILE: Final = "model.txt"
STATE_FILE: Final = "state.json"
METADATA_FILE: Final = "metadata.json"
#: The model adopted in D026: LightGBM on every feature group, 200 trees.
ADOPTED: Final = (Family.LIGHTGBM, Variant.FULL, GRID[Family.LIGHTGBM][0])
SCORED: Final = (Role.VALIDATION, Role.TEST)
_VERSION_NAME: Final = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")
_SCALE_RULE: Final = {
    Variant.FULL: "target / rolling_mean_168h (the meter's mean over the week ending one "
    "horizon before); no prediction where the scale is missing or below min_scale",
    Variant.CONDITIONS: "target / the meter's mean over its training rows; no prediction for "
    "meters without training rows or with a scale below min_scale",
}


class RegistryError(Exception):
    """A registry operation could not be completed; nothing was changed."""


class NoModelError(RegistryError):
    """No model has been promoted yet."""


class IntegrityError(RegistryError):
    """An artifact's files do not match the hashes recorded in its metadata."""


class IncompatibleModelError(RegistryError):
    """An artifact was made for a different artifact or feature-set version."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelInfo(_Strict):
    name: str
    family: str
    variant: str
    settings: dict[str, int | float]  # ints stay ints, so the model name is unchanged
    seed: int


class TrainingInfo(_Strict):
    data_fingerprint: str  # wattwise.ml.evaluation.fingerprint of all readings given
    data_rows: int
    training_rows: int  # rows with a value and a usable scale that the model was fitted on
    meters: int
    first: str  # first and last training interval start, UTC
    last: str
    split_config_sha256: str
    split_config: dict[str, Any]


class Metadata(_Strict):
    artifact_version: str
    version: str
    created_at: str
    model: ModelInfo
    feature_set_version: str
    horizon_hours: int
    feature_columns: list[str]  # model inputs, in order (features plus derived scale columns)
    min_scale: float
    scale_rule: str
    training: TrainingInfo
    code: CodeVersion
    libraries: dict[str, str]
    metrics: dict[str, dict[str, float | int | None]]  # role -> overall metrics
    files: dict[str, str]  # file name -> SHA-256


@dataclass(frozen=True)
class Trained:
    model: FeatureModel
    training: TrainingInfo
    metrics: dict[str, dict[str, float | int | None]]


@dataclass(frozen=True)
class Loaded:
    model: FeatureModel
    metadata: Metadata


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    features: pd.DataFrame,
    split_config: SplitConfig = DEFAULT_SPLIT,
    family: Family = ADOPTED[0],
    variant: Variant = ADOPTED[1],
    settings: Mapping[str, float] = ADOPTED[2],
) -> Trained:
    """Fit on the split's training rows and score validation and test with the T011 harness.

    The artifact is exactly the evaluated model, so its recorded metrics are out-of-sample."""
    split = make_split(readings, split_config, buildings)
    if len(split.folds) != 1:
        raise ValueError("Train an artifact on a single-fold (chronological) split.")
    model = FeatureModel(family, variant, settings, features)
    result = run(split, [model], roles=SCORED)
    part = split.folds[0]
    train_rows = part.rows(Role.TRAIN).dropna(subset=["value"])
    used = train_rows[model.usable(train_rows)]
    training = TrainingInfo(
        data_fingerprint=fingerprint(readings),
        data_rows=len(readings),
        training_rows=len(used),
        meters=int(used["meter_id"].nunique()),
        first=_iso(used["timestamp"].min()),
        last=_iso(used["timestamp"].max()),
        split_config_sha256=split_config.sha256(),
        split_config=split_config.model_dump(mode="json"),
    )
    metrics = {role.value: overall(result, model.name, role) for role in SCORED}
    return Trained(model=model, training=training, metrics=metrics)


# ---------------------------------------------------------------------------
# Saving, promoting, loading
# ---------------------------------------------------------------------------


def save(
    trained: Trained,
    root: Path = DEFAULT_ROOT,
    created_at: datetime | None = None,
    code: CodeVersion | None = None,
) -> str:
    """Write a new version atomically and return its name. Nothing is promoted."""
    model = trained.model
    if model.family is not Family.LIGHTGBM:
        raise RegistryError(
            f"Only LightGBM models can be saved: {model.family} has no safe file format, and "
            "artifacts are never pickled."
        )
    if model.model is None:
        raise RegistryError("Fit the model before saving it.")
    created = (created_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    files = {MODEL_FILE: model.model.booster_.model_to_string().encode("utf-8")}
    files[STATE_FILE] = _json(_state(model))
    version = f"{created:%Y%m%dT%H%M%SZ}-{_sha256(files[MODEL_FILE])[:12]}"
    metadata = Metadata(
        artifact_version=ARTIFACT_VERSION,
        version=version,
        created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=ModelInfo(
            name=model.name,
            family=model.family.value,
            variant=model.variant.value,
            settings=dict(model.settings),
            seed=model.seed,
        ),
        feature_set_version=FEATURE_SET_VERSION,
        horizon_hours=DEFAULT_HORIZON_HOURS,
        feature_columns=list(model.columns),
        min_scale=MIN_SCALE,
        scale_rule=_SCALE_RULE[model.variant],
        training=trained.training,
        code=code or code_version(),
        libraries={p: importlib.metadata.version(p) for p in ("lightgbm", "numpy", "pandas")},
        metrics=trained.metrics,
        files={name: _sha256(content) for name, content in files.items()},
    )
    files[METADATA_FILE] = _json(metadata.model_dump(mode="json"))

    root.mkdir(parents=True, exist_ok=True)
    target = root / version
    if target.exists():
        raise RegistryError(f"Version {version} already exists; versions are never overwritten.")
    staging = root / f".staging-{version}-{os.getpid()}"
    try:
        staging.mkdir()
        for name, content in files.items():
            _write_file(staging / name, content)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return version


def promote(version: str, root: Path = DEFAULT_ROOT) -> Metadata:
    """Make `version` the current model, after checking that it verifies and is compatible.
    The pointer is replaced atomically; on any error the current model is unchanged."""
    metadata = verify(version, root)
    pointer = root / f".{CURRENT}.{os.getpid()}.tmp"
    try:
        _write_file(pointer, (version + "\n").encode("utf-8"))
        os.replace(pointer, root / CURRENT)
    except BaseException:
        pointer.unlink(missing_ok=True)
        raise
    return metadata


def current(root: Path = DEFAULT_ROOT) -> str:
    """The promoted version's name; NoModelError if none."""
    try:
        name = (root / CURRENT).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise NoModelError(f"No model has been promoted in {root}.") from None
    if not name:
        raise NoModelError(f"{root / CURRENT} is empty: no model has been promoted.")
    return _checked_name(name)


def versions(root: Path = DEFAULT_ROOT) -> list[str]:
    """Saved versions, oldest first (names start with their creation time)."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and _VERSION_NAME.match(p.name))


def verify(version: str, root: Path = DEFAULT_ROOT) -> Metadata:
    """Read a version's metadata and check its files' hashes and compatibility."""
    folder = root / _checked_name(version)
    try:
        raw = (folder / METADATA_FILE).read_bytes()
    except FileNotFoundError:
        raise RegistryError(f"Version {version} does not exist in {root}.") from None
    try:
        metadata = Metadata.model_validate_json(raw)
    except ValidationError as exc:
        raise IntegrityError(f"{version}: metadata.json is not valid: {exc}") from exc
    if metadata.version != version:
        raise IntegrityError(f"{version}: the metadata names version {metadata.version}.")
    for name in (MODEL_FILE, STATE_FILE):
        path = folder / name
        if name not in metadata.files or not path.exists():
            raise IntegrityError(f"{version}: {name} is missing.")
        if _sha256(path.read_bytes()) != metadata.files[name]:
            raise IntegrityError(f"{version}: {name} does not match its recorded SHA-256.")
    if metadata.artifact_version != ARTIFACT_VERSION:
        raise IncompatibleModelError(
            f"{version}: artifact version {metadata.artifact_version}; this code reads "
            f"{ARTIFACT_VERSION}."
        )
    if metadata.feature_set_version != FEATURE_SET_VERSION:
        raise IncompatibleModelError(
            f"{version}: made for feature set {metadata.feature_set_version}; this code builds "
            f"feature set {FEATURE_SET_VERSION}."
        )
    if metadata.model.family != Family.LIGHTGBM.value:
        raise IncompatibleModelError(f"{version}: unsupported family {metadata.model.family}.")
    return metadata


def load(features: pd.DataFrame, version: str | None = None, root: Path = DEFAULT_ROOT) -> Loaded:
    """The current (or given) version, ready to predict rows of `features` (feature set 1,
    indexed like the readings). Raises NoModelError when nothing is promoted."""
    name = version or current(root)
    metadata = verify(name, root)
    variant = Variant(metadata.model.variant)
    needed = set(feature_names(VARIANT_GROUPS[variant]))
    missing = sorted(needed - set(features.columns))
    if missing:
        raise IncompatibleModelError(f"{name}: the feature table lacks {missing[:5]}.")
    folder = root / name
    model = FeatureModel(
        Family(metadata.model.family),
        variant,
        metadata.model.settings,
        features,
        metadata.model.seed,
    )
    model.model = lightgbm.Booster(model_str=(folder / MODEL_FILE).read_text(encoding="utf-8"))
    model.columns = list(metadata.feature_columns)
    state = json.loads((folder / STATE_FILE).read_text(encoding="utf-8"))
    if variant is Variant.CONDITIONS:
        model.level = pd.Series(state["level"], dtype=float)
        model.level.index.name = "meter_id"
        profile = pd.DataFrame(state["profile"], columns=["meter_id", "how", "value"])
        model.profile = profile.set_index(["meter_id", "how"])["value"].astype(float)
    return Loaded(model=model, metadata=metadata)


def _state(model: FeatureModel) -> dict[str, Any]:
    if model.variant is Variant.FULL:
        return {}
    assert model.level is not None and model.profile is not None
    return {
        "level": {str(k): float(v) for k, v in model.level.items()},
        "profile": [
            [str(m), float(h), float(v)]
            for m, h, v in zip(
                model.profile.index.get_level_values(0),
                model.profile.index.get_level_values(1),
                model.profile.to_numpy(dtype=float),
                strict=True,
            )
        ],
    }


def _checked_name(name: str) -> str:
    if not _VERSION_NAME.match(name):
        raise RegistryError(f"{name!r} is not a version name.")
    return name


def _write_file(path: Path, content: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _json(data: object) -> bytes:
    return (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Re-evaluation
# ---------------------------------------------------------------------------


def reevaluate(
    loaded: Loaded, readings: pd.DataFrame, buildings: pd.DataFrame
) -> dict[str, dict[str, float | int | None]]:
    """Score a loaded artifact again on its own split. With the same data this must reproduce
    the metrics recorded at training time."""
    config = SplitConfig.model_validate(loaded.metadata.training.split_config)
    split = make_split(readings, config, buildings)
    part = split.folds[0]
    predictions = {
        (part.fold.name, role): loaded.model.predict(
            part.rows(role).drop(columns="value"), readings
        )
        for role in SCORED
    }
    report = evaluate(
        split, predictions, Forecaster(name=loaded.model.name, params=loaded.model.params)
    )
    out: dict[str, dict[str, float | int | None]] = {}
    for score in report.scores:
        o = score.overall
        out[score.role.value] = {
            "mae": o.mae,
            "rmse": o.rmse,
            "bias": o.bias,
            "wape": o.wape,
            "scored": o.scored,
            "missing_prediction": o.missing_prediction,
        }
    return out


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _read_inputs(
    data: Path, enrichment: Path | None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    readings = pd.read_parquet(data / "readings.parquet")
    buildings = pd.read_parquet(data / "buildings.parquet")
    weather = (
        pd.read_parquet(data / "weather.parquet") if (data / "weather.parquet").exists() else None
    )
    extra = pd.read_parquet(enrichment) if enrichment else None
    return readings, buildings, build_features(readings, buildings, weather, extra)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.registry", description="Train, evaluate and promote models."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="artifact folder")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("train", "evaluate"):
        sub = commands.add_parser(name)
        sub.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
        sub.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    train_cmd = commands.choices["train"]
    train_cmd.add_argument("--promote", action="store_true", help="promote the new version")
    defaults = DEFAULT_SPLIT.time
    assert isinstance(defaults, Chronological)
    for option, value in (
        ("--train-start", defaults.train_start),
        ("--validation-start", defaults.validation_start),
        ("--test-start", defaults.test_start),
        ("--test-end", defaults.test_end),
    ):
        train_cmd.add_argument(option, default=value, type=utc_argument, help="UTC")
    commands.choices["evaluate"].add_argument("--version", help="default: the current version")
    commands.add_parser("list")
    commands.add_parser("promote").add_argument("version")
    args = parser.parse_args(argv)
    root: Path = args.root
    try:
        if args.command == "list":
            return _list(root)
        if args.command == "promote":
            metadata = promote(args.version, root)
            print(f"current model: {metadata.version} ({metadata.model.name})")
            return 0
        readings, buildings, features = _read_inputs(args.data, args.enrichment)
        if args.command == "train":
            config = SplitConfig(
                time=Chronological(
                    train_start=args.train_start,
                    validation_start=args.validation_start,
                    test_start=args.test_start,
                    test_end=args.test_end,
                )
            )
            trained = train(readings, buildings, features, config)
            version = save(trained, root)
            print(f"saved {version}: {trained.model.name}")
            for role, metrics in trained.metrics.items():
                print(f"  {role:10s} MAE {metrics['mae']} WAPE {metrics['wape']}")
            if args.promote:
                promote(version, root)
                print(f"current model: {version}")
            return 0
        loaded = load(features, args.version, root)
        return _report_reevaluation(loaded, readings, buildings)
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _list(root: Path) -> int:
    names = versions(root)
    if not names:
        print(f"no saved models in {root}")
        return 0
    try:
        promoted: str | None = current(root)
    except NoModelError:
        promoted = None
    for name in names:
        try:
            m = verify(name, root)
            test = m.metrics.get("test", {})
            detail = f"{m.model.name}  test MAE {test.get('mae')}"
        except RegistryError as exc:
            detail = f"UNUSABLE: {exc}"
        print(f"{'*' if name == promoted else ' '} {name}  {detail}")
    return 0


def _report_reevaluation(loaded: Loaded, readings: pd.DataFrame, buildings: pd.DataFrame) -> int:
    m = loaded.metadata
    same_data = fingerprint(readings) == m.training.data_fingerprint
    again = reevaluate(loaded, readings, buildings)
    print(f"{m.version}: {m.model.name}")
    print(f"  data: {'same as training' if same_data else 'DIFFERENT from training'}")
    for role, metrics in again.items():
        print(f"  {role:10s} MAE {metrics['mae']} (recorded {m.metrics[role]['mae']})")
    if not same_data:
        print("  different data: the recorded metrics are not expected to be reproduced")
        return 0
    if again != m.metrics:
        print("error: the recorded metrics were not reproduced", file=sys.stderr)
        return 1
    print("  recorded metrics reproduced exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
