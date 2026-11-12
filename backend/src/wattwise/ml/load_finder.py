"""T065: can one meter on the main incomer stand in for a meter on each machine?

The protocol is fixed in docs/reports/t065-load-finder-protocol.md (D076) **before** the held-out
weeks are scored; the constants below are that protocol.

**Real data:** HIPE (KIT, CC BY 4.0, T064). Ten machines with their own meters and the plant's
main terminal, October to December 2017. The ten machines are only 4.1 % of the main terminal's
energy, so the question is whether *each machine's running periods* can be found in the main
terminal's signal under a large unmetered load, not whether the whole plant can be split.

- **Windows (chronological):** development 1 October to 12 November 2017 (local time), held-out
  12 November 2017 to 1 January 2018, strictly later and scored **once**.
- **What a machine is known by:** its development-weeks meter gives its running power, its
  running threshold and its longest run. That stands in for a nameplate rating a factory would
  know. In the held-out weeks the machine meters are used **only to score**.
- **The finder:** steps in the main terminal between consecutive bins are matched to the machine
  whose running power they are closest to, within a tolerance; a matching rise opens a run and
  the next matching fall within the machine's longest run closes it. The tolerance is chosen per
  machine and resolution on development, from 20, 30 and 40 %.
- **Baselines:** never running; and a **schedule** built from the hours each machine ran in
  development, which reads no main-terminal data. The finder is useful only if it beats it.
- **Scored** on the 10-second truth at every resolution (10 s, 1 min, 15 min), so the cost of
  coarser data shows.

    uv run python -m wattwise.ml.load_finder development
    uv run python -m wattwise.ml.load_finder held-out        # refuses to run twice
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

STUDY_VERSION: Final = "1"
LABEL: Final = "real data, HIPE (KIT, CC BY 4.0): ten metered machines in one plant"
DATA: Final = Path("../data/processed/hipe/full")
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/load_finder")
MAIN: Final = "MainTerminal"
LOCAL_TZ: Final = "Europe/Berlin"
DEVELOPMENT: Final = (pd.Timestamp("2017-09-30T22:00Z"), pd.Timestamp("2017-11-11T23:00Z"))
HELD_OUT: Final = (pd.Timestamp("2017-11-11T23:00Z"), pd.Timestamp("2017-12-31T23:00Z"))
GRID_SECONDS: Final = 10
RESOLUTIONS: Final = (("10s", 10), ("1min", 60), ("15min", 900))
TOLERANCES: Final = (0.2, 0.3, 0.4)
DEFAULT_TOLERANCE: Final = 0.3
#: A machine is running when its power is at least this share of its development 99.9th
#: percentile, and at least ON_FLOOR_KW.
ON_SHARE: Final = 0.1
ON_FLOOR_KW: Final = 0.02
#: The longest run the finder accepts: this many times the machine's development 99th
#: percentile run, and at least MIN_RUN_RESOLUTIONS bins.
RUN_MARGIN: Final = 1.5
MIN_RUN_RESOLUTIONS: Final = 3
#: The schedule baseline predicts "running" in hour slots where the machine ran at least half the
#: time in development.
SCHEDULE_SHARE: Final = 0.5
#: Acceptance, per machine and resolution, on the held-out weeks (all required).
MIN_F1: Final = 0.5
MIN_GAIN_OVER_SCHEDULE: Final = 0.1
MAX_ENERGY_ERROR: Final = 0.3
#: Machines whose own counters disagree with their measured power (T064, D075).
COUNTER_CAVEAT: Final = ("HighTemperatureOven", "PickAndPlaceUnit", "ChipSaw")

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


# ---------------------------------------------------------------------------
# What each machine is known by (development only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    machine: str
    on_threshold_kw: float
    running_kw: float  # median power while running: the "nameplate" stand-in
    max_run_s: float  # RUN_MARGIN times the 99th-percentile development run


def running(power: pd.Series, threshold: float) -> pd.Series:
    """Whether the machine runs in each 10-second bin (missing bins count as not running)."""
    return power.fillna(0.0) >= threshold


def run_lengths(on: pd.Series, seconds: int = GRID_SECONDS) -> pd.Series:
    """Duration in seconds of each run (consecutive running bins), in time order."""
    if not on.any():
        return pd.Series(dtype=float)
    labels = (on != on.shift()).cumsum()[on]
    return labels.value_counts(sort=False).sort_index().astype(float) * seconds


def signature(machine: str, power: pd.Series) -> Signature:
    top = float(power.quantile(0.999))
    threshold = max(ON_FLOOR_KW, ON_SHARE * top)
    on = running(power, threshold)
    lengths = run_lengths(on)
    longest = float(np.quantile(lengths, 0.99)) if len(lengths) else float(GRID_SECONDS)
    return Signature(
        machine=machine,
        on_threshold_kw=round(threshold, 4),
        running_kw=round(float(power[on].median()) if on.any() else 0.0, 4),
        max_run_s=round(RUN_MARGIN * longest, 1),
    )


# ---------------------------------------------------------------------------
# The finder
# ---------------------------------------------------------------------------


def edges(main: pd.Series, seconds: int) -> pd.DataFrame:
    """Changes of the main terminal between consecutive bins `seconds` apart: `timestamp` (the
    later bin) and `delta` (kW). A missing bin breaks the chain, so no step spans a gap."""
    series = main.dropna()
    stamps = series.index.to_series()
    consecutive = stamps.diff().dt.total_seconds().to_numpy() == seconds
    delta = series.diff().to_numpy()
    keep = consecutive & np.isfinite(delta) & (delta != 0)
    return pd.DataFrame({"timestamp": series.index[keep], "delta": delta[keep]})


def assign(
    steps: pd.DataFrame, signatures: Sequence[Signature], tolerance: Mapping[str, float]
) -> pd.DataFrame:
    """Each step's machine: the one whose running power it is closest to (relative), if within
    that machine's tolerance; otherwise no machine. Adds `machine` and `rising`."""
    usable = [s for s in signatures if s.running_kw > 0]
    if not usable or steps.empty:
        return steps.assign(machine=pd.Series(dtype=object), rising=pd.Series(dtype=bool))
    size = np.abs(steps["delta"].to_numpy())[:, None]
    power = np.array([s.running_kw for s in usable])[None, :]
    allowed = np.array([tolerance[s.machine] for s in usable])[None, :]
    distance = np.abs(size / power - 1)
    distance[distance > allowed] = np.inf
    best = distance.argmin(axis=1)
    matched = np.isfinite(distance.min(axis=1))
    names = [s.machine for s in usable]
    out = pd.DataFrame(steps[matched])
    out["machine"] = [names[i] for i in best[matched]]
    out["rising"] = out["delta"].to_numpy() > 0
    return out.reset_index(drop=True)


