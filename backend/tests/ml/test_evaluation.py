import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import DAY, at, readings
from wattwise import __version__
from wattwise.ml.evaluation import (
    CodeVersion,
    EvaluationReport,
    Forecaster,
    MeterScore,
    Thresholds,
    code_version,
    compute_metrics,
    evaluate,
    fingerprint,
    macro_average,
    to_json,
    to_markdown,
    write_report,
)
from wattwise.ml.splits import (
    Chronological,
    Holdout,
    Role,
    RollingOrigin,
    Split,
    SplitConfig,
    make_split,
)

CODE = CodeVersion(package_version="test", git_commit="0" * 40, git_dirty=False)
NAIVE = Forecaster(name="test-forecaster", params={"offset": 2})


def chronological_split(data: pd.DataFrame, holdout: Holdout | None = None) -> Split:
    config = SplitConfig(
        time=Chronological(train_start=at(0), test_start=at(7), test_end=at(10)), holdout=holdout
    )
    return make_split(data, config)


def offset_predictions(
    split: Split, role: Role, offset: float
) -> dict[tuple[str, Role], pd.Series]:
    """Predictions that are `offset` above the actual value on every row of the role."""
    return {
        (part.fold.name, role): part.rows(role)["value"] + offset
        for part in split.folds
        if role in part.positions
    }


# ---------------------------------------------------------------------------
# Metrics against hand-computed values
# ---------------------------------------------------------------------------


def test_metrics_match_hand_computed_values() -> None:
    # errors (predicted - actual): +1, 0, -2, 0
    m = compute_metrics([1.0, 2.0, 3.0, 4.0], [2.0, 2.0, 1.0, 4.0])

    assert m.scored == 4
    assert m.mae == pytest.approx(0.75)
    assert m.rmse == pytest.approx(math.sqrt(5 / 4), abs=1e-6)
    assert m.bias == pytest.approx(-0.25)
    assert m.total_actual == pytest.approx(10.0)
    assert m.wape == pytest.approx(3 / 10)
    assert m.wape_note is None


def test_rows_with_a_missing_value_are_counted_not_scored() -> None:
    # Row 1 has no actual value; row 2 has no prediction. Scored errors: 0 and +2.
    m = compute_metrics([1.0, np.nan, 3.0, 4.0], [1.0, 5.0, np.nan, 6.0])

    assert (m.scored, m.missing_actual, m.missing_prediction) == (2, 1, 1)
    assert m.mae == pytest.approx(1.0)
    assert m.rmse == pytest.approx(math.sqrt(2), abs=1e-6)
    assert m.bias == pytest.approx(1.0)
    assert m.wape == pytest.approx(2 / 5)


@pytest.mark.parametrize(
    ("actual", "threshold", "reported"),
    [
        ([0.0, 0.0, 0.0], 1.0, False),  # a meter that used nothing: WAPE is undefined
        ([0.2, 0.3], 1.0, False),  # 0.5 total: below the threshold
        ([0.2, 0.3], 0.5, True),  # exactly at the threshold: reported
        ([0.2, 0.3], 0.1, True),
    ],
)
def test_wape_is_reported_only_for_a_meaningful_total(
    actual: list[float], threshold: float, reported: bool
) -> None:
    m = compute_metrics(actual, [1.0] * len(actual), Thresholds(wape_min_total=threshold))

    assert (m.wape is not None) is reported
    assert m.mae is not None, "MAE and RMSE do not depend on the guard"
    if not reported:
        assert m.wape_note is not None and "below" in m.wape_note


def test_negative_actual_values_count_by_size_in_the_wape_denominator() -> None:
    m = compute_metrics([-2.0, 2.0], [-1.0, 1.0])

    assert m.total_actual == pytest.approx(4.0)
    assert m.wape == pytest.approx(2 / 4)


def test_nothing_to_score_gives_no_metrics() -> None:
    m = compute_metrics([np.nan, 1.0], [2.0, np.nan])

    assert (m.scored, m.mae, m.rmse, m.bias, m.wape) == (0, None, None, None, None)
    assert m.wape_note == "no scored rows"


def test_inputs_of_different_length_are_rejected() -> None:
    with pytest.raises(ValueError, match="differ in shape"):
        compute_metrics([1.0, 2.0], [1.0])


