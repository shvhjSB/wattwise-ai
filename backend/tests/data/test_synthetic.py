import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER, TableContract
from wattwise.data.csv_io import read_csv
from wattwise.data.synthetic import (
    DEFAULT_SEED,
    FILES,
    LABEL_SOURCE,
    NOTICE,
    SYNTHETIC_BUILDINGS,
    SYNTHETIC_SITES,
    AnomalyType,
    SyntheticDataset,
    generate,
    main,
    write,
)

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "sample" / "synthetic"
ALL_FILES = (*FILES, "manifest.json")


@pytest.fixture(scope="module")
def dataset() -> SyntheticDataset:
    return generate(DEFAULT_SEED)


def window_mask(frame: pd.DataFrame, meter_id: str, start: object, end: object) -> np.ndarray:
    selected = (frame["meter_id"] == meter_id) & (frame["timestamp"] >= start)
    return (selected & (frame["timestamp"] < end)).to_numpy(dtype=bool)


def label(dataset: SyntheticDataset, anomaly_type: AnomalyType) -> pd.Series:
    rows = dataset.labels[dataset.labels["anomaly_type"] == anomaly_type.value]
    assert len(rows) == 1
    return rows.iloc[0]


# ---------------------------------------------------------------------------
# Reproducibility (acceptance: same seed, byte-identical output)
# ---------------------------------------------------------------------------


def test_committed_fixture_is_exactly_reproducible(tmp_path: Path) -> None:
    write(generate(DEFAULT_SEED), tmp_path)

    assert sorted(p.name for p in FIXTURE.iterdir()) == sorted(ALL_FILES)
    for name in ALL_FILES:
        assert (tmp_path / name).read_bytes() == (FIXTURE / name).read_bytes(), name


def test_same_seed_gives_byte_identical_files(tmp_path: Path) -> None:
    first = write(generate(7), tmp_path / "first")
    second = write(generate(7), tmp_path / "second")

    assert first == second


def test_the_seed_changes_noise_but_not_the_scenario(dataset: SyntheticDataset) -> None:
    other = generate(DEFAULT_SEED + 1)

    assert not other.readings["value"].equals(dataset.readings["value"])
    pd.testing.assert_frame_equal(other.labels, dataset.labels)
    pd.testing.assert_frame_equal(other.buildings, dataset.buildings)


def test_manifest_records_the_committed_files() -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["seed"] == DEFAULT_SEED
    assert set(manifest["files"]) == set(FILES)
    for name, entry in manifest["files"].items():
        data = (FIXTURE / name).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), name
        assert entry["bytes"] == len(data), name


# ---------------------------------------------------------------------------
# Contract and size (acceptance: conforms to T005, under 1 MB)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "contract"),
    [("readings.csv", READINGS), ("buildings.csv", BUILDINGS), ("weather.csv", WEATHER)],
)
def test_fixture_files_satisfy_the_contract(name: str, contract: TableContract) -> None:
    report = read_csv(FIXTURE / name, contract).report

    assert report.ok, report.errors
    assert report.warnings == ()


def test_reading_the_files_back_gives_the_generated_tables(dataset: SyntheticDataset) -> None:
    for name, contract, expected in (
        ("readings.csv", READINGS, dataset.readings),
        ("buildings.csv", BUILDINGS, dataset.buildings),
        ("weather.csv", WEATHER, dataset.weather),
    ):
        frame = read_csv(FIXTURE / name, contract).frame
        assert frame is not None
        pd.testing.assert_frame_equal(frame, expected)


def test_fixture_is_smaller_than_one_megabyte() -> None:
    assert sum(p.stat().st_size for p in FIXTURE.iterdir()) < 1_000_000


# ---------------------------------------------------------------------------
# Labels (acceptance: labels exist only for injected events)
# ---------------------------------------------------------------------------


def test_labels_cover_exactly_the_injected_changes(dataset: SyntheticDataset) -> None:
    observed, clean = dataset.readings, dataset.clean_readings
    pd.testing.assert_frame_equal(observed.drop(columns="value"), clean.drop(columns="value"))
    o, c = observed["value"].to_numpy(), clean["value"].to_numpy()
    changed = ~((o == c) | (np.isnan(o) & np.isnan(c)))

    inside_a_label = np.zeros(len(observed), dtype=bool)
    for event in dataset.labels.itertuples():
        window = window_mask(observed, str(event.meter_id), event.start, event.end)
        assert (changed & window).any(), f"{event.event_id} changed nothing"
        inside_a_label |= window

    assert changed.any()
    assert not (changed & ~inside_a_label).any(), "a reading changed outside every label"


