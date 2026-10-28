"""T022 alert prioritisation on crafted evidence bundles (not real performance)."""

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.detection import Detector, run_detection
from wattwise.ml.explanations import explain
from wattwise.ml.prioritisation import (
    PriorityConfig,
    components,
    kind_of,
    main,
    prioritise,
    to_markdown,
)
from wattwise.ml.registry import promote, save, train


def bundle(
    meter: str = "m1",
    *,
    start: str = "2017-03-01T00:00:00Z",
    end: str = "2017-03-01T10:00:00Z",
    excess: float | None = 100.0,
    flagged: int = 10,
    duration: int = 10,
    peak: float | None = 10.0,
    agrees: bool | None = True,
    signature: str = "sustained",
    direction: str = "high",
) -> dict[str, Any]:
    """The parts of an evidence bundle that the score reads."""
    return {
        "event": {
            "meter_id": meter,
            "building_id": "b1",
            "direction": direction,
            "start": start,
            "end": end,
            "duration_hours": duration,
            "flagged_hours": flagged,
            "peak_z": peak,
        },
        "model": {"agrees_with_detector": agrees},
        "signature": {"primary": signature},
        "impact": {"potential_excess_kwh": excess},
    }


def order(bundles: list[dict[str, Any]]) -> list[str]:
    return [row["meter_id"] for row in prioritise(bundles)]


# -- each component raises the rank, the others equal -------------------------------------------


def test_more_potential_excess_ranks_higher() -> None:
    assert order([bundle("small", excess=10.0), bundle("large", excess=1000.0)]) == [
        "large",
        "small",
    ]


def test_longer_persistence_ranks_higher() -> None:
    assert order(
        [
            bundle("short", flagged=2, duration=2),
            bundle("long", flagged=30, duration=30),
        ]
    ) == ["long", "short"]


def test_a_higher_peak_score_ranks_higher() -> None:
    assert order([bundle("mild", peak=5.0), bundle("sharp", peak=60.0)]) == ["sharp", "mild"]


def test_an_alert_the_model_interval_does_not_support_ranks_lower() -> None:
    ranked = order(
        [bundle("disagrees", agrees=False), bundle("unknown", agrees=None), bundle("agrees")]
    )

    assert ranked == ["agrees", "unknown", "disagrees"]


def test_a_sparsely_flagged_event_is_less_confident_than_a_fully_flagged_one() -> None:
    ranked = order(
        [bundle("sparse", flagged=5, duration=50), bundle("dense", flagged=5, duration=5)]
    )

    assert ranked == ["dense", "sparse"]


def test_impact_can_outweigh_persistence() -> None:
    # The impact weight is the largest: a short, costly event outranks a long, harmless one.
    ranked = order(
        [
            bundle("long-harmless", excess=0.0, flagged=72, duration=72),
            bundle("short-costly", excess=5000.0, flagged=2, duration=2),
        ]
    )

    assert ranked == ["short-costly", "long-harmless"]


# -- the score itself -----------------------------------------------------------------------------


def test_the_score_is_the_documented_weighted_sum() -> None:
    config = PriorityConfig()
    # excess, flagged at the cap, peak at the cap, agreeing and fully flagged: 100.
    top = bundle(excess=config.impact_cap_kwh, flagged=72, duration=72, peak=100.0, agrees=True)
    # nothing above the floor: no excess, 1 flagged hour, peak at the threshold, no agreement.
    floor = bundle(excess=0.0, flagged=1, duration=1, peak=4.0, agrees=False)

    assert prioritise([top], config)[0]["score"] == 100.0
    # only the flagged share of the confidence component remains: 0.2 * 0.5 = 10 points.
    assert prioritise([floor], config)[0]["score"] == pytest.approx(10.0)


def test_components_are_between_zero_and_one_even_for_extreme_inputs() -> None:
    extreme = bundle(excess=1e9, flagged=10_000, duration=10_000, peak=15_000_000.0)

    parts = components(extreme, PriorityConfig())

    assert all(0.0 <= value <= 1.0 for value in parts.values())
    assert parts["impact"] == 1.0
    assert parts["severity"] == 1.0


def test_one_extreme_peak_score_does_not_swamp_the_ordering() -> None:
    # Without the cap the 15-million peak would dominate; with it, impact still decides.
    ranked = order(
        [
            bundle("glitch", excess=0.0, peak=15_000_000.0, flagged=1, duration=1),
            bundle("costly", excess=1500.0, peak=8.0, flagged=24, duration=24),
        ]
    )

    assert ranked == ["costly", "glitch"]


def test_unknown_values_score_without_failing() -> None:
    unknown = bundle(excess=None, peak=None, agrees=None)

    parts = components(unknown, PriorityConfig())

    assert parts["impact"] == 0.0
    assert parts["severity"] == 0.0
    assert parts["confidence"] == pytest.approx(0.25 + 0.5)


# -- what kind of alert it is ---------------------------------------------------------------------


@pytest.mark.parametrize("signature", ["data_fault", "flatline"])
def test_meter_problems_carry_no_impact_and_are_marked(signature: str) -> None:
    fault = bundle("fault", excess=5000.0, signature=signature)

    assert kind_of(fault) == "meter_problem"
    assert components(fault, PriorityConfig())["impact"] == 0.0
    assert prioritise([fault])[0]["kind"] == "meter_problem"


