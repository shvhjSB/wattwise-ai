"""Store and read a dataset's data-quality audit (T047, docs/DATA_QUALITY.md).

`load_dataset` audits the readings it loads and stores the result. A dataset loaded before T047
has no audit; `python -m wattwise.db.quality --dataset-id ID` audits its stored readings.

    uv run --env-file .env python -m wattwise.db.quality --dataset-id bdg2-sample
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import pandas as pd
from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from wattwise.core.config import get_settings
from wattwise.data.quality import QualityReport, assess
from wattwise.db.engine import create_db_engine
from wattwise.db.models import Building, Dataset, DatasetQuality, Meter, Reading


def store_quality(connection: Connection, dataset_id: str, report: QualityReport) -> None:
    """Store (or replace) the audit of `dataset_id`, inside the caller's transaction. A report
    whose readings failed the contract is refused: stored readings always passed it."""
    if not report.valid or report.summary is None:
        raise ValueError("Only an audit of contract-valid readings can be stored.")
    values = {
        "quality_version": report.quality_version,
        "contract_version": report.contract_version,
        "thresholds": report.thresholds.model_dump(mode="json"),
        "summary": report.summary.model_dump(mode="json"),
        "meters": [m.model_dump(mode="json") for m in report.meters],
    }
    statement = pg_insert(DatasetQuality).values(dataset_id=dataset_id, **values)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[DatasetQuality.dataset_id],
            set_={**values, "assessed_at": statement.excluded.assessed_at},
        )
    )


def stored_tables(connection: Connection, dataset_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A stored dataset's buildings and readings in canonical form."""
    buildings = pd.DataFrame(
        connection.execute(
            select(
                Building.building_id,
                Building.site_id,
                Building.timezone,
                Building.primary_use,
                Building.floor_area_m2,
                Building.latitude,
                Building.longitude,
            ).where(Building.dataset_id == dataset_id)
        ).all(),
        columns=[
            "building_id",
            "site_id",
            "timezone",
            "primary_use",
            "floor_area_m2",
            "latitude",
            "longitude",
        ],
    )
    readings = pd.DataFrame(
        connection.execute(
            select(
                Reading.timestamp,
                Reading.meter_id,
                Meter.building_id,
                Meter.meter_type,
                Meter.unit,
                Reading.value,
            )
            .join(Meter, Meter.meter_id == Reading.meter_id)
            .join(Building, Building.building_id == Meter.building_id)
            .where(Building.dataset_id == dataset_id)
        ).all(),
        columns=["timestamp", "meter_id", "building_id", "meter_type", "unit", "value"],
    )
    readings["timestamp"] = pd.to_datetime(readings["timestamp"], utc=True)
    readings["value"] = readings["value"].astype(float)
    return buildings, readings


def assess_stored(connection: Connection, dataset_id: str) -> QualityReport:
    """Audit a stored dataset's readings and store the result."""
    if (
        connection.scalar(select(Dataset.dataset_id).where(Dataset.dataset_id == dataset_id))
        is None
    ):
        raise ValueError(f"Unknown dataset {dataset_id!r}.")
    buildings, readings = stored_tables(connection, dataset_id)
    report = assess(readings, buildings)
    store_quality(connection, dataset_id, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.db.quality",
        description="Audit a stored dataset's readings and store the data-quality report.",
    )
    parser.add_argument("--dataset-id", required=True)
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if url is None:
        print("error: WATTWISE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_db_engine(url.get_secret_value())
    try:
        with engine.begin() as connection:
            report = assess_stored(connection, args.dataset_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    assert report.summary is not None
    print(
        f"{args.dataset_id}: {report.summary.meters} meters, {report.summary.rows:,} rows, "
        f"coverage {report.summary.coverage_pct}%, "
        f"{report.summary.meters_with_warnings} meters with warnings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
