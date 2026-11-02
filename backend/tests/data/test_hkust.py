import io
import json
import zipfile
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd
import pytest

from wattwise.data import hkust
from wattwise.data.acquisition import AcquisitionError

EPOCH = pd.Timestamp("1899-12-30")


def serial(local: str) -> float:
    return (pd.Timestamp(local) - EPOCH) / pd.Timedelta(days=1)


def workbook(rows: Sequence[tuple[float, float | None]]) -> bytes:
    """A workbook shaped like the authors': inline-string header, numeric cells, and empty
    inline-string cells for missing values."""
    cells = [
        '<row r="1"><c r="A1" s="1" t="inlineStr"><is><t>time</t></is></c>'
        '<c r="B1" s="1" t="inlineStr"><is><t>number</t></is></c></row>'
    ]
    for i, (time, value) in enumerate(rows, start=2):
        b = (
            f'<c r="B{i}" t="inlineStr" />'
            if value is None
            else f'<c r="B{i}" t="n"><v>{value}</v></c>'
        )
        cells.append(f'<row r="{i}"><c r="A{i}" s="2" t="n"><v>{time}</v></c>{b}</row>')
    sheet = f"<worksheet><sheetData>{''.join(cells)}</sheetData></worksheet>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def test_a_register_is_read_on_local_time_with_missing_cells() -> None:
    data = workbook([(serial("2022-01-01 00:00"), 10.0), (serial("2022-01-01 01:00"), None)])

    register = hkust.read_register(data)

    assert list(register.index) == [
        pd.Timestamp("2022-01-01 00:00"),
        pd.Timestamp("2022-01-01 01:00"),
    ]
    assert register.iloc[0] == 10.0
    assert np.isnan(register.iloc[1])


def register_on(hours: int, step: float = 2.0, start: str = "2022-01-01 00:00") -> pd.Series:
    index = pd.date_range(start, periods=hours + 1, freq="h")
    return pd.Series(100.0 + step * np.arange(hours + 1), index=index)


def test_hourly_consumption_is_the_register_difference_labelled_in_utc() -> None:
    hourly = hkust.hourly_consumption(register_on(3))

    first = hourly.kwh.dropna()
    assert first.tolist() == [2.0, 2.0, 2.0]
    # 00:00 in Hong Kong is 16:00 UTC the day before
    assert first.index[0] == pd.Timestamp("2021-12-31 16:00", tz="UTC")
    assert hourly.stats["valid_hours"] == 3
    assert hourly.stats["register_step_kwh"] == 2.0


def test_quarter_hour_registers_use_the_hour_boundaries() -> None:
    index = pd.date_range("2022-01-01 00:00", periods=9, freq="15min")
    register = pd.Series(np.arange(9, dtype=float), index=index)  # 1 kWh per quarter hour

    assert hkust.hourly_consumption(register).kwh.dropna().tolist() == [4.0, 4.0]


def test_a_reset_and_a_restart_jump_are_invalid_not_filled() -> None:
    register = register_on(400)
    register.iloc[200:] -= 1000.0  # a reset: one negative difference
    register.iloc[300:] += 1e6  # a restart jump: one huge difference

    hourly = hkust.hourly_consumption(register)

    assert hourly.stats["negative_hours"] == 1
    assert hourly.stats["spike_hours"] == 1
    assert hourly.stats["valid_hours"] == 398
    assert hourly.kwh.dropna().eq(2.0).all()


def test_the_metered_class_comes_from_the_brick_model() -> None:
    ttl = """
bldg:Manager_room a brick:Room ;
    brick:isMeteredBy bldg:Meter_D0155 .

bldg:Mc_Donald a brick:Room ;
    brick:isMeteredBy bldg:Meter_D0607,
        bldg:Meter_D0611 .

bldg:Switch_AN1 a brick:Switch ;
    brick:isMeteredBy bldg:Meter_D0868 .
"""
    assert hkust.metered_classes(ttl) == {
        "D0155": "Room",
        "D0607": "Room",
        "D0611": "Room",
        "D0868": "Switch",
    }


def test_meter_members_name_each_meter_once() -> None:
    names = [
        f"{hkust.CLEAN_PREFIX}T60/GUI_NO.D0601.xlsx",
        f"{hkust.CLEAN_PREFIX}T1440/GUI_NO.D0816.xlsx",
        "All Data/Raw Dataset/Time-series data/GUI_NO.D0601.xlsx",
    ]
    assert hkust.meter_members(names) == {
        "D0601": ("T60", names[0]),
        "D0816": ("T1440", names[1]),
    }
    with pytest.raises(ValueError, match="two tiers"):
        hkust.meter_members([*names, f"{hkust.CLEAN_PREFIX}T15/GUI_NO.D0601.xlsx"])