def test_macro_averages_weight_every_meter_equally() -> None:
    big = MeterScore(meter_id="a", building_id="A", metrics=compute_metrics([0.0] * 10, [1.0] * 10))
    small = MeterScore(
        meter_id="b", building_id="B", metrics=compute_metrics([10.0] * 2, [13.0] * 2)
    )
    pooled = compute_metrics([0.0] * 10 + [10.0] * 2, [1.0] * 10 + [13.0] * 2)

    macro = macro_average([big, small])

    assert macro.mae == pytest.approx((1 + 3) / 2)
    assert pooled.mae == pytest.approx((10 * 1 + 2 * 3) / 12, abs=1e-6)
    assert (macro.meters, macro.wape_meters) == (2, 1), "meter a used nothing: no WAPE"
    assert macro.wape == pytest.approx(6 / 20)


# ---------------------------------------------------------------------------
# Scoring a split
# ---------------------------------------------------------------------------


def test_evaluate_scores_each_meter_building_and_role() -> None:
    split = chronological_split(readings(("A", "B")))

    report = evaluate(split, offset_predictions(split, Role.TEST, 2.0), NAIVE, code=CODE)
    (score,) = report.scores

    assert (score.fold, score.role, score.unit) == ("chronological", Role.TEST, "kWh")
    assert score.overall.scored == 2 * 3 * 24
    assert (score.overall.mae, score.overall.rmse, score.overall.bias) == (2.0, 2.0, 2.0)
    assert [m.meter_id for m in score.per_meter] == ["A-electricity", "B-electricity"]
    assert [b.building_id for b in score.per_building] == ["A", "B"]
    assert score.macro.mae == 2.0
    assert report.fold_summaries[0].folds == 1


def test_missing_predictions_are_reported_per_meter() -> None:
    split = chronological_split(readings(("A", "B")))
    predictions = offset_predictions(split, Role.TEST, 1.0)
    series = predictions[("chronological", Role.TEST)]
    rows = split.folds[0].rows(Role.TEST)
    series[rows["meter_id"] == "B-electricity"] = np.nan

    (score,) = evaluate(split, predictions, NAIVE, code=CODE).scores
    by_meter = {m.meter_id: m.metrics for m in score.per_meter}

    assert by_meter["B-electricity"].missing_prediction == 72
    assert by_meter["B-electricity"].scored == 0
    assert score.overall.missing_prediction == 72
    assert score.macro.meters == 1


def test_seen_and_unseen_buildings_are_scored_separately() -> None:
    split = chronological_split(readings(("A", "B", "C", "D")), Holdout(fraction=0.25, seed=0))
    predictions = {
        **offset_predictions(split, Role.TEST, 1.0),
        **offset_predictions(split, Role.TEST_UNSEEN, 3.0),
    }

    report = evaluate(split, predictions, NAIVE, code=CODE)

    assert [(s.role, s.overall.mae) for s in report.scores] == [
        (Role.TEST, 1.0),
        (Role.TEST_UNSEEN, 3.0),
    ]
    unseen = {m.building_id for m in report.scores[1].per_meter}
    assert unseen == set(split.holdout)


def test_rolling_folds_are_summarised_across_folds() -> None:
    config = SplitConfig(
        time=RollingOrigin(
            train_start=at(0), first_test_start=at(4), horizon=DAY, step=DAY, n_folds=3
        )
    )
    split = make_split(readings(), config)
    predictions = {
        (part.fold.name, Role.TEST): part.rows(Role.TEST)["value"] + (k + 1)
        for k, part in enumerate(split.folds)
    }

    report = evaluate(split, predictions, NAIVE, code=CODE)
    (summary,) = report.fold_summaries

    assert [s.fold for s in report.scores] == ["fold-1", "fold-2", "fold-3"]
    assert (summary.folds, summary.mae_mean, summary.mae_min, summary.mae_max) == (3, 2.0, 1.0, 3.0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("train", "never scored"),
        ("missing_row", "1 missing"),
        ("extra_row", "1 extra"),
        ("unknown_fold", "Unknown fold"),
        ("no_unseen_role", "has no test_unseen role"),
        ("nothing", "No predictions"),
    ],
)
def test_evaluate_refuses_predictions_that_are_not_an_honest_evaluation(
    change: str, message: str
) -> None:
    split = chronological_split(readings())
    part = split.folds[0]
    test = part.rows(Role.TEST)["value"] + 1.0
    predictions: dict[tuple[str, Role], pd.Series] = {
        "train": {("chronological", Role.TRAIN): part.rows(Role.TRAIN)["value"]},
        "missing_row": {("chronological", Role.TEST): test.iloc[1:]},
        "extra_row": {("chronological", Role.TEST): pd.concat([test, pd.Series([1.0], [10**9])])},
        "unknown_fold": {("fold-9", Role.TEST): test},
        "no_unseen_role": {("chronological", Role.TEST_UNSEEN): test},
        "nothing": {},
    }[change]

    with pytest.raises(ValueError, match=message):
        evaluate(split, predictions, NAIVE, code=CODE)


