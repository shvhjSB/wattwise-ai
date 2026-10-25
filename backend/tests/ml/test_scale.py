"""T042 full-scale tools: the quality mask, the batched feature store and full-scale baselines,
on small synthetic data."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.scale import (
    MASK_FLATLINE_HOURS,
    build_store,
    full_scale_baselines,
    load_store,
    main,
    mask_summary,
    quality_mask,
)

T0 = pd.Timestamp("2017-01-02T00:00Z")


def meter(values: list[float], meter_id: str = "m1", start: pd.Timestamp = T0) -> pd.DataFrame:
    times = pd.date_range(start, periods=len(values), freq="h").as_unit("us")
    return pd.DataFrame({"timestamp": times, "meter_id": meter_id, "value": values})


def varying(n: int) -> list[float]:
    return [10.0 + (i % 5) for i in range(n)]


def test_negative_readings_are_masked() -> None:
    rows = meter([5.0, -1.0, 5.5, 6.0])

    assert quality_mask(rows).tolist() == [True, False, True, True]


def test_zero_runs_are_masked_from_the_quality_engines_length() -> None:
    long_run = meter(varying(3) + [0.0] * 24 + varying(3))
    short_run = meter(varying(3) + [0.0] * 23 + varying(3))

    assert quality_mask(long_run).sum() == 6
    assert quality_mask(short_run).all()


def test_a_whole_day_of_identical_readings_is_masked_but_shorter_runs_are_kept() -> None:
    day = meter(varying(4) + [7.25] * 24 + varying(4))
    shorter = meter(varying(4) + [7.25] * 23 + varying(4))

    assert quality_mask(day).tolist() == [True] * 4 + [False] * 24 + [True] * 4
    assert quality_mask(shorter).all(), "steady loads on coarse meters repeat for hours"
    assert MASK_FLATLINE_HOURS == 24
    assert quality_mask(meter(varying(2) + [7.25] * 6 + varying(2)), flatline_hours=6).sum() == 4


def test_runs_do_not_cross_gaps_or_meters_and_missing_readings_are_not_usable() -> None:
    first = meter([7.25] * 3)
    after_gap = meter([7.25] * 3, start=T0 + pd.Timedelta(hours=4))  # one hour missing
    other = meter([7.25] * 3, meter_id="m2", start=T0 + pd.Timedelta(hours=3))
    rows = pd.concat([first, after_gap, other, meter([np.nan], start=T0 + pd.Timedelta(hours=9))])

    ok = quality_mask(rows.reset_index(drop=True))

    assert ok.tolist() == [True] * 9 + [False]


def test_the_mask_does_not_depend_on_row_order() -> None:
    rows = pd.concat(
        [meter(varying(5) + [3.0] * 28 + [0.0] * 30), meter(varying(40), "m2")], ignore_index=True
    )
    shuffled = rows.sample(frac=1.0, random_state=1)

    expected = quality_mask(rows)
    again = pd.Series(quality_mask(shuffled), index=shuffled.index).loc[rows.index]

    assert again.tolist() == expected.tolist()
    summary = mask_summary(rows, expected)
    assert summary["masked"] == 28 + 30 and summary["meters_with_masked_readings"] == 1


def test_a_batched_store_has_exactly_the_in_memory_features(tmp_path: Path) -> None:
    readings, weather = synthetic()

    manifest = build_store(
        readings, BUILDINGS, weather, None, tmp_path, batch_meters=1, log=lambda _: None
    )
    store = load_store(tmp_path)

    assert manifest["meters"] == 3 and len(manifest["parts"]) == 3
    assert manifest["rows"] == len(readings) == len(store)
    whole = features_of(readings, weather).astype("float32")
    merged = (
        readings[["meter_id", "timestamp"]]
        .join(whole)
        .merge(store, on=["meter_id", "timestamp"], suffixes=("", "_store"))
    )
    for column in whole.columns:
        np.testing.assert_array_equal(
            merged[column].to_numpy(), merged[f"{column}_store"].to_numpy()
        )
    assert "quality_ok" not in store.columns, "the mask is policy, not stored"
    assert set(
        load_store(tmp_path, columns=["meter_id", "value"], meters=["A-electricity"])["meter_id"]
    ) == {"A-electricity"}


def test_a_tampered_or_outdated_store_is_refused(tmp_path: Path) -> None:
    readings, weather = synthetic()
    build_store(readings, BUILDINGS, weather, None, tmp_path, batch_meters=2, log=lambda _: None)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    part = tmp_path / manifest["parts"][0]["file"]
    part.write_bytes(part.read_bytes() + b"x")
    with pytest.raises(ValueError, match="SHA-256"):
        load_store(tmp_path)

    manifest["feature_set"]["feature_set_version"] = "0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="another feature set"):
        load_store(tmp_path)


def test_full_scale_baselines_score_all_rows_and_quality_rows(tmp_path: Path) -> None:
    readings, _ = synthetic()
    stuck = (readings["building_id"] == "C") & (
        readings["timestamp"].between(
            pd.Timestamp("2017-03-25T00:00Z"), pd.Timestamp("2017-03-26T23:00Z")
        )
    )
    readings.loc[stuck, "value"] = 9.0  # a 48-hour flatline in the test window, masked

    result = full_scale_baselines(readings, BUILDINGS, tmp_path, SPLIT)

    all_rows = result["all_rows"]["seasonal-naive-1w"]["test"]
    quality = result["quality_rows"]["seasonal-naive-1w"]["test"]
    assert quality["scored"] < all_rows["scored"]
    assert result["quality_mask"]["masked"] == 48
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "all_rows" / "seasonal-naive-1w.json").exists()


def test_the_command_line_builds_a_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readings, weather = synthetic()
    folder = tmp_path / "data"
    folder.mkdir()
    readings.to_parquet(folder / "readings.parquet")
    BUILDINGS.to_parquet(folder / "buildings.parquet")
    weather.to_parquet(folder / "weather.parquet")

    assert main(["features", "--data", str(folder), "--store", str(tmp_path / "store")]) == 0
    assert "3 meters" in capsys.readouterr().out
    assert main(["baselines", "--data", str(tmp_path / "missing")]) == 1
