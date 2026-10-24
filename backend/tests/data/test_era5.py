import io
import json
import urllib.error
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd
import pytest

from tests.data.conftest import BDG2Builder
from wattwise.data.acquisition import AcquisitionError
from wattwise.data.era5 import (
    ATTRIBUTION,
    END_DATE,
    HUMIDITY_COLUMN,
    START_DATE,
    TERMS,
    VARIABLES,
    Response,
    Site,
    best_lag,
    content_sha256,
    enrich,
    equation_of_time_min,
    era5_table,
    fetch,
    located_sites,
    main,
    parse_response,
    relative_humidity,
    request_url,
    solar_noon_offsets,
    write,
)
from wattwise.data.time_convention import Clock

UNITS = {v.name: v.unit for v in VARIABLES} | {"time": "iso8601"}
SITE = Site("Test", 40.0, -75.0)


def clear_sky(interval_starts: pd.DatetimeIndex, longitude: float) -> np.ndarray:
    """Mean irradiance over each hour from a sky symmetric about true solar noon (W/m2)."""
    samples = np.arange(5, 60, 10)  # minutes into the hour
    totals = np.zeros(len(interval_starts))
    for minute in samples:
        t = interval_starts + pd.Timedelta(minutes=int(minute))
        solar_hours = (
            np.asarray(t.hour + t.minute / 60.0, dtype=float)
            + longitude / 15.0
            + equation_of_time_min(t) / 60.0
        )
        totals += 1000.0 * np.clip(np.cos(np.pi * (solar_hours - 12.0) / 12.0), 0.0, None) ** 1.5
    return totals / len(samples)


def payload(
    site: Site = SITE,
    *,
    start: str = "2016-01-01",
    days: int = 40,
    labels_are_interval_ends: bool = True,
    temperature: Callable[[pd.DatetimeIndex], np.ndarray] | None = None,
    generation_ms: float = 0.5,
    units: Mapping[str, str] = UNITS,
    offset: int = 0,
) -> bytes:
    """An Open-Meteo-style archive response. Real responses label radiation at the end of the
    averaged hour; labels_are_interval_ends=False builds a wrongly labelled one."""
    labels = pd.date_range(start, periods=24 * days, freq="h", tz="UTC")
    starts = labels - pd.Timedelta(hours=1) if labels_are_interval_ends else labels
    ghi = clear_sky(starts, site.longitude)
    temps = (
        temperature(labels)
        if temperature
        else 10 + 6 * np.cos(2 * np.pi * (np.asarray(labels.hour) - 20) / 24)
    )
    hourly = {
        "time": labels.strftime("%Y-%m-%dT%H:%M").tolist(),
        "shortwave_radiation": np.round(ghi, 1).tolist(),
        "direct_radiation": np.round(ghi * 0.7, 1).tolist(),
        "diffuse_radiation": np.round(ghi * 0.3, 1).tolist(),
        "direct_normal_irradiance": np.round(ghi * 1.2, 1).tolist(),
        "cloud_cover": [None] + [50] * (len(labels) - 1),  # a gap stays a gap
        "temperature_2m": np.round(temps, 2).tolist(),
    }
    body = {
        "latitude": site.latitude + 0.1,
        "longitude": site.longitude - 0.1,
        "generationtime_ms": generation_ms,
        "utc_offset_seconds": offset,
        "timezone": "GMT",
        "timezone_abbreviation": "GMT",
        "elevation": 50.0,
        "hourly_units": dict(units),
        "hourly": hourly,
    }
    return json.dumps(body).encode()


def observed_weather(response: Response, site_id: str = "Test") -> pd.DataFrame:
    """Canonical observed weather that matches the response's temperature exactly (lag 0)."""
    return pd.DataFrame(
        {
            "site_id": site_id,
            "timestamp": response.times,
            "air_temperature_c": response.values["temperature_2m"],
            "dew_temperature_c": response.values["temperature_2m"] - 5.0,
            "wind_speed_m_s": 2.0,
        }
    )


# ---------------------------------------------------------------------------
# Requests and responses
# ---------------------------------------------------------------------------


def test_the_request_pins_the_model_period_variables_and_utc() -> None:
    url = request_url(Site("Bear", 37.8719, -122.2607))

    assert url == request_url(Site("Bear", 37.8719, -122.2607)), "deterministic"
    for part in (
        "latitude=37.8719",
        "longitude=-122.2607",
        f"start_date={START_DATE}",
        f"end_date={END_DATE}",
        "models=era5",
        "timezone=GMT",
        "shortwave_radiation%2Cdirect_radiation",
    ):
        assert part in url