def test_meters_in_different_units_are_not_scored_together() -> None:
    data = readings(("A", "B"))
    data.loc[data["building_id"] == "B", "unit"] = "m3"
    split = chronological_split(data)

    with pytest.raises(ValueError, match="one unit is required"):
        evaluate(split, offset_predictions(split, Role.TEST, 1.0), NAIVE, code=CODE)


def test_a_non_unique_readings_index_is_rejected() -> None:
    data = readings(("A", "B"))
    data.index = [0] * len(data)
    split = chronological_split(data)

    with pytest.raises(ValueError, match="index must be unique"):
        evaluate(split, offset_predictions(split, Role.TEST, 1.0), NAIVE, code=CODE)


# ---------------------------------------------------------------------------
# The report: provenance and reproducibility
# ---------------------------------------------------------------------------


def report_for(data: pd.DataFrame) -> EvaluationReport:
    split = chronological_split(data)
    return evaluate(split, offset_predictions(split, Role.TEST, 2.0), NAIVE, code=CODE)


def test_the_report_records_forecaster_data_split_and_code() -> None:
    data = readings(("A", "B"))
    split = chronological_split(data)

    report = evaluate(split, offset_predictions(split, Role.TEST, 2.0), NAIVE, code=CODE)

    assert report.forecaster == NAIVE
    assert report.code == CODE
    assert report.split == split.manifest()
    assert report.data.fingerprint == fingerprint(data)
    assert (report.data.rows, report.data.meters) == (len(data), 2)
    assert (report.data.first, report.data.last) == ("2017-01-01T00:00:00Z", "2017-01-10T23:00:00Z")


def test_reports_are_byte_identical_for_the_same_inputs(tmp_path: Path) -> None:
    first = write_report(report_for(readings()), tmp_path / "a", "eval")
    second = write_report(report_for(readings()), tmp_path / "b", "eval")

    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]
    assert b"\r\n" not in first[0].read_bytes()


def test_the_json_report_round_trips() -> None:
    report = report_for(readings())

    assert EvaluationReport.model_validate_json(to_json(report)) == report


def test_the_markdown_report_states_its_conventions() -> None:
    data = readings(("A", "B"))
    data.loc[data["building_id"] == "B", "value"] = 0.0  # B used nothing: no WAPE for it
    markdown = to_markdown(report_for(data))

    assert "# Evaluation: test-forecaster" in markdown
    assert "`offset=2`" in markdown
    assert "predicted minus actual, in kWh" in markdown
    assert "WAPE is shown only when the total actual is at least 1 kWh" in markdown
    assert "below the 1 threshold" in markdown
    assert "000000000000" in markdown, "the git commit"


# ---------------------------------------------------------------------------
# Data fingerprint and code version
# ---------------------------------------------------------------------------


def test_the_fingerprint_ignores_row_order_and_index() -> None:
    data = readings(("A", "B"))
    shuffled = data.sample(frac=1.0, random_state=3)
    shuffled.index = pd.RangeIndex(100, 100 + len(shuffled))

    assert fingerprint(shuffled) == fingerprint(data)


def test_the_fingerprint_changes_with_any_value() -> None:
    data = readings(("A", "B"))
    changed = data.assign(value=data["value"] + np.where(data.index == 5, 0.001, 0.0))
    shift = pd.to_timedelta(np.where(data.index == 5, 1, 0), unit="min")
    moved = data.assign(timestamp=data["timestamp"] + shift)
    renamed = data.copy()
    renamed.loc[data["building_id"] == "B", "building_id"] = "C"

    assert len({fingerprint(d) for d in (data, changed, moved, renamed)}) == 4


def test_the_fingerprint_treats_signed_zeros_and_missing_values_consistently() -> None:
    data = readings(("A",))
    data.loc[0, "value"] = 0.0
    data.loc[1, "value"] = np.nan
    other = data.copy()
    other.loc[0, "value"] = -0.0
    other.loc[1, "value"] = float("nan")

    assert fingerprint(other) == fingerprint(data)


def test_code_version_reads_the_checkout_or_reports_none(tmp_path: Path) -> None:
    here = code_version()
    elsewhere = code_version(tmp_path)

    assert here.package_version == __version__
    if here.git_commit is not None:  # a git checkout (not, e.g., a source archive)
        assert len(here.git_commit) == 40
        assert here.git_dirty is not None
    assert (elsewhere.git_commit, elsewhere.git_dirty) == (None, None)
