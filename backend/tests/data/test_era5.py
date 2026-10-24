import email.message
import http.client
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
    DEFAULT_MANIFEST,
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
    era5_table,
    fetch,
    located_sites,
    main,
    parse_response,
    phase_hours,
    relative_humidity,
    request_url,
    solar_noon_offsets,
    write,
)
from wattwise.data.solar import equation_of_time_min
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
    mislabelled_from: str | None = None,
    temperature: Callable[[pd.DatetimeIndex], np.ndarray] | None = None,
    generation_ms: float = 0.5,
    units: Mapping[str, str] = UNITS,
    offset: int = 0,
) -> bytes:
    """An Open-Meteo-style archive response. Real responses label radiation at the end of the
    averaged hour; labels_are_interval_ends=False builds a wrongly labelled one."""
    labels = pd.date_range(start, periods=24 * days, freq="h", tz="UTC")
    starts = labels - pd.Timedelta(hours=1) if labels_are_interval_ends else labels
    if mislabelled_from is not None:  # from this date on, labels mark interval starts (wrong)
        wrong = labels >= pd.Timestamp(mislabelled_from, tz="UTC")
        starts = starts.where(~wrong, labels)
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
        # Varies by hour, so relabelling this instant would show; a gap stays a gap.
        "cloud_cover": [None] + [int(h) for h in np.asarray(labels.hour)[1:]],
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
    assert table.loc[label, "cloud_cover_pct_era5"] == 18.0  # the instant keeps its own hour
    assert table.loc[label - pd.Timedelta(hours=1), "cloud_cover_pct_era5"] == 17.0
    assert np.isnan(table["ghi_w_m2_era5"].iloc[-1]), "the last hour's mean is not in the response"
    assert list(table.index) == list(response.times), "the requested hourly grid is kept"


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
    assert at_zero is not None and best is not None and at_zero < best


def test_without_overlap_no_lag_is_invented() -> None:
    times = pd.date_range("2016-01-01", periods=100, freq="h", tz="UTC")
    observed = pd.Series(np.nan, index=times)
    model = pd.Series(np.sin(np.arange(100) / 3.0), index=times)

    assert best_lag(observed, model) == (None, None, None)
    assert phase_hours(observed, model) is None


def test_the_phase_resolves_half_an_hour() -> None:
    times = pd.date_range("2016-01-01", periods=24 * 30, freq="h", tz="UTC")
    hours = np.arange(len(times), dtype=float)
    observed = pd.Series(np.cos(2 * np.pi * (hours - 15) / 24), index=times)
    model = pd.Series(np.cos(2 * np.pi * (hours - 15 + 0.5) / 24), index=times)  # 30 min ahead

    phase = phase_hours(observed, model)

    assert phase == pytest.approx(-0.5, abs=0.05)


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
    phase = check["temperature_phase_h"]
    assert isinstance(phase, float) and abs(phase) < 0.1
    offset = check["solar_noon_offset_min"]
    assert isinstance(offset, float) and abs(offset) < 2.0
    nowhere = result.table[result.table["site_id"] == "Nowhere"]
    assert nowhere["ghi_w_m2_era5"].isna().all()
    assert nowhere[HUMIDITY_COLUMN].notna().all()
    assert result.stats["sites_with_era5"] == 1
    assert result.stats["sites_with_humidity_values"] == 2
    # Missing values are counted only where a source is meant to have them.
    assert result.stats["era5_missing_at_located_sites"]["ghi_w_m2_era5"] == 1  # type: ignore[index]
    assert result.stats["era5_final_hours_without_radiation_by_design"] == 0
    assert result.stats["rows_without_era5_no_coordinates"] == 40 * 24


def test_a_mislabel_in_part_of_the_period_is_caught_per_quarter() -> None:
    # The reviewer's scenario: radiation labelled as interval starts from 2017-05-01 onwards,
    # a third of the period. The whole-period median alone would still pass.
    response = parse_response(payload(start=START_DATE, days=733, mislabelled_from="2017-05-01"))

    result = enrich({"Test": response}, [SITE], observed_weather(response))

    failed = result.checks["Test"]["quarters_failed"]
    assert isinstance(failed, list)
    assert not result.aligned
    assert {"2017Q3", "2017Q4"} <= set(failed)
    assert "2016Q3" not in failed


