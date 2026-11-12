"""HIPE: the pinned source, gridding rules and preparation, on a tiny archive in HIPE's format."""

import dataclasses
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd
import pytest

from wattwise.data import hipe
from wattwise.data.acquisition import AcquisitionError, FileStatus

HEADER = "SensorDateTime,Machine,PhaseCount,T_h,V1_V,P_kW,Q_kvar,S_kVA,E_PP_kWh,E_PN_kWh,Extra"
SUFFIX = "_geq_2017-10-23_lt_2017-10-30.csv"


def member(meter: str, phases: int = 3) -> str:
    return f"{meter}_PhaseCount_{phases}{SUFFIX}"


def csv(meter: str, rows: list[tuple[str, float]], register: tuple[float, float] = (0, 0)) -> str:
    """(local timestamp with offset, kW) rows; the registers are constant unless given."""
    lines = [HEADER]
    for i, (stamp, power) in enumerate(rows):
        forward = register[0] if i == len(rows) - 1 else 0
        reverse = register[1] if i == len(rows) - 1 else 0
        lines.append(
            f"{stamp},{meter},3,1.0,230.0,{power},{power / 2},{power * 1.1},{forward},{reverse},x"
        )
    return "\n".join(lines) + "\n"


def steady(power: float, seconds: int = 120) -> list[tuple[str, float]]:
    """One sample every 5 s from 00:00:02 local (+02), all at `power`."""
    base = pd.Timestamp("2017-10-23T00:00:02")
    return [
        ((base + pd.Timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S.000") + "+02", power)
        for s in range(0, seconds, 5)
    ]


def archive(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as handle:
        for name, text in files.items():
            handle.writestr(name, text)
    return path


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    """A main terminal at 10 kW with two machines at 1 kW and 3 kW: 40 % explained."""
    return archive(
        tmp_path / "hipe.zip",
        {
            member(hipe.MAIN): csv(hipe.MAIN, steady(10.0), register=(1.0, 0.0)),
            member("Oven"): csv("Oven", steady(3.0)),
            member("Pump", phases=2): csv("Pump", steady(1.0), register=(0.0, 2.0)),
            "README.txt": "not a meter",
        },
    )


# -- the pinned source ----------------------------------------------------------------------


def test_the_archives_are_pinned_to_one_zenodo_record_with_all_three_checks() -> None:
    assert [a.remote.key for a in hipe.ARCHIVES] == ["week", "full"]
    for item in hipe.ARCHIVES:
        prefix = f"https://zenodo.org/api/records/{hipe.ZENODO_RECORD}/files/"
        assert item.remote.url == f"{prefix}{item.remote.local_path}/content"
        assert f"v{hipe.VERSION}" in item.remote.local_path
        assert item.remote.size > 0
        assert re.fullmatch(r"[0-9a-f]{32}", item.md5)
        assert re.fullmatch(r"[0-9a-f]{64}", item.remote.sha256)
        assert set(item.remote.sha256) != {"0"}  # never a placeholder
    assert hipe.DOI.endswith(hipe.ZENODO_RECORD)
    assert "CC BY 4.0" in hipe.CITATION and "10.1145/3208903.3210278" in hipe.CITATION


class FakeZenodo:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.requests: list[str] = []

    @contextmanager
    def __call__(self, url: str, timeout: float) -> Generator[BinaryIO]:
        self.requests.append(url)
        yield io.BytesIO(self.bodies[url])


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Small stand-ins for the archives, with their real sizes and checksums recomputed."""
    bodies = {a.remote.key: f"fake {a.remote.key}".encode() * 20 for a in hipe.ARCHIVES}
    replaced = tuple(
        dataclasses.replace(
            a,
            md5=hashlib.md5(bodies[a.remote.key], usedforsecurity=False).hexdigest(),
            remote=dataclasses.replace(
                a.remote,
                size=len(bodies[a.remote.key]),
                sha256=hashlib.sha256(bodies[a.remote.key]).hexdigest(),
            ),
        )
        for a in hipe.ARCHIVES
    )
    monkeypatch.setattr(hipe, "ARCHIVES", replaced)
    monkeypatch.setattr(hipe, "ARCHIVES_BY_KEY", {a.remote.key: a for a in replaced})
    return {a.remote.url: bodies[a.remote.key] for a in replaced}


def test_fetch_verifies_and_records_provenance(tmp_path: Path, fakes: dict[str, bytes]) -> None:
    zenodo = FakeZenodo(fakes)
    manifest = tmp_path / "manifests" / "hipe.json"
    first = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

    results = hipe.fetch(["week"], tmp_path / "raw", manifest, opener=zenodo, now=first)

    assert [r.status for r in results] == [FileStatus.DOWNLOADED]
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert recorded["licence"] == "CC BY 4.0" and recorded["doi"] == hipe.DOI
    ((name, entry),) = recorded["files"].items()
    week = hipe.ARCHIVES_BY_KEY["week"]
    assert name == week.remote.local_path
    assert entry["sha256"] == week.remote.sha256 and entry["zenodo_md5"] == week.md5
    assert entry["obtained_at"] == "2026-11-11T12:00:00Z"

    later = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    again = hipe.fetch(["week", "full"], tmp_path / "raw", manifest, opener=zenodo, now=later)
    assert [r.status for r in again] == [FileStatus.VERIFIED, FileStatus.DOWNLOADED]
    files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    assert files[name]["obtained_at"] == "2026-11-11T12:00:00Z"  # kept: only verified again
    assert files[name]["last_verified_at"] == "2026-11-12T09:00:00Z"
    assert len(zenodo.requests) == 2  # the verified file was not downloaded again
    assert all(hipe.verify_local(tmp_path / "raw").values())


def test_a_file_that_disagrees_with_zenodos_md5_is_refused(
    tmp_path: Path, fakes: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    week = hipe.ARCHIVES_BY_KEY["week"]
    wrong = dataclasses.replace(week, md5="0" * 32)
    monkeypatch.setattr(hipe, "ARCHIVES_BY_KEY", {**hipe.ARCHIVES_BY_KEY, "week": wrong})

    with pytest.raises(AcquisitionError, match="Zenodo publishes"):
        hipe.fetch(["week"], tmp_path / "raw", tmp_path / "m.json", opener=FakeZenodo(fakes))
    assert not (tmp_path / "m.json").exists()


# -- reading and gridding -------------------------------------------------------------------


def test_members_are_recognised_by_the_authors_file_names() -> None:
    names = [member("ChipPress"), member("ScreenPrinter", 2), "README.txt", "x/" + member("A")]

    assert hipe.meter_members(names) == {
        "ChipPress": (member("ChipPress"), 3),
        "ScreenPrinter": (member("ScreenPrinter", 2), 2),
    }


def test_samples_are_read_in_utc_sorted_with_both_registers_added(tmp_path: Path) -> None:
    rows = [
        ("2017-10-29T02:00:01.500+01", 2.0),  # after the clocks went back: 01:00:01.5 UTC
        ("2017-10-29T02:59:55.000+02", 1.0),  # before: 00:59:55 UTC
        ("2017-10-29T02:59:55.000+02", 9.0),  # the same instant again: dropped
    ]
    path = archive(tmp_path / "a.zip", {member("Pump"): csv("Pump", rows, register=(3.0, 4.0))})

    samples = hipe.read_samples(zipfile.ZipFile(path), member("Pump"))

    assert list(samples.columns) == [
        "timestamp",
        "p_kw",
        "q_kvar",
        "s_kva",
        "forward_kwh",
        "reverse_kwh",
    ]
    assert samples["timestamp"].tolist() == [
        pd.Timestamp("2017-10-29T00:59:55Z"),
        pd.Timestamp("2017-10-29T01:00:01.5Z"),
    ]
    assert samples["p_kw"].tolist() == [1.0, 2.0]
    assert samples["q_kvar"].tolist() == [0.5, 1.0]
    assert samples["forward_kwh"].tolist() == [0.0, 0.0]  # the last row was the dropped one


def test_counters_add_increments_count_rollovers_and_ignore_resets() -> None:
    plain = np.array([10.0, 10.0, 11.0, 13.0])
    rolled = np.array([65_534.0, 65_535.0, 0.0, 2.0])  # the main terminal's 16-bit rollover
    reset = np.array([500.0, 502.0, 3.0, 4.0])  # a drop that is not a rollover

    assert hipe.counter_kwh(plain) == (3.0, 0, 0)
    assert hipe.counter_kwh(rolled) == (4.0, 1, 0)
    assert hipe.counter_kwh(reset) == (3.0, 0, 1)


def grid_of(points: list[tuple[str, float]]) -> pd.DataFrame:
    stamps = pd.to_datetime([p[0] for p in points], utc=True)
    values = [p[1] for p in points]
    return pd.DataFrame({"timestamp": stamps, "p_kw": values, "q_kvar": values, "s_kva": values})


def test_the_grid_averages_the_samples_in_a_bin_and_never_fills_one() -> None:
    samples = grid_of(
        [
            ("2017-10-23T00:00:03Z", 1.0),
            ("2017-10-23T00:00:08Z", 3.0),
            ("2017-10-23T00:00:14Z", 5.0),
            ("2017-10-23T00:00:41Z", 7.0),  # 00:00:20 and 00:00:30 have no sample
        ]
    )

    grid = hipe.to_grid(samples)

    assert grid["timestamp"].tolist() == [
        pd.Timestamp("2017-10-23T00:00:00Z"),
        pd.Timestamp("2017-10-23T00:00:10Z"),
        pd.Timestamp("2017-10-23T00:00:40Z"),
    ]
    assert grid["p_kw"].tolist() == [2.0, 5.0, 7.0]
    assert grid["samples"].tolist() == [2, 1, 1]
    assert hipe.grid_kwh(grid) == pytest.approx(14.0 * 10 / 3600)


def test_coarser_grids_average_the_fine_bins_and_say_how_many_were_present() -> None:
    grid = hipe.to_grid(
        grid_of(
            [
                ("2017-10-23T00:00:01Z", 1.0),
                ("2017-10-23T00:00:11Z", 2.0),
                ("2017-10-23T00:00:21Z", 3.0),  # three of the first minute's six bins
                ("2017-10-23T00:01:05Z", 8.0),  # one of the second minute's
            ]
        )
    )

    minute = hipe.coarsen(grid, 60)

    assert minute["p_kw"].tolist() == [2.0, 8.0]
    assert minute["coverage"].tolist() == pytest.approx([0.5, 1 / 6])
    with pytest.raises(ValueError, match="multiple"):
        hipe.coarsen(grid, 25)


def test_plant_statistics_use_only_bins_where_every_meter_has_a_value() -> None:
    def flat(power: float, stamps: list[str]) -> pd.DataFrame:
        return pd.DataFrame({"timestamp": pd.to_datetime(stamps, utc=True), "p_kw": power})

    both = ["2017-10-23T00:00:00Z", "2017-10-23T00:00:10Z"]
    stats = hipe.plant_stats(
        {
            hipe.MAIN: flat(10.0, [*both, "2017-10-23T00:00:20Z"]),
            "Oven": flat(3.0, both),
            "Pump": flat(1.0, [*both, "2017-10-23T00:00:30Z"]),
        }
    )

    assert stats["common_bins"] == 2
    assert stats["explained_share"] == 0.4
    assert stats["machine_shares_of_main"] == {"Oven": 0.3, "Pump": 0.1}
    assert stats["unmetered_kw"]["mean"] == 6.0
    assert stats["unmetered_kw"]["share_of_bins_below_zero"] == 0.0


# -- preparation ----------------------------------------------------------------------------


def test_preparation_writes_every_resolution_and_a_quality_report(
    plant: Path, tmp_path: Path
) -> None:
    summary = hipe.prepare(plant, tmp_path / "out")

    assert list(summary["meters"]) == [hipe.MAIN, "Oven", "Pump"]
    assert summary["plant"]["explained_share"] == 0.4
    main = summary["meters"][hipe.MAIN]
    assert main["samples"] == 24 and main["grid_bins"] == 12 and main["grid_coverage"] == 1.0
    assert main["median_interval_s"] == 5.0 and main["gaps_over_60s"] == 0
    assert main["energy_kwh"] == round(10.0 * 120 / 3600, 2)
    assert main["counter_kwh"] == 1.0 and main["counter_rollovers"] == 0
    assert summary["meters"]["Pump"]["counter_kwh"] == 2.0  # counted in the reverse direction
    assert not any(m["counter_disagrees"] for m in summary["meters"].values())  # under 20 kWh
    assert summary["meters"]["Pump"]["phases"] == 2

    fine = pd.read_parquet(tmp_path / "out" / "power_10s.parquet")
    assert list(fine.columns) == ["meter_id", "timestamp", "p_kw", "q_kvar", "s_kva", "samples"]
    assert fine.groupby("meter_id")["p_kw"].mean().to_dict() == {
        hipe.MAIN: 10.0,
        "Oven": 3.0,
        "Pump": 1.0,
    }
    assert str(fine["timestamp"].dt.tz) == "UTC"
    assert fine["timestamp"].min() == pd.Timestamp("2017-10-22T22:00:00Z")  # 00:00 local, +02
    hourly = pd.read_parquet(tmp_path / "out" / "power_1h.parquet")
    assert len(hourly) == 3 and hourly["coverage"].tolist() == pytest.approx([12 / 360] * 3)
    for name in ("power_1min.parquet", "power_15min.parquet", "summary.json"):
        assert (tmp_path / "out" / name).exists()
    report = (tmp_path / "out" / "quality.md").read_text(encoding="utf-8")
    assert "**Real data.**" in report and "CC BY 4.0" in report
    assert "**40.0% of the main terminal**" in report


def test_an_archive_without_the_main_terminal_is_not_prepared(tmp_path: Path) -> None:
    path = archive(tmp_path / "other.zip", {member("Oven"): csv("Oven", steady(1.0))})

    with pytest.raises(ValueError, match="not a HIPE archive"):
        hipe.prepare(path, tmp_path / "out")


def test_canonical_readings_are_hourly_kwh_and_thin_hours_are_missing(tmp_path: Path) -> None:
    hourly = pd.DataFrame(
        {
            "meter_id": ["Oven", "Oven"],
            "timestamp": pd.to_datetime(["2017-10-23T00:00Z", "2017-10-23T01:00Z"], utc=True),
            "p_kw": [3.0, 5.0],
            "q_kvar": [0.0, 0.0],
            "s_kva": [3.0, 5.0],
            "coverage": [0.95, 0.5],  # the second hour is too thin to be a reading
        }
    )
    hourly.to_parquet(tmp_path / "power_1h.parquet", index=False)

    buildings, readings = hipe.canonical(tmp_path)

    assert readings["meter_id"].tolist() == ["hipe:Oven", "hipe:Oven"]
    assert readings["value"].tolist()[0] == 3.0  # kW for one hour is kWh
    assert pd.isna(readings["value"].tolist()[1])
    assert set(readings["building_id"]) == {hipe.BUILDING_ID}
    assert buildings["timezone"].tolist() == [hipe.SITE_TIMEZONE]
    folder = hipe.write_canonical(tmp_path)
    loaded = pd.read_parquet(folder / "readings.parquet")
    assert len(loaded) == 2 and str(loaded["timestamp"].dt.tz) == "UTC"
    assert (folder / "buildings.parquet").exists()


# -- command line ---------------------------------------------------------------------------


def test_the_command_line_lists_the_archives_and_explains_a_missing_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hipe.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "week:" in listed and "full:" in listed

    assert hipe.main(["prepare", "--archive", "full", "--raw", str(tmp_path)]) == 1
    assert "wattwise.data.hipe fetch --full" in capsys.readouterr().err
    assert hipe.main(["verify", "--raw", str(tmp_path)]) == 1  # nothing downloaded there