def test_sites_come_from_corrected_coordinates_and_unlocated_sites_are_left_out() -> None:
    metadata = pd.DataFrame(
        {
            "building_id": ["w1", "w2", "x1", "b1"],
            "site_id": ["Wolf", "Wolf", "Nowhere", "Bear"],
            "lat": [53.3498, 53.3498, None, 37.8719],
            "lng": [6.2603, 6.2603, None, -122.2607],
            "timezone": ["Europe/Dublin", "Europe/Dublin", "US/Eastern", "US/Pacific"],
        }
    )

    sites, applied = located_sites(metadata)

    assert sites == (Site("Bear", 37.8719, -122.2607), Site("Wolf", 53.3498, -6.2603))
    assert [c.site_id for c in applied] == ["Wolf"]
    spread = metadata.assign(lat=[53.3498, 53.0, np.nan, 37.8719])
    with pytest.raises(ValueError, match="different coordinates"):
        located_sites(spread)


def test_a_response_parses_with_gaps_kept_as_missing() -> None:
    response = parse_response(payload(days=2))

    assert str(response.times.tz) == "UTC"
    assert response.times[0] == pd.Timestamp("2016-01-01T00:00:00Z")
    assert np.isnan(response.values["cloud_cover"][0])
    assert (response.latitude, response.longitude, response.elevation_m) == (40.1, -75.1, 50.0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda: payload(days=1, offset=3600), "Expected UTC"),
        (lambda: payload(days=1, units={**UNITS, "shortwave_radiation": "J/m²"}), "expected unit"),
        (lambda: json.dumps({"error": True, "reason": "bad"}).encode(), "returned an error"),
    ],
)
def test_unexpected_responses_are_rejected(change: Callable[[], bytes], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_response(change())


def test_an_irregular_time_axis_is_rejected() -> None:
    body = json.loads(payload(days=1))
    body["hourly"]["time"][5] = body["hourly"]["time"][4]

    with pytest.raises(ValueError, match="regular hourly"):
        parse_response(json.dumps(body).encode())


def test_the_content_hash_ignores_the_server_timing_field_only() -> None:
    first, second = payload(days=2, generation_ms=0.4), payload(days=2, generation_ms=9.9)
    other = payload(days=3)

    assert content_sha256(first) == content_sha256(second)
    assert content_sha256(first) != content_sha256(other)


# ---------------------------------------------------------------------------
# Time conventions
# ---------------------------------------------------------------------------


def test_radiation_is_relabelled_to_the_start_of_its_hour_and_instants_are_not() -> None:
    response = parse_response(payload(days=2))

    table = era5_table("Test", response).set_index("timestamp")

    label = pd.Timestamp("2016-01-01T18:00:00Z")
    assert table.loc[label - pd.Timedelta(hours=1), "ghi_w_m2_era5"] == pytest.approx(
        response.values["shortwave_radiation"][18]
    )
    assert table.loc[label, "cloud_cover_pct_era5"] == response.values["cloud_cover"][18]
    assert np.isnan(table["ghi_w_m2_era5"].iloc[-1]), "the last hour's mean is not in the response"
    assert list(table.index) == list(response.times), "the requested hourly grid is kept"


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2016-02-11", -14.2), ("2016-04-15", 0.0), ("2016-11-03", 16.4), ("2017-07-26", -6.5)],
)
def test_the_equation_of_time_matches_known_values(day: str, expected: float) -> None:
    value = equation_of_time_min(pd.DatetimeIndex([pd.Timestamp(f"{day}T12:00:00Z")]))[0]

    assert value == pytest.approx(expected, abs=1.0)


def test_the_solar_noon_check_finds_correct_labels_and_a_one_hour_error() -> None:
    right = parse_response(payload(days=40, labels_are_interval_ends=True))
    wrong = parse_response(payload(days=40, labels_are_interval_ends=False))

    correct = solar_noon_offsets(
        era5_table("Test", right).set_index("timestamp")["ghi_w_m2_era5"], -75.0
    )
    mislabelled = solar_noon_offsets(
        era5_table("Test", wrong).set_index("timestamp")["ghi_w_m2_era5"], -75.0
    )

    assert abs(correct.median()) < 2.0
    assert mislabelled.median() == pytest.approx(-60.0, abs=2.0)
    assert len(correct) >= 38, "complete sunny days are used"