def test_a_one_hour_temperature_shift_in_one_quarter_is_caught() -> None:
    response = parse_response(payload(start=START_DATE, days=733))
    weather = observed_weather(response)
    summer = (weather["timestamp"] >= "2016-07-01T00:00:00Z") & (
        weather["timestamp"] < "2016-10-01T00:00:00Z"
    )
    weather.loc[summer, "timestamp"] = weather.loc[summer, "timestamp"] + pd.Timedelta(hours=1)
    weather = weather.drop_duplicates(["site_id", "timestamp"])

    result = enrich({"Test": response}, [SITE], weather)

    assert not result.aligned
    assert result.checks["Test"]["quarters_failed"] == ["2016Q3"]


def test_without_located_sites_nothing_counts_as_aligned() -> None:
    response = parse_response(payload(days=2))

    result = enrich({}, [], observed_weather(response))

    assert not result.aligned, "no site was checked"
    assert list(result.table.columns)[2:7] == [v.column for v in VARIABLES if v.column]
    assert result.table["ghi_w_m2_era5"].isna().all()


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
    def __init__(
        self,
        bodies: Mapping[str, bytes] | None = None,
        status: int = 200,
        failures: Mapping[str, Exception] | None = None,
        error_body: bytes = b"",
    ) -> None:
        self.bodies = dict(bodies or {})
        self.status = status
        self.failures = dict(failures or {})
        self.error_body = error_body
        self.calls: list[str] = []

    @contextmanager
    def __call__(self, url: str, timeout: float) -> Generator[BinaryIO]:
        self.calls.append(url)
        if url in self.failures:
            raise self.failures[url]
        if self.status != 200:
            raise urllib.error.HTTPError(
                url, self.status, "error", email.message.Message(), io.BytesIO(self.error_body)
            )
        yield io.BytesIO(self.bodies.get(url, payload(days=2)))


def test_a_failure_part_way_keeps_the_sites_already_fetched(tmp_path: Path) -> None:
    other = Site("Other", 51.5, -0.12)
    manifest = tmp_path / "era5.json"
    failing = FakeApi(failures={request_url(other): urllib.error.URLError("offline")})

    with pytest.raises(AcquisitionError, match="Could not read from Open-Meteo"):
        fetch([SITE, other], tmp_path / "raw", manifest, opener=failing, pause=0)
    retry = fetch([SITE, other], tmp_path / "raw", manifest, opener=FakeApi(), pause=0)

    assert retry == {"Test": "verified", "Other": "downloaded"}, "no --force needed to resume"


def test_a_different_request_is_downloaded_not_reported_as_changed(tmp_path: Path) -> None:
    manifest = tmp_path / "era5.json"
    fetch([SITE], tmp_path / "raw", manifest, opener=FakeApi(), pause=0)
    moved = Site("Test", 41.0, -75.0)
    # Different content too: without the same-request guard this would be reported "changed".
    api = FakeApi({request_url(moved): payload(moved, days=3)})

    assert fetch([moved], tmp_path / "raw", manifest, opener=api, pause=0, force=True) == {
        "Test": "downloaded"
    }
    entry = json.loads(manifest.read_text(encoding="utf-8"))["files"]["Test"]
    assert "previous_content_sha256" not in entry


def test_http_errors_carry_open_meteos_reason(tmp_path: Path) -> None:
    api = FakeApi(status=400, error_body=b'{"error": true, "reason": "end_date out of range"}')

    with pytest.raises(AcquisitionError, match=r"HTTP 400.*end_date out of range"):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=api, pause=0)


@pytest.mark.parametrize("problem", ["truncated", "not_json"])
def test_a_broken_response_is_an_error_and_nothing_is_saved(tmp_path: Path, problem: str) -> None:
    url = request_url(SITE)
    api = (
        FakeApi(failures={url: http.client.IncompleteRead(b"partial")})
        if problem == "truncated"
        else FakeApi(bodies={url: b"<html>maintenance</html>"})
    )

    with pytest.raises(AcquisitionError):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=api, pause=0)

    assert not (tmp_path / "raw" / "Test.json").exists()