def pair(assigned: pd.DataFrame, signature: Signature, seconds: int) -> pd.DataFrame:
    """Runs of one machine: a rise opens one, the next fall within the longest run closes it.
    A second rise before a fall replaces the first (a machine runs once at a time). Energy is
    the mean of the two step sizes times the duration."""
    mine = assigned[assigned["machine"] == signature.machine].sort_values("timestamp")
    longest = max(signature.max_run_s, MIN_RUN_RESOLUTIONS * seconds)
    runs: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
    start: pd.Timestamp | None = None
    rise = 0.0
    for stamp, delta, rising in zip(
        mine["timestamp"], mine["delta"].to_numpy(dtype=float), mine["rising"], strict=True
    ):
        if rising:
            start, rise = stamp, delta
            continue
        if start is None:
            continue
        duration = (stamp - start).total_seconds()
        if duration <= longest:
            power = (rise + abs(delta)) / 2
            runs.append((start, stamp, power * duration / 3600))
        start = None
    return pd.DataFrame(runs, columns=["start", "end", "energy_kwh"])


def _utc_ns(index: pd.DatetimeIndex) -> npt.NDArray[np.datetime64]:
    """Plain UTC nanosecond stamps: time-zone-aware ones would compare as Python objects, and
    pandas may store them in microseconds."""
    return np.asarray(index.tz_convert("UTC").tz_localize(None), dtype="datetime64[ns]")


def covered(index: pd.DatetimeIndex, runs: pd.DataFrame) -> BoolArray:
    """For each 10-second bin start: whether it lies in a run [start, end)."""
    out = np.zeros(len(index), dtype=bool)
    if runs.empty:
        return out
    stamps = _utc_ns(index)
    lo = np.searchsorted(stamps, _utc_ns(pd.DatetimeIndex(runs["start"])), side="left")
    hi = np.searchsorted(stamps, _utc_ns(pd.DatetimeIndex(runs["end"])), side="left")
    marks = np.zeros(len(index) + 1, dtype=np.int64)
    np.add.at(marks, lo, 1)
    np.add.at(marks, hi, -1)
    return np.cumsum(marks[:-1]) > 0


# ---------------------------------------------------------------------------
# The schedule baseline (development only)
# ---------------------------------------------------------------------------


def slots(index: pd.DatetimeIndex) -> npt.NDArray[np.int64]:
    """Hour-of-week slot in local time: 0 to 167, Monday 00:00 first."""
    local = index.tz_convert(LOCAL_TZ)
    return np.asarray(local.dayofweek * 24 + local.hour, dtype=np.int64)


