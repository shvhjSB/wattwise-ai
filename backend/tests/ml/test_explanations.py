"""T020 explanations on the synthetic load with an injected surge (not real performance)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.detection import Detector, run_detection
from wattwise.ml.explanations import (
    CHECKS,
    FORBIDDEN,
    check_for,
    explain,
    main,
    render,
    wording_problems,
)
from wattwise.ml.models import FeatureModel
from wattwise.ml.registry import promote, save, train
from wattwise.ml.signatures import DESCRIPTIONS, Signature

SURGE = (pd.Timestamp("2017-03-27T00:00Z"), pd.Timestamp("2017-03-29T00:00Z"))


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    readings, weather = synthetic()
    surge = (
        (readings["building_id"] == "B")
        & (readings["timestamp"] >= SURGE[0])
        & (readings["timestamp"] < SURGE[1])
    )
    readings.loc[surge, "value"] *= 1.6
    features = features_of(readings, weather)
    root = tmp_path_factory.mktemp("models")
    promote(save(train(readings, BUILDINGS, features, SPLIT), root), root)
    return readings, features, root


@pytest.fixture(scope="module")
def bundles(prepared: tuple[pd.DataFrame, pd.DataFrame, Path]) -> list[dict[str, object]]:
    readings, features, root = prepared
    run = run_detection(readings, BUILDINGS, features, root, detector=Detector.MODEL)
    return explain(run, readings, features)


def surge_bundle(bundles: list[dict[str, object]]) -> dict[str, object]:
    for b in bundles:
        event = b["event"]
        assert isinstance(event, dict)
        if event["meter_id"] == "B-electricity" and event["start"] == "2017-03-27T00:00:00Z":
            return b
    raise AssertionError("the surge event is missing")


def test_every_event_gets_an_evidence_bundle_and_an_explanation(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path], bundles: list[dict[str, object]]
) -> None:
    readings, features, root = prepared
    run = run_detection(readings, BUILDINGS, features, root, detector=Detector.MODEL)

    assert len(bundles) == len(run.events) > 0
    for b in bundles:
        assert set(b) >= {"event", "detector", "model", "signature", "influences", "check"}
        assert isinstance(b["explanation"], str) and b["explanation"]
        assert wording_problems(b["explanation"]) == []
    json.dumps(bundles, allow_nan=False)  # finite JSON throughout


def test_the_surge_explanation_carries_the_model_interval_and_influences(
    bundles: list[dict[str, object]],
) -> None:
    b = surge_bundle(bundles)
    model, influences = b["model"], b["influences"]
    assert isinstance(model, dict) and isinstance(influences, list)

    assert model["observed_kwh"] > model["expected_kwh"]
    assert model["hours_above_upper_bound"] > 24 and model["hours_below_lower_bound"] == 0
    assert model["agrees_with_detector"] is True
    assert model["interval"]["nominal"] == 0.9
    assert 0 < model["interval"]["measured_coverage_in_detection_window"] <= 1
    assert 1 <= len(influences) <= 5
    assert all("mean_contribution_kwh" in item for item in influences)
    text = str(b["explanation"])
    assert "above the model's expected consumption" in text
    assert "associations within the model and not causes" in text
    assert "Possible explanations to check" in text


def test_contributions_add_up_to_the_expected_value(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path],
) -> None:
    readings, features, root = prepared
    run = run_detection(readings, BUILDINGS, features, root, detector=Detector.MODEL)
    model = run.model.model
    rows = readings[readings["timestamp"] >= SURGE[0]].head(300)

    contributions = model.contributions(rows)
    expected = model.predict(rows.drop(columns="value"), readings)

    assert contributions is not None and len(contributions) > 0
    total = contributions.sum(axis=1)
    positive = expected.loc[total.index] > 0
    np.testing.assert_allclose(total[positive], expected.loc[total.index][positive], rtol=1e-6)


def test_explanations_survive_without_contributions(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    readings, features, root = prepared
    run = run_detection(readings, BUILDINGS, features, root, detector=Detector.MODEL)

    def broken(self: FeatureModel, rows: pd.DataFrame) -> pd.DataFrame:
        raise RuntimeError("no contributions here")

    monkeypatch.setattr(FeatureModel, "contributions", broken)
    found = explain(run, readings, features)

    assert len(found) == len(run.events)
    assert all(b["influences"] == [] for b in found)
    assert all("unavailable" in str(b["influences_note"]) for b in found)
    assert all("Largest influences" not in str(b["explanation"]) for b in found)


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def test_no_template_states_a_cause_or_certainty() -> None:
    texts = [text for options in CHECKS.values() for text in options.values()]
    texts += list(DESCRIPTIONS.values())

    for text in texts:
        assert wording_problems(text) == [], text
    for signature in Signature:
        for direction in ("high", "low"):
            assert check_for(signature.value, direction).startswith("Check") or check_for(
                signature.value, direction
            ).startswith("Compare")


def test_the_guard_catches_causal_and_certain_wording() -> None:
    assert wording_problems("Usage rose because the chiller failed.") == ["because"]
    assert set(wording_problems("This is confirmed waste, caused by HVAC.")) == {
        "caused",
        "confirmed",
        "waste",
    }
    assert {"due to", "definitely"} <= set(FORBIDDEN)


def test_an_event_without_a_model_expectation_still_reads_cleanly() -> None:
    bundle = {
        "event": {"meter_id": "m", "direction": "low", "start": "2017-01-01T00:00:00Z",
                  "duration_hours": 5, "flagged_hours": 4, "peak_z": 6.2},
        "detector": {"baseline": "its level at the same hour on the previous 14 days",
                     "observed_kwh": 10.0, "baseline_kwh": 50.0},
        "model": {"expected_kwh": None},
        "signature": {"primary": "unclassified",
                      "description": DESCRIPTIONS[Signature.UNCLASSIFIED]},
        "influences": [],
        "check": check_for("unclassified", "low"),
    }  # fmt: skip

    text = render(bundle)
    within = render(
        bundle
        | {
            "model": {
                "expected_kwh": 40.0, "observed_kwh": 10.0, "hours_with_expectation": 5,
                "hours_with_interval": 5, "hours_above_upper_bound": 0,
                "hours_below_lower_bound": 0,
                "interval": {"nominal": 0.9, "measured_coverage_in_detection_window": 0.87},
            }
        }
    )  # fmt: skip

    assert "found every hour within its interval" in within
    assert wording_problems(within) == []
    assert "The model had no expected value for these hours." in text
    assert "5 h from 2017-01-01 00:00 UTC" in text
    assert wording_problems(text) == []


def test_the_command_line_writes_explanations_and_needs_a_model(
    prepared: tuple[pd.DataFrame, pd.DataFrame, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readings, _, root = prepared
    folder = tmp_path / "data"
    folder.mkdir()
    readings.to_parquet(folder / "readings.parquet")
    BUILDINGS.to_parquet(folder / "buildings.parquet")
    synthetic()[1].to_parquet(folder / "weather.parquet")
    args = ["--data", str(folder), "--root", str(root), "--detector", "model"]

    assert main([*args, "--output", str(tmp_path / "one")]) == 0
    assert main([*args, "--output", str(tmp_path / "two")]) == 0

    for name in ("explanations.json", "explanations.md"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    payload = json.loads((tmp_path / "one" / "explanations.json").read_text(encoding="utf-8"))
    assert payload["explanations_version"] == "1" and payload["events"]
    capsys.readouterr()
    assert main(["--data", str(folder), "--root", str(tmp_path / "none")]) == 1
    assert "Train and promote one first" in capsys.readouterr().err