def test_prepare_keeps_hourly_meters_and_says_why_others_are_not_used(tmp_path: Path) -> None:
    hours = [
        (serial(str(t)), 100.0 + 3.0 * i)
        for i, t in enumerate(pd.date_range("2022-01-01", periods=49, freq="h"))
    ]
    zeros = [(serial(str(t)), 5.0) for t in pd.date_range("2022-01-01", periods=49, freq="h")]
    archive = tmp_path / "All_Data.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(
            hkust.METADATA_MEMBER,
            "bldg:Lab a brick:Room ;\n    brick:isMeteredBy bldg:Meter_D0001 .\n",
        )
        z.writestr(f"{hkust.CLEAN_PREFIX}T60/GUI_NO.D0001.xlsx", workbook(hours))
        z.writestr(f"{hkust.CLEAN_PREFIX}T60/GUI_NO.D0002.xlsx", workbook(zeros))
        z.writestr(f"{hkust.CLEAN_PREFIX}T1440/GUI_NO.D0003.xlsx", workbook(hours[:2]))

    summary = hkust.prepare(archive, tmp_path / "out")

    readings = pd.read_parquet(tmp_path / "out" / "readings.parquet")
    meters = pd.read_csv(tmp_path / "out" / "meters.csv")
    assert summary["meters_used"] == 1
    assert len(readings) == 48 and readings["value"].eq(3.0).all()
    assert isinstance(readings["timestamp"].dtype, pd.DatetimeTZDtype)
    assert str(readings["timestamp"].dtype.tz) == "UTC"
    reasons = dict(zip(meters["meter_id"], meters["reason"].fillna(""), strict=True))
    assert reasons == {
        "D0001": "",
        "D0002": "every valid hour is zero",
        "D0003": "daily data only (T1440)",
    }
    assert meters.set_index("meter_id").loc["D0001", "metered_class"] == "Room"


# --- weather -------------------------------------------------------------------------------


def payload(**override: object) -> bytes:
    times = [f"2022-01-01T{h:02d}:00" for h in range(4)]
    data: dict[str, object] = {
        "latitude": 22.25,
        "longitude": 114.25,
        "elevation": 50.0,
        "utc_offset_seconds": 0,
        "hourly_units": {name: unit for name, unit in hkust.WEATHER_VARIABLES},
        "hourly": {
            "time": times,
            "temperature_2m": [20.0, 21.0, 22.0, 23.0],
            "dew_point_2m": [15.0, 15.0, 15.0, None],
            "wind_speed_10m": [3.0, 3.0, 3.0, 3.0],
            "shortwave_radiation": [0.0, 100.0, 200.0, 300.0],
            "cloud_cover": [50, 50, 50, 50],
        },
    }
    data.update(override)
    return json.dumps(data).encode()


def test_weather_is_parsed_in_utc_with_radiation_moved_to_its_hour_start() -> None:
    weather, enrichment = hkust.parse_weather(payload())

    assert weather["timestamp"].iloc[0] == pd.Timestamp("2022-01-01 00:00", tz="UTC")
    assert weather["air_temperature_c"].tolist() == [20.0, 21.0, 22.0, 23.0]
    # the value labelled 01:00 is the mean over 00:00-01:00
    assert enrichment["ghi_w_m2_era5"].tolist()[:3] == [100.0, 200.0, 300.0]
    assert np.isnan(enrichment["ghi_w_m2_era5"].iloc[3])
    assert np.isnan(enrichment["relative_humidity_pct_derived"].iloc[3])
    assert set(weather["site_id"]) == {hkust.SITE_ID}


def test_weather_with_a_wrong_unit_is_rejected() -> None:
    units = {name: unit for name, unit in hkust.WEATHER_VARIABLES} | {"wind_speed_10m": "km/h"}

    with pytest.raises(ValueError, match="wind_speed_10m"):
        hkust.parse_weather(payload(hourly_units=units))


def test_weather_is_downloaded_once_then_verified(tmp_path: Path) -> None:
    seen: list[str] = []

    @contextmanager
    def opener(url: str, timeout: float) -> Generator[BinaryIO]:
        seen.append(url)
        yield io.BytesIO(payload())

    path, manifest = tmp_path / "era5.json", tmp_path / "manifest.json"
    now = datetime(2026, 11, 2, tzinfo=UTC)

    assert hkust.fetch_weather(path, manifest, opener=opener, now=now) == "downloaded"
    assert hkust.fetch_weather(path, manifest, opener=opener, now=now) == "verified"
    assert len(seen) == 1 and "models=era5" in seen[0]
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert record["local_path"] == "data/raw/hkust/era5.json"
    path.write_bytes(b"changed")
    with pytest.raises(AcquisitionError, match="does not match"):
        hkust.fetch_weather(path, manifest, opener=opener, now=now)


def test_the_command_line_explains_a_missing_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hkust.main(["prepare", "--archive", str(tmp_path / "none.zip")]) == 1
    assert "wattwise.data.dryad fetch hkust" in capsys.readouterr().err