def schedule(on: pd.Series) -> FloatArray:
    """The share of each hour-of-week slot in which the machine ran (development)."""
    share = np.zeros(168)
    frame = pd.DataFrame({"slot": slots(pd.DatetimeIndex(on.index)), "on": on.to_numpy()})
    means = frame.groupby("slot")["on"].mean()
    share[means.index.to_numpy()] = means.to_numpy()
    return share


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score(
    predicted: BoolArray, truth: BoolArray, predicted_kwh: float, true_kwh: float
) -> dict[str, Any]:
    tp = int((predicted & truth).sum())
    fp = int((predicted & ~truth).sum())
    fn = int((~predicted & truth).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0
    )
    return {
        "precision": _round(precision),
        "recall": _round(recall),
        "f1": round(f1, 4),
        "predicted_hours": round(float(predicted.sum()) * GRID_SECONDS / 3600, 2),
        "true_hours": round(float(truth.sum()) * GRID_SECONDS / 3600, 2),
        "predicted_kwh": round(predicted_kwh, 2),
        "true_kwh": round(true_kwh, 2),
        "energy_error": round((predicted_kwh - true_kwh) / true_kwh, 4) if true_kwh else None,
    }


def run_recall(predicted: BoolArray, truth: BoolArray) -> float | None:
    """The share of true runs that overlap a predicted running bin."""
    labels = np.cumsum(np.diff(np.concatenate([[False], truth]).astype(np.int8)) == 1)
    ids = labels[truth]
    if not len(ids):
        return None
    hit = pd.Series(predicted[truth]).groupby(ids).any()
    return round(float(hit.mean()), 4)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


# ---------------------------------------------------------------------------
# Data and phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Data:
    fine: pd.DataFrame  # 10-second power, one column per meter
    main: dict[int, pd.Series]  # the main terminal at each resolution (seconds -> series)


def load(data: Path = DATA) -> Data:
    fine = pd.read_parquet(data / "power_10s.parquet", columns=["meter_id", "timestamp", "p_kw"])
    wide = fine.pivot(index="timestamp", columns="meter_id", values="p_kw").sort_index()
    main: dict[int, pd.Series] = {GRID_SECONDS: wide[MAIN]}
    for name, seconds in RESOLUTIONS:
        if seconds == GRID_SECONDS:
            continue
        coarse = pd.read_parquet(
            data / f"power_{name}.parquet",
            columns=["meter_id", "timestamp", "p_kw"],
            filters=[("meter_id", "==", MAIN)],
        )
        main[seconds] = coarse.set_index("timestamp")["p_kw"].sort_index()
    return Data(fine=wide, main=main)


def window(frame: pd.DataFrame | pd.Series, span: tuple[pd.Timestamp, pd.Timestamp]) -> Any:
    return frame[(frame.index >= span[0]) & (frame.index < span[1])]


def machines(data: Data) -> list[str]:
    return sorted(c for c in data.fine.columns if c != MAIN)


def signatures_of(data: Data) -> list[Signature]:
    dev = window(data.fine, DEVELOPMENT)
    return [signature(m, dev[m].dropna()) for m in machines(data)]


def evaluate(
    data: Data,
    span: tuple[pd.Timestamp, pd.Timestamp],
    signatures: Sequence[Signature],
    tolerance: Mapping[tuple[str, int], float],
) -> dict[str, Any]:
    """Every machine, resolution and baseline scored on `span` against the 10-second truth."""
    fine = window(data.fine, span)
    dev = window(data.fine, DEVELOPMENT)
    out: dict[str, Any] = {}
    found_runs: dict[int, pd.DataFrame] = {}
    for _, seconds in RESOLUTIONS:
        steps = edges(window(data.main[seconds], span), seconds)
        per_machine = {s.machine: tolerance[(s.machine, seconds)] for s in signatures}
        assigned = assign(steps, signatures, per_machine)
        found_runs[seconds] = assigned
    for sig in signatures:
        rows = fine[[MAIN, sig.machine]].dropna()
        index = pd.DatetimeIndex(rows.index)
        truth = running(rows[sig.machine], sig.on_threshold_kw).to_numpy()
        true_kwh = float(rows[sig.machine].sum() * GRID_SECONDS / 3600)
        dev_on = running(dev[sig.machine].dropna(), sig.on_threshold_kw)
        share = schedule(dev_on)
        planned = share[slots(index)] >= SCHEDULE_SHARE
        mean_on = float(dev[sig.machine].dropna()[dev_on].mean()) if dev_on.any() else 0.0
        machine: dict[str, Any] = {
            "signature": asdict(sig),
            "counter_caveat": sig.machine in COUNTER_CAVEAT,
            "never": score(np.zeros(len(index), dtype=bool), truth, 0.0, true_kwh),
            "schedule": score(
                planned, truth, float(planned.sum()) * GRID_SECONDS / 3600 * mean_on, true_kwh
            ),
            "true_runs": len(run_lengths(pd.Series(truth, index=index))),
        }
        machine["schedule"]["run_recall"] = run_recall(planned, truth)
        for name, seconds in RESOLUTIONS:
            runs = pair(found_runs[seconds], sig, seconds)
            predicted = covered(index, runs)
            result = score(predicted, truth, float(runs["energy_kwh"].sum()), true_kwh)
            result["run_recall"] = run_recall(predicted, truth)
            result["runs_found"] = len(runs)
            result["tolerance"] = tolerance[(sig.machine, seconds)]
            machine[name] = result
        out[sig.machine] = machine
    return out


