"""Compute and store the model's expectation and interval for a dataset (D052, T030).

The explorer draws each meter's readings against what the model expected and its 90% interval.
Neither is in the readings, and computing them per request would need weather and ERA5 data the
API does not hold. So they are computed once, here, by the same code that produces the alerts'
evidence (`wattwise.ml.explanations.expectation_bounds`), and stored for the **evaluation
windows** only: validation and test, where the model's residuals are out of sample. Elsewhere
(the training period, other datasets) there is no expectation, and the API says so.

    uv run --env-file .env python -m wattwise.db.expectations --dataset-id bdg2-cleaned-all \\
        --data ../data/processed/bdg2/cleaned-all \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet \\
        --store ../data/processed/features-all
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import Connection, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from wattwise.core.config import get_settings
from wattwise.db.engine import create_db_engine
from wattwise.db.models import Building, Expectation, ExpectationSet, Meter
from wattwise.ml.explanations import INTERVAL_ALPHA, expectation_bounds
from wattwise.ml.fullscale import downstream_inputs
from wattwise.ml.registry import DEFAULT_ROOT, NoModelError, RegistryError, load
from wattwise.ml.splits import Chronological, SplitConfig

COPY_CHUNK_ROWS = 500_000


@dataclass(frozen=True)
class ExpectationInfo:
    model_version: str
    measured_coverage: float | None
    window_start: datetime
    window_end: datetime
    detection_start: datetime


@dataclass(frozen=True)
class ExpectationSummary:
    dataset_id: str
    model_version: str
    rows: int
    rows_with_interval: int
    meters: int


def compute_expectations(
    data: Path, enrichment: Path | None, store: Path | None, root: Path
) -> tuple[pd.DataFrame, ExpectationInfo]:
    """The expectation and interval of every reading in the promoted model's validation and test
    windows (columns meter_id, timestamp, expected, lower, upper), and what produced them."""
    readings, _, features = downstream_inputs(data, enrichment, store, root)
    loaded = load(features, root=root)
    split = SplitConfig.model_validate(loaded.metadata.training.split_config).time
    if not isinstance(split, Chronological) or split.validation_start is None:
        raise RegistryError("The promoted model has no validation window to calibrate on.")
    calibration = (split.validation_start, split.test_start)
    detection = (split.test_start, split.test_end)
    bounds, held = expectation_bounds(loaded.model, readings, features, calibration, detection)
    frame = readings.loc[bounds.index, ["meter_id", "timestamp"]].join(bounds)
    frame = frame[frame["timestamp"] < split.test_end]
    info = ExpectationInfo(
        model_version=loaded.metadata.version,
        measured_coverage=held,
        window_start=split.validation_start,
        window_end=split.test_end,
        detection_start=split.test_start,
    )
    return frame.reset_index(drop=True), info


def store_expectations(
    connection: Connection, dataset_id: str, frame: pd.DataFrame, info: ExpectationInfo
) -> ExpectationSummary:
    """Replace `dataset_id`'s stored expectations with `frame`, inside the caller's transaction.

    Rows without an expectation are not stored (an interval needs one). Raises `ValueError` for
    meters that are not the dataset's."""
    frame = frame[frame["expected"].notna()]
    meters = set(
        connection.scalars(
            select(Meter.meter_id).join(Building).where(Building.dataset_id == dataset_id)
        )
    )
    if not meters:
        raise ValueError(f"dataset {dataset_id!r} has no meters; load its readings first")
    foreign = sorted(set(frame["meter_id"]) - meters)
    if foreign:
        raise ValueError(f"meters not in dataset {dataset_id!r}: {foreign[:5]}")

    connection.execute(delete(Expectation).where(Expectation.meter_id.in_(sorted(meters))))
    values = {
        "model_version": info.model_version,
        "interval_nominal": 1 - INTERVAL_ALPHA,
        "measured_coverage": info.measured_coverage,
        "window_start": info.window_start,
        "window_end": info.window_end,
        "detection_start": info.detection_start,
        "row_count": len(frame),
    }
    connection.execute(
        pg_insert(ExpectationSet)
        .values(dataset_id=dataset_id, **values)
        .on_conflict_do_update(
            index_elements=[ExpectationSet.dataset_id], set_={**values, "created_at": func.now()}
        )
    )
    _copy(connection, frame)
    return ExpectationSummary(
        dataset_id=dataset_id,
        model_version=info.model_version,
        rows=len(frame),
        rows_with_interval=int(frame["lower"].notna().sum()),
        meters=int(frame["meter_id"].nunique()),
    )


def _copy(connection: Connection, frame: pd.DataFrame) -> None:
    """COPY in CSV chunks; an empty field is NULL (the same approach as the readings)."""
    cursor = connection.connection.dbapi_connection.cursor()  # type: ignore[union-attr]
    with cursor.copy(
        'COPY expectations (meter_id, "timestamp", expected, lower, upper) FROM STDIN (FORMAT csv)'
    ) as copy:
        for first in range(0, len(frame), COPY_CHUNK_ROWS):
            part = frame.iloc[first : first + COPY_CHUNK_ROWS]
            utc = part["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
            stamps = np.datetime_as_string(utc.to_numpy("datetime64[us]"), unit="us")
            chunk = pd.DataFrame(
                {
                    "meter_id": part["meter_id"].to_numpy(),
                    "timestamp": np.char.add(stamps, "Z"),
                    "expected": part["expected"].to_numpy(),
                    "lower": part["lower"].to_numpy(),
                    "upper": part["upper"].to_numpy(),
                }
            )
            copy.write(chunk.to_csv(index=False, header=False, lineterminator="\n"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.db.expectations",
        description="Compute and store the promoted model's expectation and interval.",
    )
    parser.add_argument("--dataset-id", required=True, help="a dataset already loaded")
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--store", type=Path, help="T042 feature store (full scale)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if url is None:
        print("error: WATTWISE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    try:
        frame, info = compute_expectations(args.data, args.enrichment, args.store, args.root)
    except NoModelError as exc:
        print(f"error: {exc} Train and promote one first.", file=sys.stderr)
        return 1
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    engine = create_db_engine(url.get_secret_value())
    try:
        with engine.begin() as connection:
            summary = store_expectations(connection, args.dataset_id, frame, info)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"stored {summary.rows:,} expectations ({summary.rows_with_interval:,} with an interval) "
        f"for {summary.meters:,} meters of {summary.dataset_id}, model {summary.model_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
