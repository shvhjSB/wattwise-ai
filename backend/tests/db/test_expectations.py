from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.db.expectations import (
    ExpectationInfo,
    compute_expectations,
    main,
    store_expectations,
)
from wattwise.db.load import DatasetInfo, load_dataset
from wattwise.db.models import DataKind, Expectation, ExpectationSet
from wattwise.ml.registry import current, promote, save, train
from wattwise.ml.splits import Chronological

DATASET = "ml-synthetic"


def chronological() -> Chronological:
    split = SPLIT.time
    assert isinstance(split, Chronological)  # the test split is chronological
    return split


TIME = chronological()


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, pd.DataFrame]:
    """A promoted tiny model, its prepared tables on disk, and the readings."""
    readings, weather = synthetic()
    root = tmp_path_factory.mktemp("models")
    promote(save(train(readings, BUILDINGS, features_of(readings, weather), SPLIT), root), root)
    data = tmp_path_factory.mktemp("data")
    readings.to_parquet(data / "readings.parquet")
    BUILDINGS.to_parquet(data / "buildings.parquet")
    weather.to_parquet(data / "weather.parquet")
    return root, data, readings


@pytest.fixture(scope="module")
def computed(
    prepared: tuple[Path, Path, pd.DataFrame],
) -> tuple[pd.DataFrame, ExpectationInfo]:
    root, data, _ = prepared
    return compute_expectations(data, None, None, root)


def test_expectations_cover_exactly_the_validation_and_test_windows(
    computed: tuple[pd.DataFrame, ExpectationInfo],
) -> None:
    frame, info = computed

    assert frame["timestamp"].min() == TIME.validation_start
    assert frame["timestamp"].max() < TIME.test_end
    assert (info.window_start, info.window_end) == (
        TIME.validation_start,
        TIME.test_end,
    )
    assert info.detection_start == TIME.test_start
    # 3 meters, every hour from 2017-03-01 to 2017-04-11
    assert len(frame) == 3 * 41 * 24


def test_the_interval_brackets_the_expectation_and_begins_after_calibration(
    computed: tuple[pd.DataFrame, ExpectationInfo],
) -> None:
    frame, _ = computed

    with_interval = frame[frame["lower"].notna()]
    assert 0 < len(with_interval) < len(frame)  # the first days have no interval
    assert (with_interval["lower"] <= with_interval["expected"]).all()
    assert (with_interval["expected"] <= with_interval["upper"]).all()
    assert (with_interval["lower"] >= 0).all()


def test_the_model_and_measured_coverage_are_recorded(
    computed: tuple[pd.DataFrame, ExpectationInfo], prepared: tuple[Path, Path, pd.DataFrame]
) -> None:
    _, info = computed

    assert info.model_version == current(prepared[0])
    assert info.measured_coverage is not None
    assert 0.5 < info.measured_coverage <= 1.0


@pytest.fixture
def loaded_engine(migrated_engine: Engine, prepared: tuple[Path, Path, pd.DataFrame]) -> Engine:
    readings = prepared[2]
    with migrated_engine.begin() as connection:
        load_dataset(
            connection,
            DatasetInfo(DATASET, "ML test data", DataKind.SYNTHETIC, "tests"),
            BUILDINGS,
            readings,
        )
    return migrated_engine


def count(engine: Engine) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(Expectation)) or 0)


def test_stored_expectations_equal_the_computed_ones(
    loaded_engine: Engine, computed: tuple[pd.DataFrame, ExpectationInfo]
) -> None:
    frame, info = computed

    with loaded_engine.begin() as connection:
        summary = store_expectations(connection, DATASET, frame, info)

    assert summary.rows == count(loaded_engine) == len(frame)
    assert summary.meters == 3
    assert summary.rows_with_interval == int(frame["lower"].notna().sum())
    with Session(loaded_engine) as session:
        stored = pd.DataFrame(
            session.execute(
                select(
                    Expectation.meter_id,
                    Expectation.timestamp,
                    Expectation.expected,
                    Expectation.lower,
                    Expectation.upper,
                ).order_by(Expectation.meter_id, Expectation.timestamp)
            ).all(),
            columns=["meter_id", "timestamp", "expected", "lower", "upper"],
        )
        saved = session.get(ExpectationSet, DATASET)
    source = frame.sort_values(["meter_id", "timestamp"]).reset_index(drop=True)
    assert stored["meter_id"].tolist() == source["meter_id"].tolist()
    for column in ("expected", "lower", "upper"):
        # single precision: equal to about 7 significant digits; missing stays missing
        np.testing.assert_allclose(
            stored[column].astype(float), source[column].astype(float), rtol=1e-6, equal_nan=True
        )
    assert saved is not None
    assert saved.model_version == info.model_version
    assert saved.interval_nominal == pytest.approx(0.9)
    assert saved.row_count == len(frame)
    assert saved.window_start == info.window_start


def test_storing_again_replaces_rather_than_adds(
    loaded_engine: Engine, computed: tuple[pd.DataFrame, ExpectationInfo]
) -> None:
    frame, info = computed
    for _ in range(2):
        with loaded_engine.begin() as connection:
            store_expectations(connection, DATASET, frame, info)

    assert count(loaded_engine) == len(frame)


def test_rows_without_an_expectation_are_not_stored(
    loaded_engine: Engine, computed: tuple[pd.DataFrame, ExpectationInfo]
) -> None:
    frame, info = computed
    gappy = frame.copy()
    gappy.loc[gappy.index[:10], ["expected", "lower", "upper"]] = np.nan

    with loaded_engine.begin() as connection:
        summary = store_expectations(connection, DATASET, gappy, info)

    assert summary.rows == len(frame) - 10


def test_meters_outside_the_dataset_are_refused_and_nothing_changes(
    loaded_engine: Engine, computed: tuple[pd.DataFrame, ExpectationInfo]
) -> None:
    frame, info = computed
    with loaded_engine.begin() as connection:
        store_expectations(connection, DATASET, frame, info)
    stray = frame.copy()
    stray.loc[stray.index[0], "meter_id"] = "nope-electricity"

    with pytest.raises(ValueError, match="not in dataset"), loaded_engine.begin() as connection:
        store_expectations(connection, DATASET, stray, info)

    assert count(loaded_engine) == len(frame)


def test_an_unknown_dataset_is_refused(
    migrated_engine: Engine, computed: tuple[pd.DataFrame, ExpectationInfo]
) -> None:
    frame, info = computed

    with pytest.raises(ValueError, match="no meters"), migrated_engine.begin() as connection:
        store_expectations(connection, "nothing", frame, info)


def test_the_command_line_needs_a_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from wattwise.core.config import get_settings

    monkeypatch.delenv("WATTWISE_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        code = main(["--dataset-id", "x", "--data", str(tmp_path)])
    finally:
        get_settings.cache_clear()

    assert code == 1


def test_the_command_line_needs_a_promoted_model(
    monkeypatch: pytest.MonkeyPatch,
    prepared: tuple[Path, Path, pd.DataFrame],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from wattwise.core.config import get_settings

    monkeypatch.setenv("WATTWISE_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    get_settings.cache_clear()
    try:
        code = main(
            ["--dataset-id", "x", "--data", str(prepared[1]), "--root", str(tmp_path / "none")]
        )
    finally:
        get_settings.cache_clear()

    assert code == 1
    assert "promoted" in capsys.readouterr().err