def choose_tolerances(
    data: Data, signatures: Sequence[Signature]
) -> tuple[dict[tuple[str, int], float], dict[float, dict[str, Any]]]:
    """Per machine and resolution, the tolerance with the best development F1 (ties: 30 %)."""
    by_tolerance = {
        t: evaluate(data, DEVELOPMENT, signatures, _uniform(signatures, t)) for t in TOLERANCES
    }
    chosen: dict[tuple[str, int], float] = {}
    for sig in signatures:
        for name, seconds in RESOLUTIONS:
            f1 = {t: by_tolerance[t][sig.machine][name]["f1"] for t in TOLERANCES}
            best = max(f1.values())
            ties = [t for t in TOLERANCES if f1[t] >= best - 1e-9]
            chosen[(sig.machine, seconds)] = (
                DEFAULT_TOLERANCE if DEFAULT_TOLERANCE in ties else min(ties)
            )
    return chosen, by_tolerance


def _uniform(signatures: Sequence[Signature], value: float) -> dict[tuple[str, int], float]:
    return {(s.machine, seconds): value for s in signatures for _, seconds in RESOLUTIONS}


def accept(result: Mapping[str, Any], name: str) -> dict[str, Any]:
    """The predeclared criteria for one machine at one resolution (held-out)."""
    finder, planned = result[name], result["schedule"]
    error = finder["energy_error"]
    criteria = {
        "f1_at_least_0.5": finder["f1"] >= MIN_F1,
        "beats_schedule_by_0.1": finder["f1"] >= planned["f1"] + MIN_GAIN_OVER_SCHEDULE,
        "energy_error_within_30pct": error is not None and abs(error) <= MAX_ENERGY_ERROR,
    }
    return {"criteria": criteria, "passed": all(criteria.values())}


def development(data: Data) -> dict[str, Any]:
    signatures = signatures_of(data)
    chosen, _ = choose_tolerances(data, signatures)
    results = evaluate(data, DEVELOPMENT, signatures, chosen)
    return {
        "label": LABEL,
        "study_version": STUDY_VERSION,
        "window": [w.isoformat() for w in DEVELOPMENT],
        "note": "In-sample: signatures, tolerances and the schedule come from these same weeks.",
        "tolerances": {f"{m}@{s}s": t for (m, s), t in sorted(chosen.items())},
        "results": results,
    }


def held_out(data: Data, tolerances: Mapping[str, float]) -> dict[str, Any]:
    signatures = signatures_of(data)
    chosen = {
        (key.split("@")[0], int(key.split("@")[1].rstrip("s"))): value
        for key, value in tolerances.items()
    }
    results = evaluate(data, HELD_OUT, signatures, chosen)
    verdicts = {
        machine: {name: accept(result, name) for name, _ in RESOLUTIONS}
        for machine, result in results.items()
    }
    passing = sorted(
        f"{machine} at {name}"
        for machine, by_name in verdicts.items()
        for name, verdict in by_name.items()
        if verdict["passed"]
    )
    return {
        "label": LABEL,
        "study_version": STUDY_VERSION,
        "window": [w.isoformat() for w in HELD_OUT],
        "results": results,
        "acceptance": verdicts,
        "passing": passing,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.load_finder",
        description="T065: find machines' running periods in the main terminal (HIPE, local).",
    )
    parser.add_argument("phase", choices=["development", "held-out"])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    dev_file, held_file = args.output / "development.json", args.output / "held_out.json"
    if args.phase == "held-out":
        if held_file.exists():
            print(f"error: {held_file} exists: the held-out weeks are scored once", file=sys.stderr)
            return 1
        if not dev_file.exists():
            print("error: run the development phase first", file=sys.stderr)
            return 1
    if not (args.data / "power_10s.parquet").exists():
        print(
            f"error: {args.data} has no prepared HIPE data. Run: uv run python -m "
            "wattwise.data.hipe prepare --archive full",
            file=sys.stderr,
        )
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    data = load(args.data)
    if args.phase == "development":
        report = development(data)
        target = dev_file
    else:
        tolerances = json.loads(dev_file.read_text(encoding="utf-8"))["tolerances"]
        report = held_out(data, tolerances)
        target = held_file
    target.write_bytes((json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
