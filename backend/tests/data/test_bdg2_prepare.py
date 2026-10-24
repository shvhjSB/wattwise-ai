import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd
import pytest

from tests.data.conftest import SiteSpec
from wattwise.data.bdg2_prepare import Options, Prepared, Reason, Variant, main, prepare, write
from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER
from wattwise.data.time_convention import Clock
from wattwise.data.validation import validate

Builder = Callable[[Sequence[SiteSpec]], Path]
SITES: Sequence[SiteSpec] = (
    ("Std", "US/Eastern", Clock.STANDARD, 3, False),
    ("Wall", "US/Pacific", Clock.WALL_CLOCK, 3, False),
    ("Undet", "Europe/London", Clock.WALL_CLOCK, 2, False),
)
CLOCKS = {"Std": Clock.STANDARD, "Wall": Clock.WALL_CLOCK, "Undet": Clock.UNDETERMINED}
WEATHER_CLOCKS = dict.fromkeys(CLOCKS, Clock.STANDARD)
ALL = Options(sample_meters=0)


def run(raw: Path, options: Options = ALL) -> Prepared:
    return prepare(raw, options, electricity_clocks=CLOCKS, weather_clocks=WEATHER_CLOCKS)


def raw_value(raw: Path, building: str, naive: str) -> float:
    wide = pd.read_csv(
        raw / "meters" / "cleaned" / "electricity_cleaned.csv", index_col="timestamp"
    )
    return float(wide.loc[[naive], building].to_numpy(dtype=float)[0])


def reading_at(prepared: Prepared, building: str, utc: str) -> float:
    r = prepared.readings
    row = r[(r["building_id"] == building) & (r["timestamp"] == pd.Timestamp(utc))]
    assert len(row) == 1, (building, utc)
    return float(row["value"].iloc[0])


def reasons(prepared: Prepared) -> dict[str, set[str]]:
    log = prepared.exclusions
    return {r.value: set(log.loc[log["reason"] == r.value, "building_id"]) for r in Reason}


# ---------------------------------------------------------------------------
# Conversion to UTC with each site's clock
# ---------------------------------------------------------------------------


def test_standard_time_sites_use_the_fixed_winter_offset(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)
    prepared = run(raw)

    for naive, utc in (("2016-01-15 12:00:00", "2016-01-15T17:00:00Z"),
                       ("2016-07-01 12:00:00", "2016-07-01T17:00:00Z")):  # fmt: skip
        assert reading_at(prepared, "Std_office_B1", utc) == raw_value(raw, "Std_office_B1", naive)


def test_wall_clock_sites_follow_daylight_saving(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)
    prepared = run(raw)

    for naive, utc in (("2016-01-15 12:00:00", "2016-01-15T20:00:00Z"),
                       ("2016-07-01 12:00:00", "2016-07-01T19:00:00Z")):  # fmt: skip
        assert reading_at(prepared, "Wall_office_B1", utc) == raw_value(
            raw, "Wall_office_B1", naive
        )


def test_unconvertible_wall_clock_hours_are_dropped_and_counted(make_bdg2_raw: Builder) -> None:
    prepared = run(make_bdg2_raw(SITES))
    per_meter = prepared.readings.groupby("building_id").size()

    assert prepared.stats["dropped_unconvertible_hours_by_site"] == {"Std": 0, "Wall": 4}
    assert per_meter["Std_office_B0"] == 17_544
    assert per_meter["Wall_office_B0"] == 17_544 - 4  # 2 non-existent + 2 repeated hours


def test_weather_is_converted_with_its_own_clock(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)
    prepared = run(raw)
    source = pd.read_csv(raw / "weather" / "weather.csv")
    naive = source[(source["site_id"] == "Wall") & (source["timestamp"] == "2016-07-01 15:00:00")]
    weather = prepared.weather
    # Weather is standard time even at a wall-clock electricity site: fixed -8 h, not -7 h.
    row = weather[
        (weather["site_id"] == "Wall")
        & (weather["timestamp"] == pd.Timestamp("2016-07-01T23:00:00Z"))
    ]

    assert float(row["air_temperature_c"].iloc[0]) == float(naive["airTemperature"].iloc[0])
    assert prepared.stats["weather_join_coverage_pct"] == {"Std": 100.0, "Wall": 100.0}


# ---------------------------------------------------------------------------
# Exclusions and sampling
# ---------------------------------------------------------------------------


def test_every_exclusion_has_a_reason(make_bdg2_raw: Builder) -> None:
    prepared = run(make_bdg2_raw(SITES))
    found = reasons(prepared)

    assert found["undetermined_clock"] == {"Undet_office_B0", "Undet_office_B1"}
    assert found["not_electricity"] == {"Std_office_B0", "Wall_office_B0", "Undet_office_B0"}
    assert set(
        prepared.exclusions.loc[prepared.exclusions["reason"] == "not_electricity", "meter_type"]
    ) == {"hotwater"}
    assert prepared.stats["excluded_by_reason"] == {
        "not_electricity": 3,
        "no_metadata": 0,
        "undetermined_clock": 2,
        "insufficient_data": 0,
        "not_sampled": 0,
    }


def test_meters_without_metadata_are_excluded(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)
    path = raw / "metadata" / "metadata.csv"
    metadata = pd.read_csv(path)
    metadata[metadata["building_id"] != "Std_office_B2"].to_csv(path, index=False)

    prepared = run(raw)

    assert reasons(prepared)["no_metadata"] == {"Std_office_B2"}
    assert "Std_office_B2" not in set(prepared.buildings["building_id"])