def test_labels_are_marked_synthetic_and_cover_each_anomaly_type_once(
    dataset: SyntheticDataset,
) -> None:
    assert (dataset.labels["label_source"] == LABEL_SOURCE).all()
    assert sorted(dataset.labels["anomaly_type"]) == sorted(t.value for t in AnomalyType)
    assert NOTICE in (FIXTURE / "README.md").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["notice"] == NOTICE


def test_nothing_looks_like_a_real_building(dataset: SyntheticDataset) -> None:
    ids = [b.building_id for b in SYNTHETIC_BUILDINGS] + [s.site_id for s in SYNTHETIC_SITES]
    assert all(identifier.startswith("syn-") for identifier in ids)
    assert dataset.buildings[["latitude", "longitude"]].isna().all().all(), "no invented places"


# ---------------------------------------------------------------------------
# The documented behaviour of the model and the anomalies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("building_id", ["syn-office-a", "syn-office-d"])
def test_offices_follow_local_working_hours(dataset: SyntheticDataset, building_id: str) -> None:
    timezone = dataset.buildings.set_index("building_id").loc[building_id, "timezone"]
    meter = dataset.clean_readings[dataset.clean_readings["building_id"] == building_id]
    local = meter["timestamp"].dt.tz_convert(str(timezone))
    weekend = (local.dt.dayofweek >= 5).to_numpy()
    by_hour = meter.loc[~weekend, "value"].groupby(local[~weekend].dt.hour).mean()

    assert 9 <= by_hour.idxmax() <= 16, "weekday peak inside local working hours"
    assert meter.loc[weekend, "value"].mean() < 0.8 * meter.loc[~weekend, "value"].mean()


def test_daily_load_falls_as_temperature_rises(dataset: SyntheticDataset) -> None:
    sites = {s.site_id: s.timezone for s in SYNTHETIC_SITES}
    for building in SYNTHETIC_BUILDINGS:
        rows = dataset.clean_readings[dataset.clean_readings["building_id"] == building.building_id]
        load = rows.set_index("timestamp")["value"]
        weather = dataset.weather[dataset.weather["site_id"] == building.site_id]
        temperature = weather.set_index("timestamp")["air_temperature_c"]
        day = pd.DatetimeIndex(load.index).tz_convert(sites[building.site_id]).normalize()

        slope = np.polyfit(temperature.groupby(day).mean(), load.groupby(day).mean(), 1)[0]

        assert slope < 0, building.building_id
        assert slope == pytest.approx(-building.heating_kw_per_c, rel=0.3), building.building_id


def test_each_anomaly_has_its_documented_effect(dataset: SyntheticDataset) -> None:
    observed, clean = dataset.readings, dataset.clean_readings
    tolerance = 0.002  # both series are rounded to 0.001 kWh

    def values(anomaly_type: AnomalyType) -> tuple[np.ndarray, np.ndarray, pd.Series]:
        event = label(dataset, anomaly_type)
        window = window_mask(observed, str(event["meter_id"]), event["start"], event["end"])
        return observed["value"].to_numpy()[window], clean["value"].to_numpy()[window], event

    spiked, normal, event = values(AnomalyType.SPIKE)
    np.testing.assert_allclose(spiked, normal * event["effect_value"], atol=tolerance)

    excess, normal, event = values(AnomalyType.SUSTAINED_EXCESS)
    np.testing.assert_allclose(excess, normal * event["effect_value"], atol=tolerance)

    night, normal, event = values(AnomalyType.OVERNIGHT_BASELOAD)
    added = night - normal
    assert np.isclose(added, event["effect_value"], atol=tolerance).sum() == 70  # 10 h x 7 nights
    assert np.isclose(added, 0.0, atol=tolerance).sum() == 168 - 70

    drifted, normal, event = values(AnomalyType.GRADUAL_DRIFT)
    ratio = drifted / normal
    assert ratio[-1] == pytest.approx(event["effect_value"], abs=1e-4)
    assert np.all(np.diff(ratio) > -1e-4), "the drift only rises"

    stuck, _, _ = values(AnomalyType.FLATLINE)
    assert np.unique(stuck).size == 1

    gap, _, _ = values(AnomalyType.MISSING_DATA)
    assert np.isnan(gap).all()


def test_cli_writes_every_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--output", str(tmp_path), "--seed", "3"]) == 0

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(ALL_FILES)
    assert "readings.csv" in capsys.readouterr().out
