"""T014 models on a synthetic load (not real performance): weekday occupancy plus heating that
follows a temperature changing from day to day, which a one-week-old reading cannot know."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, START, VALIDATION_START, features_of, synthetic
from wattwise.ml.baselines import SeasonalNaive, run
from wattwise.ml.features import Group, feature_names
from wattwise.ml.models import (
    MIN_SCALE,
    SEASONAL_NAIVE,
    Family,
    FeatureModel,
    Study,
    Variant,
    compare_with_naive,
    decide,
    main,
    study,
    summary,
    to_markdown,
)
from wattwise.ml.splits import Holdout, Role, make_split

SMALL_GRID = {
    Family.RIDGE: ({"alpha": 1.0}, {"alpha": 1000.0}),
    Family.HIST_GBM: (
        {"max_iter": 60, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 20},
    ),
    Family.LIGHTGBM: (
        {"n_estimators": 60, "learning_rate": 0.1, "num_leaves": 15, "min_child_samples": 20},
    ),
}


@pytest.fixture(scope="module")
def data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    readings, weather = synthetic()
    return readings, weather, features_of(readings, weather)


def model(
    features: pd.DataFrame, family: Family = Family.LIGHTGBM, variant: Variant = Variant.FULL
) -> FeatureModel:
    settings = SMALL_GRID[family][0]
    return FeatureModel(family, variant, settings, features)


def fitted_predictions(
    readings: pd.DataFrame, features: pd.DataFrame, family: Family, variant: Variant
) -> pd.Series:
    split = make_split(readings, SPLIT)
    part = split.folds[0]
    m = model(features, family, variant)
    m.fit(part.rows(Role.TRAIN))
    return m.predict(part.rows(Role.TEST).drop(columns="value"), readings)


# ---------------------------------------------------------------------------
# Single models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", list(Family))
@pytest.mark.parametrize("variant", list(Variant))
def test_every_model_beats_seasonal_naive_on_a_weather_driven_load(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], family: Family, variant: Variant
) -> None:
    readings, _, features = data
    m = model(features, family, variant)

    result = run(make_split(readings, SPLIT), [m, SeasonalNaive()], roles=(Role.TEST,))
    (comparison,) = compare_with_naive(result, m.name)

    assert comparison.rows > 1000
    assert comparison.improvement is not None and comparison.improvement > 0.2


@pytest.mark.parametrize("family", list(Family))
@pytest.mark.parametrize("variant", list(Variant))
def test_predictions_are_deterministic_and_never_negative(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], family: Family, variant: Variant
) -> None:
    readings, _, features = data

    first = fitted_predictions(readings, features, family, variant)
    second = fitted_predictions(readings, features, family, variant)

    pd.testing.assert_series_equal(first, second)
    assert (first.dropna() >= 0).all()


@pytest.mark.parametrize("family", list(Family))
def test_conditions_models_never_see_values_outside_training(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], family: Family
) -> None:
    readings, weather, features = data
    later = (readings["timestamp"] >= VALIDATION_START).to_numpy()
    rewritten = readings.copy()
    rewritten.loc[later, "value"] = np.random.default_rng(5).uniform(0, 1e4, int(later.sum()))

    before = fitted_predictions(readings, features, family, Variant.CONDITIONS)
    after = fitted_predictions(
        rewritten, features_of(rewritten, weather), family, Variant.CONDITIONS
    )

    pd.testing.assert_series_equal(before, after)


@pytest.mark.parametrize("family", list(Family))
def test_full_models_ignore_readings_within_the_horizon(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], family: Family
) -> None:
    """Rewriting every reading from a cutoff in the test window changes no prediction before
    cutoff + 168 h: the target and anything later never reach the model."""
    readings, weather, features = data
    cutoff = pd.Timestamp("2017-03-29T05:00Z")
    later = (readings["timestamp"] >= cutoff).to_numpy()
    rewritten = readings.copy()
    rewritten.loc[later, "value"] = np.random.default_rng(6).uniform(0, 1e4, int(later.sum()))

    before = fitted_predictions(readings, features, family, Variant.FULL)
    after = fitted_predictions(rewritten, features_of(rewritten, weather), family, Variant.FULL)

    times = readings.loc[before.index, "timestamp"]
    early = (times < cutoff + pd.Timedelta(hours=168)).to_numpy()
    pd.testing.assert_series_equal(before[early], after[early])
    assert not before[~early].equals(after[~early]), "later predictions do use newer history"


def test_conditions_models_cannot_forecast_an_unknown_meter(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    readings, _, features = data
    m = model(features, Family.RIDGE, Variant.CONDITIONS)
    m.fit(readings[(readings["building_id"] != "C") & (readings["timestamp"] < VALIDATION_START)])

    predicted = m.predict(readings.drop(columns="value"), readings)

    c = (readings["building_id"] == "C").to_numpy()
    assert predicted[c].isna().all()
    assert predicted[~c].notna().all()


def test_rows_without_a_usable_scale_get_no_prediction(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    readings, weather, _ = data
    off = readings.copy()
    off.loc[off["building_id"] == "C", "value"] = MIN_SCALE / 10  # a meter that is all but off
    features = features_of(off, weather)
    m = model(features, Family.HIST_GBM, Variant.FULL)
    m.fit(off[off["timestamp"] < VALIDATION_START])

    predicted = m.predict(off.drop(columns="value"), off)

    # The scale needs 84 readings in the week ending 168 h before: from hour 168 + 83 on.
    early = (off["timestamp"] < START + pd.Timedelta(hours=251)).to_numpy()
    c = (off["building_id"] == "C").to_numpy()
    assert predicted[early | c].isna().all(), "no usable past week, or a scale below MIN_SCALE"
    assert predicted[~early & ~c].notna().all()


def test_a_model_must_be_fitted_and_needs_usable_training_rows(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    readings, _, features = data
    m = model(features, Family.RIDGE, Variant.FULL)

    with pytest.raises(RuntimeError, match="Fit the model"):
        m.predict(readings, readings)
    with pytest.raises(ValueError, match="no training row"):
        m.fit(readings[readings["timestamp"] < START + pd.Timedelta(hours=168)])


def test_names_and_params_record_the_family_variant_and_settings(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    m = FeatureModel(Family.RIDGE, Variant.CONDITIONS, {"alpha": 10.0}, data[2])

    assert m.name == "ridge-conditions-alpha10.0"
    assert m.params == {
        "family": "ridge",
        "variant": "conditions",
        "feature_set_version": "1",
        "seed": 0,
        "alpha": 10.0,
    }


def test_the_conditions_variant_uses_no_history_features(
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    m = model(data[2], Family.LIGHTGBM, Variant.CONDITIONS)

    m.fit(data[0][data[0]["timestamp"] < VALIDATION_START])

    assert not set(m.columns) & set(feature_names([Group.HISTORY]))
    assert {"profile_ratio", "log_scale"} <= set(m.columns)


# ---------------------------------------------------------------------------
# The study and the decision
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_study(data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> Study:
    readings, _, features = data
    holdouts = [Holdout(fraction=0.34, seed=0, group_by="building")]
    return study(readings, BUILDINGS, features, SPLIT, holdouts, SMALL_GRID, log=lambda _: None)


def test_settings_and_the_winner_are_chosen_on_validation(small_study: Study) -> None:
    trials = small_study.trials
    assert len(trials) == 2 * (2 + 1 + 1)  # every setting, in both variants
    ridge_full = [t for t in trials if t["family"] == "ridge" and t["variant"] == "full"]
    chosen = min(ridge_full, key=lambda t: t["validation"]["mae"])
    assert small_study.best["ridge-full"].name == chosen["model"]
    best = {k: m.name for k, m in small_study.best.items()}
    validation = {t["model"]: t["validation"]["mae"] for t in trials}
    assert small_study.winner == min(best, key=lambda k: validation[best[k]])
    assert all("test" not in t for t in trials), "grid trials never touch the test window"


def test_the_decision_compares_on_common_rows_and_covers_unseen_buildings(
    small_study: Study,
) -> None:
    decision = decide(small_study)

    seen, unseen = decision["seen_buildings"], decision["unseen_buildings"]
    assert seen["candidate"] == small_study.best[small_study.winner].name
    assert seen["adopted"] is True
    assert "-full-" in unseen["candidate"]
    assert unseen["adopted"] is True
    assert unseen["test_unseen_vs_seasonal_naive"][0]["role"] == "test_unseen"


def test_conditions_models_give_no_prediction_for_held_out_buildings(small_study: Study) -> None:
    held = small_study.holdouts[0]
    conditions = [m.name for k, m in small_study.best.items() if k.endswith("conditions")]

    for name in conditions:
        predicted = held.predictions[name][("chronological", Role.TEST_UNSEEN)]
        assert predicted.isna().all()
    assert held.predictions[SEASONAL_NAIVE][("chronological", Role.TEST_UNSEEN)].notna().any()


def test_the_summary_and_markdown_report_every_part(small_study: Study) -> None:
    data = summary(small_study, decide(small_study))
    text = to_markdown(data)

    assert set(data["future_period"]) == {
        SEASONAL_NAIVE,
        *(m.name for m in small_study.best.values()),
    }
    assert data["unseen_buildings"][0]["held_out_buildings"] == list(
        small_study.holdouts[0].split.holdout
    )
    assert "Expected-consumption accuracy" in text and "## Decision" in text
    assert "building holdout" in text


def test_the_command_line_needs_prepared_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data", str(tmp_path)]) == 1
    assert "Prepare the data first" in capsys.readouterr().err
