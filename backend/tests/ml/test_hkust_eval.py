from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.data.hkust import TIMEZONE
from wattwise.ml import hkust_eval
from wattwise.ml.splits import Chronological, Role, Split, make_split


def synthetic_readings() -> pd.DataFrame:
    """Two meters over the whole HKUST period: a daily cycle plus noise. Synthetic: it tests the
    plumbing only."""
    window = hkust_eval.SPLIT.time
    assert isinstance(window, Chronological)
    index = pd.date_range(
        window.train_start,
        window.test_end,
        freq="h",
        inclusive="left",
    )
    rng = np.random.default_rng(3)
    parts = []
    for meter, level in (("A", 10.0), ("B", 2.0)):
        hour = index.tz_convert(TIMEZONE).hour
        value = level * (1.0 + 0.5 * ((hour >= 8) & (hour < 18))) + rng.normal(0, 0.2, len(index))
        parts.append(
            pd.DataFrame(
                {
                    "meter_id": meter,
                    "building_id": meter,
                    "timestamp": index,
                    "value": value,
                    "meter_type": "electricity",
                    "unit": "kWh",
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


@pytest.fixture(scope="module")
def split() -> Split:
    return make_split(synthetic_readings(), hkust_eval.SPLIT)


def test_the_split_is_chronological_on_local_midnights(split: Split) -> None:
    fold = split.folds[0].fold
    assert fold.train.end == fold.validation.start  # type: ignore[union-attr]
    assert pd.Timestamp(fold.test.start).tz_convert(TIMEZONE).hour == 0
    test = split.folds[0].rows(Role.TEST)
    train = split.folds[0].rows(Role.TRAIN)
    assert test["timestamp"].min() > train["timestamp"].max()


def test_the_baselines_predict_validation_and_test_rows(split: Split) -> None:
    made = hkust_eval.baseline_predictions(split)

    key = (split.folds[0].fold.name, Role.TEST)
    rows = split.folds[0].rows(Role.TEST)
    for name in (hkust_eval.NAIVE, hkust_eval.PROFILE):
        assert made[name][key].index.equals(rows.index)
        assert made[name][key].notna().mean() > 0.99


def fake_model(split: Split, bias: float) -> dict:  # type: ignore[type-arg]
    part = split.folds[0]
    return {(part.fold.name, role): part.rows(role)["value"] + bias for role in hkust_eval.SCORED}


def test_common_rows_and_per_meter_compare_the_same_rows(split: Split) -> None:
    made = hkust_eval.baseline_predictions(split)
    made[hkust_eval.MODEL_ERA5] = fake_model(split, 0.1)
    made[hkust_eval.MODEL_NONE] = fake_model(split, 1.0)
    meters = pd.DataFrame(
        {"meter_id": ["A", "B"], "tier": ["T60", "T15"], "metered_class": ["Room", "Switch"]}
    )

    common = hkust_eval.common_rows(split, made, Role.TEST)
    table = hkust_eval.per_meter(split, made, meters)

    assert common["meters"] == 2
    assert common[hkust_eval.MODEL_ERA5]["mae"] == pytest.approx(0.1)
    assert common[hkust_eval.MODEL_NONE]["mae"] == pytest.approx(1.0)
    assert list(table["meter_id"]) == ["A", "B"]
    assert (table["model_mae_kwh"] < table["naive_mae_kwh"]).all()
    assert (table["test_hours"] > 0).all() and (table["train_hours"] > table["test_hours"]).all()


def test_the_change_is_relative_to_seasonal_naive() -> None:
    assert hkust_eval._change(8.0, 10.0) == -0.2
    assert hkust_eval._change(None, 10.0) is None
    assert hkust_eval._change(1.0, 0.0) is None


def test_the_report_keeps_the_narrative_above_the_marker(tmp_path: Path) -> None:
    path = tmp_path / "r.md"
    path.write_text(f"# Narrative\n\n{hkust_eval.MARKER}\n\nold\n", encoding="utf-8")

    hkust_eval.update_report(path, "new\n")

    assert path.read_text(encoding="utf-8").endswith(f"{hkust_eval.MARKER}\n\nnew\n")


def test_missing_inputs_are_explained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert hkust_eval.main(["--data", str(tmp_path)]) == 1
    assert "wattwise.data.hkust prepare" in capsys.readouterr().err
