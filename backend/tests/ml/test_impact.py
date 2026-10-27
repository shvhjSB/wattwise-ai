"""T021 excess energy, cost and carbon impact (synthetic — not real performance)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tests.ml.conftest import SPLIT, features_of, synthetic
from wattwise.data.reference import CarbonFactor
from wattwise.ml.detection import Detector, run_detection
from wattwise.ml.explanations import explain
from wattwise.ml.impact import (
    ImpactStatus,
    TariffConfig,
    estimate_impact,
    main,
    potential_excess_kwh,
    price_bundles,
    run_impact,
    to_markdown,
)
from wattwise.ml.registry import promote, save, train

FACTOR = CarbonFactor(
    geography="GB",
    geography_name="United Kingdom",
    requested_year=2016,
    vintage_year=2016,
    kg_co2e_per_kwh=0.45,
    scope="delivered",
    source_name="s",
    source_url="u",
    retrieved="2026-10-26",
    licence="l",
    file_sha256="h",
)
TARIFF = TariffConfig(currency="gbp", rate_per_kwh=0.30)


# -- potential_excess_kwh ---------------------------------------------------------------------


def test_excess_is_zero_at_or_below_the_bound_never_negative() -> None:
    excess = potential_excess_kwh(actual=[5.0, 10.0, 15.0], upper=[10.0, 10.0, 10.0])

    np.testing.assert_array_equal(excess, [0.0, 0.0, 5.0])


def test_excess_is_nan_where_either_input_is_unknown() -> None:
    excess = potential_excess_kwh(actual=[np.nan, 5.0, 5.0], upper=[10.0, np.nan, 10.0])

    assert np.isnan(excess[0])
    assert np.isnan(excess[1])
    assert excess[2] == 0.0


def test_excess_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="same shape"):
        potential_excess_kwh(actual=[1.0, 2.0], upper=[1.0])


# -- estimate_impact ---------------------------------------------------------------------------


def test_estimate_impact_sums_the_excess_and_is_always_potential() -> None:
    impact = estimate_impact(actual=[5.0, 20.0, 12.0], upper=[10.0, 10.0, 10.0])

    assert impact.status is ImpactStatus.POTENTIAL
    assert impact.excess_kwh == pytest.approx(12.0)  # 0 + 10 + 2
    assert impact.hours_with_interval == 3
    assert impact.hours_above_upper_bound == 2


def test_a_missing_tariff_gives_kwh_only() -> None:
    impact = estimate_impact(actual=[20.0], upper=[10.0])

    assert impact.cost is None
    assert impact.currency is None
    assert impact.excess_kwh == pytest.approx(10.0)


def test_a_configured_tariff_prices_the_excess_in_its_currency() -> None:
    impact = estimate_impact(actual=[20.0], upper=[10.0], tariff=TARIFF)

    assert impact.cost == pytest.approx(3.0)  # 10 kWh * 0.30
    assert impact.currency == "GBP"


def test_a_missing_carbon_factor_is_not_configured() -> None:
    impact = estimate_impact(actual=[20.0], upper=[10.0])

    assert impact.carbon_kg is None
    assert impact.carbon_factor is None


def test_a_resolved_carbon_factor_costs_the_excess_in_kg_co2e() -> None:
    impact = estimate_impact(actual=[20.0], upper=[10.0], factor=FACTOR)

    assert impact.carbon_kg == pytest.approx(4.5)  # 10 kWh * 0.45
    assert impact.carbon_factor is FACTOR


def test_no_rows_above_the_bound_gives_zero_impact_not_none() -> None:
    impact = estimate_impact(actual=[1.0, 2.0], upper=[10.0, 10.0], tariff=TARIFF, factor=FACTOR)

    assert impact.excess_kwh == 0.0
    assert impact.cost == 0.0
    assert impact.carbon_kg == 0.0


def test_every_row_unknown_gives_zero_hours_and_zero_impact() -> None:
    impact = estimate_impact(actual=[np.nan], upper=[np.nan])

    assert impact.hours_with_interval == 0
    assert impact.excess_kwh == 0.0


# -- TariffConfig: currency handling ------------------------------------------------------------


def test_tariff_currency_is_normalised_to_uppercase() -> None:
    assert TariffConfig(currency="usd", rate_per_kwh=0.1).currency == "USD"


def test_tariff_currency_must_be_a_three_letter_code() -> None:
    with pytest.raises(ValidationError):
        TariffConfig(currency="US", rate_per_kwh=0.1)
    with pytest.raises(ValidationError):
        TariffConfig(currency="123", rate_per_kwh=0.1)


def test_tariff_rate_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        TariffConfig(currency="USD", rate_per_kwh=0.0)
    with pytest.raises(ValidationError):
        TariffConfig(currency="USD", rate_per_kwh=-0.1)


def test_tariff_is_frozen_and_rejects_unknown_fields() -> None:
    tariff = TariffConfig(currency="USD", rate_per_kwh=0.1)
    with pytest.raises(ValidationError):
        tariff.rate_per_kwh = 0.2  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TariffConfig(currency="USD", rate_per_kwh=0.1, extra_field="nope")  # type: ignore[call-arg]


# -- run_impact / to_markdown / main: on real-shaped detected events ---------------------------

BUILDINGS_WITH_A_REAL_SITE = pd.DataFrame(
    {
        "building_id": ["A", "B", "C"],
        "site_id": ["S1", "Bear", "S2"],  # Bear: a real BDG2 site -> eGRID subregion CAMX
        "timezone": ["UTC", "UTC", "UTC"],
        "latitude": [40.0, 37.871903, 51.5],
        "longitude": [-75.0, -122.260729, 0.0],
    }
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    readings, weather = synthetic()
    surge = (
        (readings["building_id"] == "B")
        & (readings["timestamp"] >= pd.Timestamp("2017-03-27T00:00Z"))
        & (readings["timestamp"] < pd.Timestamp("2017-03-29T00:00Z"))
    )
    readings.loc[surge, "value"] *= 1.6
    features = features_of(readings, weather)
    root = tmp_path_factory.mktemp("models")
    promote(save(train(readings, BUILDINGS_WITH_A_REAL_SITE, features, SPLIT), root), root)
    return readings, features, root


def test_run_impact_prices_each_event_by_its_own_site(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path],
) -> None:
    readings, features, root = prepared

    summary = run_impact(
        readings, BUILDINGS_WITH_A_REAL_SITE, features, root, Detector.MODEL,
        geography_filter="US-CAMX", tariff=TariffConfig(currency="USD", rate_per_kwh=0.2),
    )  # fmt: skip

    assert summary["events"] > 0
    assert summary["total_potential_excess_kwh"] >= 0
    bear_events = [
        e for e in summary["events_detail"] if e["site_id"] == "Bear" and not e["meter_problem"]
    ]
    assert bear_events and all(e["geography"] == "US-CAMX" for e in bear_events)
    assert any(e["carbon_kg"] is not None for e in bear_events)  # a real, committed factor
    s1_events = [
        e for e in summary["events_detail"] if e["site_id"] == "S1" and not e["meter_problem"]
    ]
    assert s1_events and all(e["geography"] is None and e["carbon_kg"] is None for e in s1_events)
    # cost is priced only for the named geography, never mixed across others
    assert all(e["cost"] is None for e in s1_events)
    priced = [e for e in bear_events if e["excess_kwh"] > 0]
    assert priced and all(
        e["cost"] == pytest.approx(e["excess_kwh"] * 0.2, abs=0.001) for e in priced
    )


def test_run_impact_without_a_tariff_prices_carbon_only(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path],
) -> None:
    readings, features, root = prepared

    summary = run_impact(readings, BUILDINGS_WITH_A_REAL_SITE, features, root, Detector.MODEL)

    assert summary["priced_geography"] is None
    assert all(e["cost"] is None for e in summary["events_detail"])
    assert "US-CAMX" in summary["by_geography"]
    assert summary["by_geography"]["US-CAMX"]["carbon_kg"] >= 0


def test_to_markdown_reports_the_totals_and_never_says_waste(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path],
) -> None:
    readings, features, root = prepared
    summary = run_impact(readings, BUILDINGS_WITH_A_REAL_SITE, features, root, Detector.MODEL)

    text = to_markdown(summary)

    assert "waste" not in text.lower()
    assert "potential" in text.lower()
    assert "US-CAMX" in text
    assert f"{summary['events']} events" in text


def test_the_command_line_writes_a_report(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path], tmp_path: Path
) -> None:
    readings, _features, root = prepared
    data = tmp_path / "data"
    data.mkdir()
    readings.to_parquet(data / "readings.parquet")
    BUILDINGS_WITH_A_REAL_SITE.to_parquet(data / "buildings.parquet")
    output = tmp_path / "out"

    code = main(
        [
            "--data", str(data), "--root", str(root), "--output", str(output),
            "--detector", "model", "--geography", "US-CAMX",
            "--tariff-currency", "USD", "--tariff-rate", "0.2",
        ]
    )  # fmt: skip

    assert code == 0
    assert (output / "impact.json").exists()
    assert (output / "impact.md").exists()


def test_the_command_line_needs_tariff_flags_together(tmp_path: Path) -> None:
    code = main(["--data", str(tmp_path), "--tariff-currency", "USD"])

    assert code == 1


def test_the_command_line_needs_a_model(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2017-01-01T00:00Z")],
            "meter_id": ["A-electricity"],
            "building_id": ["A"],
            "meter_type": ["electricity"],
            "unit": ["kWh"],
            "value": [1.0],
        }
    ).to_parquet(data / "readings.parquet")
    BUILDINGS_WITH_A_REAL_SITE.to_parquet(data / "buildings.parquet")
    empty_root = tmp_path / "no-model"

    code = main(["--data", str(data), "--root", str(empty_root)])

    assert code == 1


def test_pricing_saved_bundles_equals_detecting_and_explaining_again(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path], tmp_path: Path
) -> None:
    readings, features, root = prepared
    run = run_detection(
        readings, BUILDINGS_WITH_A_REAL_SITE, features, root, detector=Detector.MODEL
    )
    bundles = explain(run, readings, features)
    saved = tmp_path / "explanations.json"
    saved.write_text(json.dumps({"events": bundles}), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    BUILDINGS_WITH_A_REAL_SITE.to_parquet(data / "buildings.parquet")

    direct = run_impact(readings, BUILDINGS_WITH_A_REAL_SITE, features, root, Detector.MODEL)
    assert price_bundles(bundles, BUILDINGS_WITH_A_REAL_SITE) == direct
    assert direct["model_version"] == run.model.metadata.version
    out = tmp_path / "out"
    assert main(["--data", str(data), "--explanations", str(saved), "--output", str(out)]) == 0
    assert json.loads((out / "impact.json").read_text(encoding="utf-8")) == direct


def _bundle(meter: str, signature: str, excess: float) -> dict[str, object]:
    problem = signature in {"data_fault", "flatline"}
    return {
        "event": {"meter_id": meter, "building_id": "B", "start": "2017-11-01T00:00:00Z"},
        "detector": {"name": "rolling-z"},
        "model": {"version": "v"},
        "signature": {"primary": signature},
        "impact": {
            "meter_problem": problem,
            "potential_excess_kwh": None if problem else excess,
            "kwh_above_bound_not_counted": excess if problem else None,
            "hours_with_interval": 10,
            "hours_above_upper_bound": 5,
        },
    }


def test_meter_problems_are_never_counted_as_potential_excess() -> None:
    bundles = [
        _bundle("m1", "sustained", 100.0),
        _bundle("m2", "data_fault", 54_000.0),  # one wild reading, as in the BDG2 data
        _bundle("m3", "flatline", 500.0),
        _bundle("m4", "spike", 20.0),
    ]
    buildings = BUILDINGS_WITH_A_REAL_SITE

    summary = price_bundles(
        bundles, buildings, "US-CAMX", TariffConfig(currency="USD", rate_per_kwh=0.5)
    )

    assert summary["events"] == 4 and summary["events_counted"] == 2
    assert summary["total_potential_excess_kwh"] == pytest.approx(120.0)
    assert summary["meter_problem_events"] == 2
    assert summary["meter_problem_kwh_above_bound_not_counted"] == pytest.approx(54_500.0)
    for e in summary["events_detail"]:
        if e["meter_problem"]:
            assert e["excess_kwh"] is None and e["cost"] is None and e["carbon_kg"] is None
    text = to_markdown(summary)
    assert "Not counted" in text and "54,500.0 kWh above the bound" in text
    assert "waste" not in text.lower()


def test_bundles_written_before_the_rule_are_priced_by_their_signature() -> None:
    old = _bundle("m2", "data_fault", 54_000.0)
    old["impact"] = {  # no `meter_problem` flag, and the figure still in potential_excess_kwh
        "potential_excess_kwh": 54_000.0,
        "hours_with_interval": 1,
        "hours_above_upper_bound": 1,
    }

    summary = price_bundles([old, _bundle("m1", "sustained", 10.0)], BUILDINGS_WITH_A_REAL_SITE)

    assert summary["total_potential_excess_kwh"] == pytest.approx(10.0)
    assert summary["meter_problem_kwh_above_bound_not_counted"] == pytest.approx(54_000.0)


def test_the_priced_cost_is_stated_for_the_named_geography_only() -> None:
    bundles = [_bundle("m1", "sustained", 100.0), _bundle("m2", "data_fault", 9_000.0)]
    tariff = TariffConfig(currency="USD", rate_per_kwh=0.5)
    buildings = BUILDINGS_WITH_A_REAL_SITE.assign(site_id=["Bear", "Bear", "Bear"])

    priced = price_bundles(bundles, buildings, "US-CAMX", tariff)
    unpriced = price_bundles(bundles, buildings)

    assert priced["total_cost"] == {"currency": "USD", "value": 50.0, "events": 1}  # not 4,550
    assert "Cost: 50.00 USD" in to_markdown(priced)
    assert unpriced["total_cost"] is None