def test_best_lag_recovers_a_one_hour_delay() -> None:
    times = pd.date_range("2016-01-01", periods=24 * 20, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    reference = pd.Series(
        np.sin(np.arange(len(times)) / 3.7) + rng.normal(0, 0.1, len(times)), times
    )
    delayed = pd.Series(reference.to_numpy(), times + pd.Timedelta(hours=1))

    lag, best, at_zero = best_lag(reference, delayed)

    assert lag == 1
    assert best == pytest.approx(1.0)
    assert at_zero < best


# ---------------------------------------------------------------------------
# Humidity
# ---------------------------------------------------------------------------


def test_relative_humidity_matches_reference_values() -> None:
    rh, invalid, capped = relative_humidity([20.0, 20.0, 30.0, 0.0], [20.0, 10.0, 15.0, -10.0])

    assert rh[0] == pytest.approx(100.0)
    assert rh[1] == pytest.approx(52.6, abs=0.3)  # 20 degC air, 10 degC dew point
    assert rh[2] == pytest.approx(40.0, abs=0.5)  # 30 degC air, 15 degC dew point
    assert rh[3] == pytest.approx(46.8, abs=0.6)  # over water
    assert (invalid, capped) == (0, 0)


def test_a_dew_point_above_the_air_temperature_is_capped_or_rejected() -> None:
    rh, invalid, capped = relative_humidity([10.0, 10.0, np.nan], [10.3, 11.0, 5.0])

    assert rh[0] == 100.0  # 0.3 degC above: rounding, capped
    assert np.isnan(rh[1])  # 1 degC above: a data error, unknown
    assert np.isnan(rh[2])  # no temperature, no humidity
    assert (invalid, capped) == (1, 1)


# ---------------------------------------------------------------------------
# The enrichment, its checks and outputs
# ---------------------------------------------------------------------------


def test_aligned_data_passes_and_unlocated_sites_get_humidity_only() -> None:
    response = parse_response(payload(days=40))
    weather = pd.concat(
        [observed_weather(response), observed_weather(response, site_id="Nowhere")],
        ignore_index=True,
    )

    result = enrich({"Test": response}, [SITE], weather)

    assert result.aligned
    check = result.checks["Test"]
    assert check["temperature_best_lag_h"] == 0
    offset = check["solar_noon_offset_min"]
    assert isinstance(offset, float) and abs(offset) < 2.0
    nowhere = result.table[result.table["site_id"] == "Nowhere"]
    assert nowhere["ghi_w_m2_era5"].isna().all()
    assert nowhere[HUMIDITY_COLUMN].notna().all()
    assert result.stats["sites_with_era5"] == 1
    assert result.stats["sites_with_humidity"] == 2


@pytest.mark.parametrize("fault", ["radiation_labels", "temperature_shift"])
def test_misaligned_data_fails_the_checks(fault: str) -> None:
    good = parse_response(payload(days=40))
    if fault == "radiation_labels":
        response = parse_response(payload(days=40, labels_are_interval_ends=False))
        weather = observed_weather(good)
    else:
        response = good
        weather = observed_weather(good).assign(
            timestamp=lambda f: f["timestamp"] + pd.Timedelta(hours=2)
        )

    result = enrich({"Test": response}, [SITE], weather)

    assert not result.aligned


def test_outputs_are_deterministic_and_record_provenance(tmp_path: Path) -> None:
    response = parse_response(payload(days=10))
    result = enrich({"Test": response}, [SITE], observed_weather(response))
    source = tmp_path / "Test.json"
    source.write_bytes(payload(days=10))

    first = write(result, {"era5/Test": source}, tmp_path / "a", inputs_verified=False)
    second = write(result, {"era5/Test": source}, tmp_path / "b", inputs_verified=False)

    assert first == second
    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attribution"] == ATTRIBUTION
    assert manifest["terms"] == TERMS
    assert manifest["columns"]["ghi_w_m2_era5"]["source"].startswith("modelled: ERA5")
    assert manifest["columns"][HUMIDITY_COLUMN]["source"].startswith("derived:")
    assert manifest["alignment_passed"] is True
    table = pd.read_parquet(tmp_path / "a" / "weather_enrichment.parquet")
    assert str(table["timestamp"].dtype) == "datetime64[us, UTC]"


# ---------------------------------------------------------------------------
# Acquisition with a stand-in for the network
# ---------------------------------------------------------------------------


class FakeApi:
    def __init__(self, bodies: Mapping[str, bytes] | None = None, status: int = 200) -> None:
        self.bodies = dict(bodies or {})
        self.status = status
        self.calls: list[str] = []

    @contextmanager
    def __call__(self, url: str, timeout: float) -> Generator[BinaryIO]:
        self.calls.append(url)
        if self.status != 200:
            raise urllib.error.HTTPError(url, self.status, "error", {}, None)  # type: ignore[arg-type]
        yield io.BytesIO(self.bodies.get(url, payload(days=2)))


def test_fetch_downloads_records_and_then_only_verifies(tmp_path: Path) -> None:
    api = FakeApi()
    sites = [SITE, Site("Other", 51.5, -0.12)]
    manifest = tmp_path / "era5.json"

    first = fetch(sites, tmp_path / "raw", manifest, opener=api, pause=0)
    second = fetch(sites, tmp_path / "raw", manifest, opener=FakeApi(status=500), pause=0)

    assert first == {"Test": "downloaded", "Other": "downloaded"}
    assert second == {"Test": "verified", "Other": "verified"}, "no request the second time"
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert recorded["model"] == "era5"
    assert recorded["files"]["Test"]["grid_latitude"] == 40.1
    assert recorded["files"]["Test"]["url"] == request_url(SITE)


def test_fetch_reports_changed_content_on_a_forced_refetch(tmp_path: Path) -> None:
    manifest = tmp_path / "era5.json"
    fetch([SITE], tmp_path / "raw", manifest, opener=FakeApi(), pause=0)
    changed = FakeApi({request_url(SITE): payload(days=3)})

    assert fetch([SITE], tmp_path / "raw", manifest, opener=changed, pause=0, force=True) == {
        "Test": "changed"
    }


def test_fetch_never_overwrites_an_unrecorded_file(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "Test.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AcquisitionError, match="not recorded"):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=FakeApi(), pause=0)


def test_a_rate_limit_is_explained(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="rate limit"):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=FakeApi(status=429), pause=0)


def test_cli_prepare_runs_on_bdg2_format_files(make_bdg2_raw: BDG2Builder, tmp_path: Path) -> None:
    raw = make_bdg2_raw(
        [("Eagle", "US/Eastern", Clock.STANDARD, 2, False)], coordinates={"Eagle": (40.0, -75.0)}
    )
    site = Site("Eagle", 40.0, -75.0)
    # The fixture's temperature follows the sun in fixed UTC-5 time: 10 + 6 cos(2 pi (h - 15) / 24).
    body = payload(
        site,
        start=START_DATE,
        days=733,
        temperature=lambda t: (
            10 + 6 * np.cos(2 * np.pi * ((np.asarray(t.hour) - 5) % 24 - 15) / 24)
        ),
    )
    manifest = tmp_path / "era5.json"
    fetch([site], tmp_path / "raw", manifest, opener=FakeApi({request_url(site): body}), pause=0)
    out = tmp_path / "out"

    code = main(
        [
            "prepare",
            "--bdg2",
            str(raw),
            "--dest",
            str(tmp_path / "raw"),
            "--manifest",
            str(manifest),
            "--output",
            str(out),
            "--skip-input-verification",
        ]
    )

    assert code == 0
    recorded = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert recorded["alignment_passed"] is True
    assert recorded["checks"]["Eagle"]["temperature_best_lag_h"] == 0


def test_cli_reports_missing_responses(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = make_bdg2_raw(
        [("Eagle", "US/Eastern", Clock.STANDARD, 1, False)], coordinates={"Eagle": (40.0, -75.0)}
    )

    code = main(
        [
            "prepare",
            "--bdg2",
            str(raw),
            "--dest",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "m.json"),
            "--output",
            str(tmp_path / "out"),
            "--skip-input-verification",
        ]
    )

    assert code == 1
    assert "Missing or unrecorded ERA5 responses for ['Eagle']" in capsys.readouterr().err


def test_cli_verifies_bdg2_inputs_by_default(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = make_bdg2_raw([("Eagle", "US/Eastern", Clock.STANDARD, 1, False)])

    assert main(["verify", "--bdg2", str(raw), "--dest", str(tmp_path)]) == 1
    assert "does not match the expected size and SHA-256" in capsys.readouterr().err
