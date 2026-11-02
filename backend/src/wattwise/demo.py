"""Prepare the explicitly synthetic local demo, preserving models and reviews on restart."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from wattwise.core.config import get_settings
from wattwise.data.acquisition import sha256_of
from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER
from wattwise.db.alerts import load_alerts
from wattwise.db.engine import create_db_engine
from wattwise.db.expectations import compute_expectations, store_expectations
from wattwise.db.load import DatasetInfo, load_dataset, read_table
from wattwise.db.migrate import downgrade, upgrade
from wattwise.db.models import Alert, DataKind, Dataset, ExpectationSet, Reading
from wattwise.ml.baselines import SeasonalNaive
from wattwise.ml.detection import run_detection
from wattwise.ml.evaluation import Forecaster, evaluate, write_report
from wattwise.ml.explanations import explain
from wattwise.ml.models import FeatureModel
from wattwise.ml.registry import (
    RegistryError,
    current,
    load,
    promote,
    read_inputs,
    save,
    train,
    verify,
)
from wattwise.ml.splits import Chronological, Role, SplitConfig, make_split

DEMO_VERSION = "1"
DEMO_INFO = DatasetInfo(
    "synthetic-sample", "WattWise synthetic sample", DataKind.SYNTHETIC, "data/sample/synthetic"
)
DEMO_WINDOW = Chronological(
    train_start=datetime(2016, 1, 4, tzinfo=UTC),
    validation_start=datetime(2016, 1, 25, tzinfo=UTC),
    test_start=datetime(2016, 2, 8, tzinfo=UTC),
    test_end=datetime(2016, 2, 29, tzinfo=UTC),
)


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    demo_version: str
    source_sha256: dict[str, str]
    model_version: str
    data_fingerprint: str
    readings: int


@dataclass(frozen=True)
class DemoResult:
    seeded: bool
    model_version: str
    readings: int
    alerts: int


def _validate_checkpoint(checkpoint: Checkpoint, source_hashes: dict[str, str], root: Path) -> None:
    if checkpoint.demo_version != DEMO_VERSION or checkpoint.source_sha256 != source_hashes:
        raise ValueError(
            "Demo source/version changed. Use separate demo volumes; existing data is kept."
        )
    if current(root) != checkpoint.model_version:
        raise ValueError(
            "Demo model pointer differs from its checkpoint; restore matching artifacts."
        )
    metadata = verify(checkpoint.model_version, root)
    if metadata.training.data_fingerprint != checkpoint.data_fingerprint:
        raise ValueError("Demo model data differs from its checkpoint.")


def _counts(connection: Connection) -> tuple[int, int]:
    readings = connection.scalar(select(func.count()).select_from(Reading)) or 0
    alerts = connection.scalar(select(func.count()).select_from(Alert)) or 0
    return int(readings), int(alerts)


def _source_hashes(source: Path) -> dict[str, str]:
    return {
        f"{name}.csv": sha256_of(source / f"{name}.csv")
        for name in ("buildings", "readings", "weather")
    }


def _prepare(source: Path, artifacts: Path) -> Path:
    artifacts.mkdir(parents=True, exist_ok=True)
    prepared = artifacts / "prepared"
    prepared.mkdir(exist_ok=True)
    for contract in (BUILDINGS, READINGS, WEATHER):
        read_table(source, contract).to_parquet(prepared / f"{contract.name}.parquet", index=False)
    return prepared


def _write_evaluation(
    model: FeatureModel, readings: pd.DataFrame, buildings: pd.DataFrame, artifacts: Path
) -> None:
    """The chosen model's and seasonal-naive's T011 reports on the demo windows."""
    split = make_split(readings, SplitConfig(time=DEMO_WINDOW), buildings)
    part = split.folds[0]
    naive = SeasonalNaive()
    forecasters: tuple[tuple[FeatureModel | SeasonalNaive, str], ...] = (
        (model, "chosen"),
        (naive, naive.name),
    )
    for forecaster, name in forecasters:
        predictions = {
            (part.fold.name, role): forecaster.predict(
                part.rows(role).drop(columns="value"), readings
            )
            for role in (Role.VALIDATION, Role.TEST)
        }
        write_report(
            evaluate(
                split, predictions, Forecaster(name=forecaster.name, params=forecaster.params)
            ),
            artifacts / "evaluation",
            name,
        )


def _write_checkpoint(marker: Path, checkpoint: Checkpoint) -> None:
    pending = marker.with_suffix(".tmp")
    pending.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
    pending.replace(marker)


def build_artifacts(source: Path, artifacts: Path) -> Checkpoint:
    """Train and promote the demo model and write its checkpoint, without a database. A container
    image runs this at build time (T046), so a fresh database is seeded at startup without any
    training. An existing checkpoint is validated and kept."""
    source_hashes = _source_hashes(source)
    marker = artifacts / "demo.json"
    root = artifacts / "models"
    if marker.exists():
        checkpoint = Checkpoint.model_validate_json(marker.read_bytes())
        _validate_checkpoint(checkpoint, source_hashes, root)
        return checkpoint
    if (root / "CURRENT").exists():
        raise ValueError(
            "Model artifacts exist without a demo checkpoint; refusing to replace them."
        )
    readings, buildings, features = read_inputs(_prepare(source, artifacts), None)
    trained = train(readings, buildings, features, SplitConfig(time=DEMO_WINDOW))
    version = save(trained, root)
    promote(version, root)
    _write_evaluation(load(features, root=root).model, readings, buildings, artifacts)
    checkpoint = Checkpoint(
        demo_version=DEMO_VERSION,
        source_sha256=source_hashes,
        model_version=version,
        data_fingerprint=trained.training.data_fingerprint,
        readings=len(readings),
    )
    _write_checkpoint(marker, checkpoint)
    return checkpoint


def _stored_model_version(connection: Connection) -> str | None:
    version: str | None = connection.scalar(
        select(ExpectationSet.model_version).where(
            ExpectationSet.dataset_id == DEMO_INFO.dataset_id
        )
    )
    return version


def initialize_demo(
    engine: Engine, source: Path, artifacts: Path, *, replace_stale: bool = False
) -> DemoResult:
    """Seed the synthetic demo, preserving an existing one.

    With `replace_stale` (the public, read-only demo only, D064), a stored synthetic demo whose
    expectations come from another model than the checkpoint's is dropped and reseeded: a new
    image brings a new model, and the free database outlives it. It never touches a database
    holding any other dataset."""
    source_hashes = _source_hashes(source)
    marker = artifacts / "demo.json"
    root = artifacts / "models"
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(1463899219)"))
        upgrade(connection)
        checkpoint = (
            Checkpoint.model_validate_json(marker.read_bytes()) if marker.exists() else None
        )
        datasets: list[tuple[str, str]] = [
            (dataset_id, kind)
            for dataset_id, kind in connection.execute(select(Dataset.dataset_id, Dataset.kind))
        ]
        if datasets and datasets != [(DEMO_INFO.dataset_id, DataKind.SYNTHETIC.value)]:
            raise ValueError("Demo initialization refuses a database containing other datasets.")
        if checkpoint is not None:
            _validate_checkpoint(checkpoint, source_hashes, root)
        if (
            datasets
            and replace_stale
            and checkpoint is not None
            and _stored_model_version(connection) != checkpoint.model_version
        ):
            downgrade(connection)  # synthetic demo data only, checked above
            upgrade(connection)
            datasets = []
        if datasets:
            if checkpoint is None:
                raise ValueError(
                    "Demo data exists without its artifact checkpoint. Restore matching artifacts."
                )
            rows, alerts = _counts(connection)
            if rows != checkpoint.readings:
                raise ValueError(
                    "Demo reading count differs from its checkpoint; existing data is kept."
                )
            return DemoResult(False, checkpoint.model_version, rows, alerts)

        prepared = _prepare(source, artifacts)
        readings, buildings, features = read_inputs(prepared, None)
        config = SplitConfig(time=DEMO_WINDOW)
        if checkpoint is None:
            if (root / "CURRENT").exists():
                raise ValueError(
                    "Model artifacts exist without a demo checkpoint; refusing to replace them."
                )
            trained = train(readings, buildings, features, config)
            version = save(trained, root)
            promote(version, root)
            checkpoint = Checkpoint(
                demo_version=DEMO_VERSION,
                source_sha256=source_hashes,
                model_version=version,
                data_fingerprint=trained.training.data_fingerprint,
                readings=len(readings),
            )
        detected = run_detection(readings, buildings, features, root)
        bundles = explain(detected, readings, features, top=0)
        expectations, info = compute_expectations(prepared, None, None, root)
        _write_evaluation(detected.model.model, readings, buildings, artifacts)
        load_dataset(connection, DEMO_INFO, buildings, readings)
        load_alerts(connection, DEMO_INFO.dataset_id, bundles)
        store_expectations(connection, DEMO_INFO.dataset_id, expectations, info)
        _write_checkpoint(marker, checkpoint)
        return DemoResult(True, checkpoint.model_version, len(readings), len(bundles))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("../data/sample/synthetic"))
    parser.add_argument("--artifacts", type=Path, default=Path("../artifacts/demo"))
    parser.add_argument(
        "--build-only", action="store_true", help="train the model and checkpoint; no database"
    )
    parser.add_argument(
        "--replace-stale",
        action="store_true",
        help="public demo only: reseed a stored synthetic demo made with another model",
    )
    args = parser.parse_args()
    if args.build_only:
        try:
            checkpoint = build_artifacts(args.data, args.artifacts)
        except (ValueError, OSError, RegistryError) as exc:
            print(f"Demo build failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"synthetic": True, "model_version": checkpoint.model_version}))
        return 0
    url = get_settings().database_url
    if url is None:
        print("WATTWISE_DATABASE_URL is required for demo initialization.", file=sys.stderr)
        return 1
    engine = create_db_engine(url.get_secret_value())
    try:
        result = initialize_demo(
            engine, args.data, args.artifacts, replace_stale=args.replace_stale
        )
    except SQLAlchemyError as exc:
        print(f"Demo database initialization failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    except (ValueError, OSError, RegistryError) as exc:
        print(f"Demo initialization failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(json.dumps({"synthetic": True, **result.__dict__}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