def test_the_manifest_is_kept_out_of_git() -> None:
    assert DEFAULT_MANIFEST.as_posix().startswith("../data/raw/"), "it holds BDG2 coordinates"


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

    first = json.loads(manifest.read_text(encoding="utf-8"))["files"]["Test"]["content_sha256"]

    assert fetch([SITE], tmp_path / "raw", manifest, opener=changed, pause=0, force=True) == {
        "Test": "changed"
    }
    entry = json.loads(manifest.read_text(encoding="utf-8"))["files"]["Test"]
    assert entry["previous_content_sha256"] == first, "the earlier content stays on record"
    assert entry["content_sha256"] == content_sha256(payload(days=3))


def test_fetch_never_overwrites_an_unrecorded_file(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "Test.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AcquisitionError, match="not recorded"):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=FakeApi(), pause=0)


def test_a_rate_limit_is_explained(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="rate limit"):
        fetch([SITE], tmp_path / "raw", tmp_path / "era5.json", opener=FakeApi(status=429), pause=0)


def cli_prepare(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, delay_hours: int = 0
) -> tuple[list[str], Path]:
    """A BDG2-format site with a fetched ERA5 response; the ERA5 temperature can be delayed."""
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
            10 + 6 * np.cos(2 * np.pi * ((np.asarray(t.hour) - 5 - delay_hours) % 24 - 15) / 24)
        ),
    )
    manifest = tmp_path / "era5.json"
    fetch([site], tmp_path / "raw", manifest, opener=FakeApi({request_url(site): body}), pause=0)
    args = ["prepare", "--bdg2", str(raw), "--dest", str(tmp_path / "raw")]
    args += ["--manifest", str(manifest), "--output", str(tmp_path / "out")]
    return [*args, "--skip-input-verification"], manifest


def test_cli_prepare_runs_on_bdg2_format_files(make_bdg2_raw: BDG2Builder, tmp_path: Path) -> None:
    args, _ = cli_prepare(make_bdg2_raw, tmp_path)

    assert main(args) == 0
    recorded = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert recorded["alignment_passed"] is True
    assert abs(recorded["checks"]["Eagle"]["temperature_phase_h"]) < 0.1
    assert recorded["checks"]["Eagle"]["quarters_failed"] == []


def test_cli_prepare_writes_nothing_when_the_alignment_fails(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, _ = cli_prepare(make_bdg2_raw, tmp_path, delay_hours=2)

    assert main(args) == 1
    assert "alignment checks failed; nothing was written" in capsys.readouterr().err
    assert not (tmp_path / "out" / "weather_enrichment.parquet").exists()


def test_cli_verify_passes_and_then_catches_a_changed_era5_file(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, manifest = cli_prepare(make_bdg2_raw, tmp_path)
    verify_args = ["verify", *args[1:5], "--manifest", str(manifest), "--skip-input-verification"]

    assert main(verify_args) == 0
    assert "1 site responses verified" in capsys.readouterr().out
    response = tmp_path / "raw" / "Eagle.json"
    response.write_bytes(response.read_bytes().replace(b'"elevation": 50.0', b'"elevation": 51.0'))

    assert main(verify_args) == 1, "the ERA5 checksum is checked even when BDG2's is skipped"
    assert main(args) == 1


def test_a_uniform_one_hour_weather_clock_error_is_caught() -> None:
    response = parse_response(payload(start=START_DATE, days=733))
    late = observed_weather(response).assign(
        timestamp=lambda f: f["timestamp"] + pd.Timedelta(hours=1)
    )

    result = enrich({"Test": response}, [SITE], late)

    assert not result.aligned
    phase = result.checks["Test"]["temperature_phase_h"]
    assert isinstance(phase, float) and abs(phase) == pytest.approx(1.0, abs=0.1)


def test_cli_prepare_refuses_a_response_recorded_for_another_request(
    make_bdg2_raw: BDG2Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, manifest = cli_prepare(make_bdg2_raw, tmp_path)
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    recorded["files"]["Eagle"]["url"] = request_url(Site("Eagle", 41.0, -75.0))
    manifest.write_text(json.dumps(recorded), encoding="utf-8")

    assert main(args) == 1
    assert "recorded for a different request" in capsys.readouterr().err


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