def test_an_alert_below_the_expected_level_has_no_impact_component() -> None:
    low = bundle("low", direction="low", excess=0.0)

    assert kind_of(low) == "below_expected"
    assert components(low, PriorityConfig())["impact"] == 0.0


def test_a_consumption_alert_with_excess_outranks_an_equal_meter_problem() -> None:
    assert order(
        [bundle("fault", signature="flatline", excess=500.0), bundle("above", excess=500.0)]
    ) == ["above", "fault"]


# -- determinism ----------------------------------------------------------------------------------


def test_the_order_does_not_depend_on_the_input_order() -> None:
    bundles = [
        bundle(f"m{i}", excess=float(i % 4) * 100, flagged=1 + i % 5, duration=6, peak=4.0 + i)
        for i in range(30)
    ]
    expected = prioritise(bundles)

    for seed in range(5):
        shuffled = copy.deepcopy(bundles)
        random.Random(seed).shuffle(shuffled)
        assert prioritise(shuffled) == expected


def test_ties_break_by_excess_then_flagged_hours_then_start_then_meter() -> None:
    # An identical score needs identical components; a sparse flagged share keeps the scores
    # equal here only because each pair differs in a tie-break field with the same rounding.
    a = bundle("a", start="2017-03-02T00:00:00Z", peak=10.0, agrees=True)
    b = bundle("b", start="2017-03-01T00:00:00Z", peak=10.0, agrees=True)
    c = bundle("c", start="2017-03-01T00:00:00Z", peak=10.0, agrees=True)

    ranked = prioritise([c, a, b])

    assert [r["score"] for r in ranked] == [ranked[0]["score"]] * 3
    assert [r["meter_id"] for r in ranked] == ["b", "c", "a"]  # earlier start, then meter id
    assert [r["rank"] for r in ranked] == [1, 2, 3]


def test_equal_everything_but_the_end_puts_the_later_end_first() -> None:
    first = bundle("m", end="2017-03-01T10:00:00Z")
    second = bundle("m", end="2017-03-01T11:00:00Z")

    ranked = prioritise([first, second])

    assert [r["end"] for r in ranked] == ["2017-03-01T11:00:00Z", "2017-03-01T10:00:00Z"]


# -- configuration --------------------------------------------------------------------------------


def test_the_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        PriorityConfig(impact_weight=0.5)


def test_a_different_weighting_can_change_the_order() -> None:
    bundles = [
        bundle("costly", excess=5000.0, flagged=2, duration=2),
        bundle("long", excess=0.0, flagged=72, duration=72),
    ]
    persistence_first = PriorityConfig(
        impact_weight=0.1, persistence_weight=0.7, severity_weight=0.1, confidence_weight=0.1
    )

    assert order(bundles) == ["costly", "long"]
    assert [r["meter_id"] for r in prioritise(bundles, persistence_first)] == ["long", "costly"]


# -- real bundles and the command line ------------------------------------------------------------


@pytest.fixture(scope="module")
def real_bundles(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    readings, weather = synthetic()
    surge = (
        (readings["building_id"] == "B")
        & (readings["timestamp"] >= "2017-03-27T00:00Z")
        & (readings["timestamp"] < "2017-03-29T00:00Z")
    )
    readings.loc[surge, "value"] *= 1.6
    features = features_of(readings, weather)
    root = tmp_path_factory.mktemp("models")
    promote(save(train(readings, BUILDINGS, features, SPLIT), root), root)
    run = run_detection(readings, BUILDINGS, features, root, detector=Detector.MODEL)
    return explain(run, readings, features, top=0)


def test_real_bundles_rank_with_the_surge_among_the_top(
    real_bundles: list[dict[str, Any]],
) -> None:
    ranked = prioritise(real_bundles)

    assert len(ranked) == len(real_bundles)
    assert [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1))
    assert ranked[0]["score"] >= ranked[-1]["score"]
    top = ranked[0]
    assert top["meter_id"] == "B-electricity"
    assert top["start"] == "2017-03-27T00:00:00Z"


def test_the_command_line_writes_a_ranking_and_the_summary_reads_cleanly(
    real_bundles: list[dict[str, Any]], tmp_path: Path
) -> None:
    source = tmp_path / "explanations.json"
    source.write_text(json.dumps({"events": real_bundles}), encoding="utf-8")

    code = main(["--explanations", str(source), "--output", str(tmp_path / "out")])

    assert code == 0
    document = json.loads((tmp_path / "out" / "priorities.json").read_text(encoding="utf-8"))
    assert document["config"] == PriorityConfig().model_dump()
    assert [a["rank"] for a in document["alerts"]] == list(range(1, len(real_bundles) + 1))
    text = (tmp_path / "out" / "priorities.md").read_text(encoding="utf-8")
    assert "not a probability or a verified saving" in text
    assert text == to_markdown(document["alerts"], PriorityConfig())


def test_the_command_line_reports_a_missing_file(tmp_path: Path) -> None:
    assert main(["--explanations", str(tmp_path / "nope.json"), "--output", str(tmp_path)]) == 1