def test_meters_with_too_little_data_are_excluded(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)
    path = raw / "meters" / "cleaned" / "electricity_cleaned.csv"
    wide = pd.read_csv(path)
    wide.loc[wide.index[: int(len(wide) * 0.7)], "Std_office_B2"] = None  # 30% left
    wide.to_csv(path, index=False)

    prepared = run(raw)

    assert reasons(prepared)["insufficient_data"] == {"Std_office_B2"}
    assert "Std_office_B2" not in set(prepared.readings["building_id"])


def test_sampling_is_seeded(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)

    first = run(raw, Options(sample_meters=2, seed=7))
    again = run(raw, Options(sample_meters=2, seed=7))

    sampled = set(first.buildings["building_id"])
    assert len(sampled) == 2
    assert sampled == set(again.buildings["building_id"])
    assert len(reasons(first)["not_sampled"]) == 6 - 2
    seeds = {
        frozenset(run(raw, Options(sample_meters=2, seed=s)).buildings["building_id"])
        for s in range(6)
    }
    assert len(seeds) > 1, "the seed changes the sample"


def test_no_eligible_meters_is_an_error(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(SITES)

    with pytest.raises(ValueError, match="No eligible electricity meters"):
        prepare(raw, ALL, electricity_clocks={}, weather_clocks=WEATHER_CLOCKS)


# ---------------------------------------------------------------------------
# Outputs (acceptance: identical inputs and seed give identical output hashes)
# ---------------------------------------------------------------------------


def test_outputs_are_byte_identical_across_runs(make_bdg2_raw: Builder, tmp_path: Path) -> None:
    raw = make_bdg2_raw(SITES)
    options = Options(sample_meters=3, seed=11)

    first = write(run(raw, options), raw, tmp_path / "a", inputs_verified=False)
    second = write(run(raw, options), raw, tmp_path / "b", inputs_verified=False)

    assert first == second


def test_outputs_satisfy_the_contracts(make_bdg2_raw: Builder, tmp_path: Path) -> None:
    raw = make_bdg2_raw(SITES)
    prepared = run(raw)
    write(prepared, raw, tmp_path, inputs_verified=False)

    for name, contract in (("readings", READINGS), ("buildings", BUILDINGS), ("weather", WEATHER)):
        frame = pd.read_parquet(tmp_path / f"{name}.parquet")
        report = validate(frame, contract)
        assert report.ok and report.warnings == (), name
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "readings.parquet"), prepared.readings)
    quality = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["valid"] is True
    assert quality["summary"]["meters"] == 6


def test_manifest_records_provenance_options_and_counts(
    make_bdg2_raw: Builder, tmp_path: Path
) -> None:
    raw = make_bdg2_raw(SITES)
    write(run(raw, Options(sample_meters=4, seed=3)), raw, tmp_path, inputs_verified=False)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["options"] == {
        "variant": "cleaned",
        "sample_meters": 4,
        "seed": 3,
        "min_coverage_pct": 50.0,
    }
    assert manifest["inputs_verified_against_pinned_checksums"] is False
    assert set(manifest["inputs"]) == {"metadata", "weather", "electricity_cleaned"}
    assert manifest["stats"]["sampled_meters"] == 4
    assert manifest["stats"]["eligible_meters"] == 6
    assert "start of each hourly interval" in manifest["assumptions"]["interval"]
    assert "removed outliers" in manifest["assumptions"]["variant"]
    assert manifest["outputs"]["readings.parquet"]["rows"] == manifest["stats"]["readings_rows"]
    assert "do not redistribute" in manifest["licence"]


def test_the_raw_variant_reads_the_raw_file(make_bdg2_raw: Builder, tmp_path: Path) -> None:
    raw = make_bdg2_raw(SITES)
    write(
        run(raw, Options(variant=Variant.RAW, sample_meters=0)),
        raw,
        tmp_path,
        inputs_verified=False,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["inputs"]) == {"metadata", "weather", "electricity_raw"}
    assert "not ground truth" in manifest["assumptions"]["variant"]


# ---------------------------------------------------------------------------
# Command line (uses the pinned real-site clocks)
# ---------------------------------------------------------------------------


def test_cli_verifies_inputs_against_the_pinned_checksums(
    make_bdg2_raw: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = make_bdg2_raw([("Eagle", "US/Eastern", Clock.STANDARD, 2, False)])

    assert main(["--raw", str(raw), "--output", str(tmp_path / "out")]) == 1
    assert "does not match the expected size and SHA-256" in capsys.readouterr().err


def test_cli_runs_with_real_site_names(make_bdg2_raw: Builder, tmp_path: Path) -> None:
    raw = make_bdg2_raw(
        [
            ("Eagle", "US/Eastern", Clock.STANDARD, 2, False),
            ("Bear", "US/Pacific", Clock.WALL_CLOCK, 2, False),
        ]
    )

    code = main(
        [
            "--raw",
            str(raw),
            "--output",
            str(tmp_path / "out"),
            "--sample-meters",
            "0",
            "--skip-input-verification",
        ]
    )

    assert code == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["stats"]["clock_by_sampled_site"] == {"Bear": "wall_clock", "Eagle": "standard"}
