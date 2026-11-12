"""T065: the load finder's rules, on a synthetic plant where the answer is known."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.ml import load_finder as lf

DAY = pd.Timedelta(days=1)
START = pd.Timestamp("2017-10-02T00:00Z")  # a Monday


def series(values: list[float], start: pd.Timestamp = START, seconds: int = 10) -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq=f"{seconds}s")
    return pd.Series(values, index=index, dtype=float)


# -- what a machine is known by -------------------------------------------------------------


def test_a_signature_comes_from_the_machines_own_development_power() -> None:
    # 2 runs: 30 s at 10 kW and 60 s at 12 kW, otherwise 0.
    power = series([0.0] * 10 + [10.0] * 3 + [0.0] * 10 + [12.0] * 6 + [0.0] * 10)

    sig = lf.signature("Press", power)

    assert sig.on_threshold_kw == pytest.approx(0.1 * power.quantile(0.999))
    assert sig.running_kw == 12.0  # median of the nine running bins (3 at 10, 6 at 12)
    expected = lf.RUN_MARGIN * np.quantile([30.0, 60.0], 0.99)
    assert sig.max_run_s == pytest.approx(expected, abs=0.1)  # rounded to 0.1 s


def test_a_machine_that_never_runs_has_no_running_power() -> None:
    sig = lf.signature("Idle", series([0.0] * 20))

    assert sig.on_threshold_kw == lf.ON_FLOOR_KW and sig.running_kw == 0.0


# -- the finder -----------------------------------------------------------------------------


def test_steps_are_taken_only_between_consecutive_bins() -> None:
    main = series([5.0, 15.0, 15.0, 5.0, 5.0])
    main = main.drop(main.index[3])  # the fall happens across a missing bin

    steps = lf.edges(main, 10)

    assert steps["delta"].tolist() == [10.0]  # the step across the gap is not a step
    assert steps["timestamp"].tolist() == [main.index[1]]


def sig(name: str, kw: float, longest: float = 600.0) -> lf.Signature:
    return lf.Signature(name, on_threshold_kw=kw / 10, running_kw=kw, max_run_s=longest)


def test_each_step_goes_to_the_closest_machine_within_its_tolerance() -> None:
    steps = pd.DataFrame(
        {
            "timestamp": pd.date_range(START, periods=4, freq="10s"),
            "delta": [9.0, -3.2, 6.0, 0.5],
        }
    )
    signatures = [sig("Press", 10.0), sig("Oven", 3.0)]

    out = lf.assign(steps, signatures, {"Press": 0.2, "Oven": 0.2})

    assert out["machine"].tolist() == ["Press", "Oven"]  # 6 kW and 0.5 kW match nobody
    assert out["rising"].tolist() == [True, False]


def test_runs_pair_a_rise_with_the_next_fall_within_the_longest_run() -> None:
    t = pd.date_range(START, periods=12, freq="10s")
    assigned = pd.DataFrame(
        {
            "timestamp": [t[0], t[1], t[3], t[5], t[6], t[11]],
            "delta": [10.0, 10.0, -10.0, -10.0, 10.0, -10.0],
            "rising": [True, True, False, False, True, False],
            "machine": ["Press"] * 6,
        }
    )

    runs = lf.pair(assigned, sig("Press", 10.0, longest=30.0), seconds=10)

    # The second rise replaces the first; a fall with nothing open is ignored; the last run
    # (50 s) is longer than the longest accepted (30 s) and is dropped.
    assert runs["start"].tolist() == [t[1]]
    assert runs["end"].tolist() == [t[3]]
    assert runs["energy_kwh"].tolist() == pytest.approx([10.0 * 20 / 3600])


def test_runs_cover_the_bins_from_their_start_up_to_their_end() -> None:
    index = pd.date_range(START, periods=6, freq="10s")
    runs = pd.DataFrame({"start": [index[1]], "end": [index[4]], "energy_kwh": [1.0]})

    assert lf.covered(index, runs).tolist() == [False, True, True, True, False, False]
    assert not lf.covered(index, runs.iloc[:0]).any()


# -- the schedule baseline and scoring ------------------------------------------------------


def test_slots_are_local_hours_of_the_week_across_the_clock_change() -> None:
    # Monday 30 October 2017, 07:00 UTC: 08:00 in Berlin, after the clocks went back.
    index = pd.DatetimeIndex(["2017-10-30T07:00Z", "2017-10-27T06:00Z"])

    assert lf.slots(index).tolist() == [8, 4 * 24 + 8]  # Friday 27 October: still +02


def test_scores_count_bins_runs_and_energy() -> None:
    truth = np.array([False, True, True, False, True, False])
    predicted = np.array([False, True, False, False, False, True])

    result = lf.score(predicted, truth, predicted_kwh=1.2, true_kwh=1.0)

    assert result["precision"] == 0.5 and result["recall"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["f1"] == pytest.approx(0.4)
    assert result["energy_error"] == pytest.approx(0.2)
    assert lf.run_recall(predicted, truth) == 0.5  # the first of two true runs was touched
    assert lf.score(np.zeros(3, bool), np.zeros(3, bool), 0.0, 0.0)["f1"] == 0.0


# -- end to end on a synthetic plant --------------------------------------------------------


def plant(days: int = 14, seed: int = 0) -> lf.Data:
    """Background 5 kW with 0.3 kW noise; a 10 kW press for 2 minutes at 09:00 (UTC) every day; a
    0.3 kW pump from 08:00 to 16:00. Ten-second bins, with 1 min and 15 min main series."""
    index = pd.date_range(START, periods=days * 8640, freq="10s")
    hours = index.hour + index.minute / 60
    press = np.where((hours >= 9) & (hours < 9 + 2 / 60), 10.0, 0.0)
    pump = np.where((hours >= 8) & (hours < 16), 0.3, 0.0)
    background = 5 + np.random.default_rng(seed).normal(0, 0.3, len(index))
    fine = pd.DataFrame(
        {lf.MAIN: background + press + pump, "Press": press, "Pump": pump}, index=index
    )
    main = {10: fine[lf.MAIN]}
    for _, seconds in lf.RESOLUTIONS[1:]:
        main[seconds] = fine[lf.MAIN].resample(f"{seconds}s").mean()
    return lf.Data(fine=fine, main=main)


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    # Whole weeks, as in the study: the schedule is by hour of the week.
    monkeypatch.setattr(lf, "DEVELOPMENT", (START, START + 7 * DAY))
    monkeypatch.setattr(lf, "HELD_OUT", (START + 7 * DAY, START + 14 * DAY))


@pytest.mark.usefixtures("windows")
def test_the_finder_finds_a_big_machine_and_not_a_small_one() -> None:
    data = plant()
    chosen, _ = lf.choose_tolerances(data, lf.signatures_of(data))

    report = lf.held_out(data, {f"{m}@{s}s": t for (m, s), t in chosen.items()})

    press = report["results"]["Press"]
    assert press["10s"]["f1"] > 0.95 and press["10s"]["run_recall"] == 1.0
    assert abs(press["10s"]["energy_error"]) < 0.05
    assert press["schedule"]["f1"] == 0.0  # 2 minutes is under half of the 09:00 slot
    assert report["acceptance"]["Press"]["10s"]["passed"]
    assert report["acceptance"]["Press"]["1min"]["passed"]  # runs align with minutes
    # A 2-minute run lifts a 15-minute average by only 1.3 kW: far outside the press's band.
    assert press["15min"]["runs_found"] == 0
    assert report["acceptance"]["Press"]["15min"]["passed"] is False
    pump = report["results"]["Pump"]
    assert pump["10s"]["f1"] < pump["schedule"]["f1"]  # its 0.3 kW steps are noise-sized
    assert pump["schedule"]["f1"] > 0.9  # but it keeps to a schedule
    assert "Press at 10s" in report["passing"]
    assert not any(p.startswith("Pump") for p in report["passing"])


@pytest.mark.usefixtures("windows")
def test_development_reports_its_tolerances_and_says_it_is_in_sample() -> None:
    report = lf.development(plant())

    assert set(report["tolerances"]) == {
        f"{m}@{s}s" for m in ("Press", "Pump") for _, s in lf.RESOLUTIONS
    }
    assert all(t in lf.TOLERANCES for t in report["tolerances"].values())
    assert "In-sample" in report["note"]


# -- scored once ----------------------------------------------------------------------------


def test_the_held_out_weeks_are_scored_once_and_only_after_development(tmp_path: Path) -> None:
    args = ["--data", str(tmp_path / "none"), "--output", str(tmp_path)]

    assert lf.main(["held-out", *args]) == 1  # no development result yet
    (tmp_path / "development.json").write_text("{}", encoding="utf-8")
    (tmp_path / "held_out.json").write_text("{}", encoding="utf-8")
    assert lf.main(["held-out", *args]) == 1  # already scored
    (tmp_path / "held_out.json").unlink()
    assert lf.main(["held-out", *args]) == 1  # no prepared data
