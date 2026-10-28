import pandas as pd
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.conftest import SAMPLE_INFO, SYNTHETIC_SAMPLE
from wattwise.data.contracts import BUILDINGS, READINGS
from wattwise.data.validation import ContractViolationError
from wattwise.db.load import DatasetInfo, load_dataset, main, read_table
from wattwise.db.models import Building, DataKind, Dataset, Meter, Reading


@pytest.fixture(scope="module")
def tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    return read_table(SYNTHETIC_SAMPLE, BUILDINGS), read_table(SYNTHETIC_SAMPLE, READINGS)


def counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Dataset, Building, Meter, Reading)
        }


def test_the_sample_loads_completely_and_keeps_its_label(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables
    with migrated_engine.begin() as connection:
        summary = load_dataset(connection, SAMPLE_INFO, buildings, readings)

    assert summary.buildings == len(buildings) == 4
    assert summary.readings == len(readings) == 5376
    assert summary.meters == readings["meter_id"].nunique()
    assert summary.missing_values == int(readings["value"].isna().sum())
    assert counts(migrated_engine) == {
        "datasets": 1,
        "buildings": 4,
        "meters": summary.meters,
        "readings": 5376,
    }
    with Session(migrated_engine) as session:
        dataset = session.get(Dataset, SAMPLE_INFO.dataset_id)
        assert dataset is not None
        assert dataset.kind == "synthetic"


def test_stored_values_equal_the_source_and_missing_stays_missing(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables
    with migrated_engine.begin() as connection:
        load_dataset(connection, SAMPLE_INFO, buildings, readings)

    with Session(migrated_engine) as session:
        stored = pd.DataFrame(
            session.execute(
                select(Reading.meter_id, Reading.timestamp, Reading.value).order_by(
                    Reading.meter_id, Reading.timestamp
                )
            ).all(),
            columns=["meter_id", "timestamp", "value"],
        )
    source = readings.sort_values(["meter_id", "timestamp"]).reset_index(drop=True)
    assert stored["meter_id"].tolist() == source["meter_id"].tolist()
    assert (
        pd.to_datetime(stored["timestamp"], utc=True).tolist()
        == pd.to_datetime(source["timestamp"], utc=True).tolist()
    )
    pd.testing.assert_series_equal(
        stored["value"].astype(float), source["value"].astype(float), check_names=False
    )


def test_loading_again_replaces_the_dataset(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables
    with migrated_engine.begin() as connection:
        load_dataset(connection, SAMPLE_INFO, buildings, readings)
    one_building = buildings[buildings["building_id"] == "syn-office-a"]
    its_readings = readings[readings["building_id"] == "syn-office-a"]
    with migrated_engine.begin() as connection:
        load_dataset(connection, SAMPLE_INFO, one_building, its_readings)

    assert counts(migrated_engine) == {
        "datasets": 1,
        "buildings": 1,
        "meters": its_readings["meter_id"].nunique(),
        "readings": len(its_readings),
    }


def test_a_building_of_another_dataset_is_refused_and_nothing_changes(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables
    with migrated_engine.begin() as connection:
        load_dataset(connection, SAMPLE_INFO, buildings, readings)
    before = counts(migrated_engine)
    other = DatasetInfo("other", "another dataset", DataKind.OBSERVED, "tests")

    with pytest.raises(ValueError, match="another dataset"), migrated_engine.begin() as connection:
        load_dataset(connection, other, buildings, readings)

    assert counts(migrated_engine) == before


def test_readings_for_an_unknown_building_are_refused(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables

    with (
        pytest.raises(ValueError, match="missing from the buildings table"),
        migrated_engine.begin() as connection,
    ):
        load_dataset(connection, SAMPLE_INFO, buildings.iloc[:1], readings)

    assert counts(migrated_engine)["readings"] == 0


def test_a_table_that_violates_the_contract_is_not_loaded(
    migrated_engine: Engine, tables: tuple[pd.DataFrame, pd.DataFrame]
) -> None:
    buildings, readings = tables
    broken = readings.copy()
    broken.loc[0, "unit"] = "BTU"

    with pytest.raises(ContractViolationError), migrated_engine.begin() as connection:
        load_dataset(connection, SAMPLE_INFO, buildings, broken)

    assert counts(migrated_engine)["datasets"] == 0


def test_the_command_line_needs_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATTWISE_DATABASE_URL", raising=False)
    from wattwise.core.config import get_settings

    get_settings.cache_clear()
    try:
        code = main(
            [
                *("--source", str(SYNTHETIC_SAMPLE), "--dataset-id", "x"),
                *("--name", "x", "--kind", "synthetic"),
            ]
        )
    finally:
        get_settings.cache_clear()

    assert code == 1
