"""Load a dataset's canonical buildings and readings into the database (docs/DATABASE.md, T024).

Both tables are validated against the data contract first; a table that violates it is not
loaded at all. A dataset is replaced as a whole: loading it again removes its old buildings,
meters and readings in the same transaction, so a reload never mixes two versions. A building
that already belongs to *another* dataset is refused, never moved.

The meters come from the readings (each meter's building, type and unit, which the contract
makes consistent), and every meter's building must be in the buildings table.

    uv run --env-file .env python -m wattwise.db.load --source ../data/sample/synthetic \\
        --dataset-id synthetic-sample --kind synthetic \\
        --name "WattWise synthetic sample (seed 2016)"

`--source` is a folder with `buildings.csv` and `readings.csv` (the upload format), or with
`buildings.parquet` and `readings.parquet` (canonical tables, e.g. from bdg2_prepare).
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, delete, insert, select

from wattwise.core.config import get_settings
from wattwise.data.contracts import BUILDINGS, READINGS, TableContract
from wattwise.data.csv_io import read_csv
from wattwise.data.validation import ContractViolationError, to_canonical
from wattwise.db.engine import create_db_engine
from wattwise.db.models import Building, DataKind, Dataset, Meter, Reading


@dataclass(frozen=True)
class DatasetInfo:
    dataset_id: str
    name: str
    kind: DataKind
    source: str


@dataclass(frozen=True)
class LoadSummary:
    dataset_id: str
    buildings: int
    meters: int
    readings: int
    missing_values: int


def load_dataset(
    connection: Connection,
    info: DatasetInfo,
    buildings: pd.DataFrame,
    readings: pd.DataFrame,
) -> LoadSummary:
    """Replace `info`'s dataset with these tables, inside the caller's transaction.

    Raises `ContractViolationError` for a table that violates the contract, and `ValueError`
    for tables that are valid alone but inconsistent together, or that claim another dataset's
    buildings."""
    buildings = to_canonical(buildings, BUILDINGS)
    readings = to_canonical(readings, READINGS)
    meters = (
        readings[["meter_id", "building_id", "meter_type", "unit"]]
        .drop_duplicates("meter_id")
        .sort_values("meter_id")
    )
    unknown = sorted(set(meters["building_id"]) - set(buildings["building_id"]))
    if unknown:
        raise ValueError(f"readings name buildings missing from the buildings table: {unknown[:5]}")
    owners = connection.execute(
        select(Building.building_id, Building.dataset_id).where(
            Building.building_id.in_(buildings["building_id"].tolist()),
            Building.dataset_id != info.dataset_id,
        )
    ).all()
    if owners:
        taken = [f"{b} (in {d})" for b, d in owners[:5]]
        raise ValueError(f"buildings already belong to another dataset: {taken}")

    _remove(connection, info.dataset_id)
    connection.execute(
        insert(Dataset).values(
            dataset_id=info.dataset_id, name=info.name, kind=info.kind.value, source=info.source
        )
    )
    connection.execute(
        insert(Building),
        [
            {
                "building_id": row.building_id,
                "dataset_id": info.dataset_id,
                "site_id": row.site_id,
                "timezone": row.timezone,
                "primary_use": _text(row.primary_use),
                "floor_area_m2": _number(row.floor_area_m2),
                "latitude": _number(row.latitude),
                "longitude": _number(row.longitude),
            }
            for row in buildings.itertuples(index=False)
        ],
    )
    connection.execute(
        insert(Meter),
        [
            {"meter_id": m, "building_id": b, "meter_type": t, "unit": u}
            for m, b, t, u in meters.itertuples(index=False)
        ],
    )
    _copy_readings(connection, readings)
    return LoadSummary(
        dataset_id=info.dataset_id,
        buildings=len(buildings),
        meters=len(meters),
        readings=len(readings),
        missing_values=int(readings["value"].isna().sum()),
    )


def _remove(connection: Connection, dataset_id: str) -> None:
    owned = select(Building.building_id).where(Building.dataset_id == dataset_id)
    meters = select(Meter.meter_id).where(Meter.building_id.in_(owned))
    connection.execute(delete(Reading).where(Reading.meter_id.in_(meters)))
    connection.execute(delete(Meter).where(Meter.building_id.in_(owned)))
    connection.execute(delete(Building).where(Building.dataset_id == dataset_id))
    connection.execute(delete(Dataset).where(Dataset.dataset_id == dataset_id))


def _copy_readings(connection: Connection, readings: pd.DataFrame) -> None:
    """PostgreSQL COPY: one round trip for any number of rows (millions at full scale)."""
    cursor = connection.connection.dbapi_connection.cursor()  # type: ignore[union-attr]
    columns = zip(
        readings["meter_id"].tolist(),
        readings["timestamp"].dt.to_pydatetime().tolist(),
        readings["value"].tolist(),
        strict=True,
    )
    with cursor.copy('COPY readings (meter_id, "timestamp", value) FROM STDIN') as copy:
        for meter_id, timestamp, value in columns:
            copy.write_row((meter_id, timestamp, None if math.isnan(value) else value))


def _missing(value: object) -> bool:
    return value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))


def _number(value: object) -> float | None:
    return None if _missing(value) else float(value)  # type: ignore[arg-type]


def _text(value: object) -> str | None:
    return None if _missing(value) else str(value)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def read_table(folder: Path, contract: TableContract) -> pd.DataFrame:
    """A canonical table from `folder`: `<name>.parquet` if present, else `<name>.csv`."""
    parquet = folder / f"{contract.name}.parquet"
    if parquet.exists():
        return to_canonical(pd.read_parquet(parquet), contract)
    result = read_csv(folder / f"{contract.name}.csv", contract)
    if result.frame is None:
        raise ContractViolationError(result.report)
    return result.frame


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.db.load",
        description="Validate a dataset's buildings and readings and load them (replacing it).",
    )
    parser.add_argument("--source", type=Path, required=True, help="folder with the tables")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--name", required=True, help="a human-readable dataset name")
    parser.add_argument(
        "--kind",
        type=DataKind,
        choices=list(DataKind),
        required=True,
        help="synthetic (generated) or observed (measured)",
    )
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if url is None:
        print("error: WATTWISE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    info = DatasetInfo(args.dataset_id, args.name, args.kind, str(args.source))
    engine = create_db_engine(url.get_secret_value())
    try:
        buildings = read_table(args.source, BUILDINGS)
        readings = read_table(args.source, READINGS)
        with engine.begin() as connection:
            summary = load_dataset(connection, info, buildings, readings)
    except ContractViolationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for issue in exc.report.errors:
            print(f"  [{issue.code.value}] {issue.message}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"loaded {summary.dataset_id} ({info.kind.value}): {summary.buildings} buildings, "
        f"{summary.meters} meters, {summary.readings:,} readings "
        f"({summary.missing_values:,} missing values)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
