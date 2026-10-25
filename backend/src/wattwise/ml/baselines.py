"""Seasonal and historical baselines: the bar every model must beat (docs/EVALUATION.md, D024).

- `SeasonalNaive`: the same meter's reading exactly one week earlier. It is a one-week-ahead
  forecast: it only ever looks 168 h back, so it never sees the hour it predicts or anything later.
- `HourOfWeekProfile`: the median of the meter's training readings for the same hour of the
  week, in the building's local time so schedules stay aligned across daylight-saving changes.
  Hours of the week without training data fall back to the meter's training median. Meters
  without training data get no prediction: this baseline cannot forecast unseen buildings.

Both are scored with the T011 harness on the rows a split assigns to validation and test.

    uv run python -m wattwise.ml.baselines --data ../data/processed/bdg2/cleaned
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol

import numpy as np
import pandas as pd

from wattwise.ml.evaluation import (
    EvaluationReport,
    Forecaster,
    Param,
    compute_metrics,
    evaluate,
    write_report,
)
from wattwise.ml.splits import Chronological, Role, Split, SplitConfig, make_split

SCORED_ROLES: Final = (Role.VALIDATION, Role.TEST)
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/baselines")
#: The default split for the BDG2 sample: train to mid-2017, validate on the third quarter, test on
#: the fourth (the BDG2 local year ends up to 8 h later in UTC, hence 2 January).
DEFAULT_SPLIT: Final = SplitConfig(
    time=Chronological(
        train_start=datetime(2016, 1, 1, tzinfo=UTC),
        validation_start=datetime(2017, 7, 1, tzinfo=UTC),
        test_start=datetime(2017, 10, 1, tzinfo=UTC),
        test_end=datetime(2018, 1, 2, tzinfo=UTC),
    )
)


class Baseline(Protocol):
    name: str

    @property
    def params(self) -> dict[str, Param]: ...

    def fit(self, train: pd.DataFrame) -> None: ...

    def predict(self, rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        """Predictions for `rows` (indexed like them; NaN where none can be made). `history`
        holds observed readings; a baseline may use only those it is entitled to."""
        ...


class SeasonalNaive:
    name = "seasonal-naive-1w"

    def __init__(self, lag_hours: int = 168) -> None:
        if lag_hours <= 0:
            raise ValueError("The lag must be positive: a forecast cannot look at its own hour.")
        self.lag_hours = lag_hours

    @property
    def params(self) -> dict[str, Param]:
        return {"lag_hours": self.lag_hours}

    def fit(self, train: pd.DataFrame) -> None:
        """Nothing to learn."""

    def predict(self, rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        observed = history.set_index(["meter_id", "timestamp"])["value"]
        observed = observed[~observed.index.duplicated()]
        wanted = pd.MultiIndex.from_arrays(
            [rows["meter_id"], rows["timestamp"] - pd.Timedelta(hours=self.lag_hours)]
        )
        return pd.Series(observed.reindex(wanted).to_numpy(dtype=float), index=rows.index)


class HourOfWeekProfile:
    name = "hour-of-week-median"

    def __init__(self, timezones: Mapping[str, str]) -> None:
        """`timezones`: building ID -> IANA zone. Buildings without one use UTC."""
        self.timezones = dict(timezones)
        self.profile: pd.Series | None = None
        self.fallback: pd.Series | None = None

    @property
    def params(self) -> dict[str, Param]:
        return {"statistic": "median", "clock": "local wall time"}

    def fit(self, train: pd.DataFrame) -> None:
        values = train.assign(hour_of_week=self._hour_of_week(train)).dropna(subset=["value"])
        self.profile = values.groupby(["meter_id", "hour_of_week"])["value"].median()
        self.fallback = values.groupby("meter_id")["value"].median()

    def predict(self, rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if self.profile is None or self.fallback is None:
            raise RuntimeError("Fit the profile on training rows first.")
        slots = pd.MultiIndex.from_arrays([rows["meter_id"], self._hour_of_week(rows)])
        predicted = self.profile.reindex(slots).to_numpy(dtype=float)
        fallback = self.fallback.reindex(rows["meter_id"]).to_numpy(dtype=float)
        return pd.Series(np.where(np.isnan(predicted), fallback, predicted), index=rows.index)

    def _hour_of_week(self, rows: pd.DataFrame) -> np.ndarray:
        result = np.zeros(len(rows), dtype=np.int64)
        zones = rows["building_id"].map(lambda b: self.timezones.get(str(b), "UTC")).to_numpy()
        for zone in sorted(set(zones)):
            mask = zones == zone
            local = pd.DatetimeIndex(rows.loc[mask, "timestamp"]).tz_convert(zone)
            result[mask] = np.asarray(local.dayofweek * 24 + local.hour, dtype=np.int64)
        return result


@dataclass(frozen=True)
class BaselineRun:
    split: Split
    reports: list[EvaluationReport]
    #: forecaster name -> (fold, role) -> predictions, indexed like the role's rows
    predictions: dict[str, dict[tuple[str, Role], pd.Series]]


def run(
    split: Split, baselines: Sequence[Baseline], roles: Sequence[Role] = SCORED_ROLES
) -> BaselineRun:
    """Fit each baseline on every fold's training rows only, and score the requested roles.
    Predictions never receive the target rows' values."""
    reports: list[EvaluationReport] = []
    predictions: dict[str, dict[tuple[str, Role], pd.Series]] = {}
    for baseline in baselines:
        made: dict[tuple[str, Role], pd.Series] = {}
        for part in split.folds:
            baseline.fit(part.rows(Role.TRAIN))
            for role in roles:
                if role in part.positions:
                    made[(part.fold.name, role)] = baseline.predict(
                        part.rows(role).drop(columns="value"), part.readings
                    )
        predictions[baseline.name] = made
        reports.append(
            evaluate(split, made, Forecaster(name=baseline.name, params=baseline.params))
        )
    return BaselineRun(split=split, reports=reports, predictions=predictions)


def common_rows_comparison(result: BaselineRun) -> list[dict[str, object]]:
    """Each baseline's overall metrics on only the rows every baseline predicted (and that have
    an actual value), so that coverage differences do not decide the comparison."""
    folds = {part.fold.name: part for part in result.split.folds}
    keys = set.intersection(*(set(p) for p in result.predictions.values()))
    rows_out: list[dict[str, object]] = []
    for fold, role in sorted(keys, key=lambda k: (k[0], list(Role).index(k[1]))):
        actual = folds[fold].rows(role)["value"].to_numpy(dtype=float)
        made = {
            name: p[(fold, role)].to_numpy(dtype=float) for name, p in result.predictions.items()
        }
        common = ~np.isnan(actual)
        for values in made.values():
            common &= ~np.isnan(values)
        for name, values in made.items():
            metrics = compute_metrics(actual[common], values[common])
            rows_out.append(
                {
                    "forecaster": name,
                    "fold": fold,
                    "role": role.value,
                    "common_rows": int(common.sum()),
                    "mae": metrics.mae,
                    "rmse": metrics.rmse,
                    "bias": metrics.bias,
                    "wape": metrics.wape,
                }
            )
    return rows_out


def default_baselines(buildings: pd.DataFrame) -> list[Baseline]:
    timezones = dict(
        zip(buildings["building_id"].astype(str), buildings["timezone"].astype(str), strict=True)
    )
    return [SeasonalNaive(), HourOfWeekProfile(timezones)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.baselines",
        description="Score the seasonal and hour-of-week baselines on prepared canonical data.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="folder with readings.parquet and buildings.parquet",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    defaults = DEFAULT_SPLIT.time
    assert isinstance(defaults, Chronological)
    for option, value in (
        ("--train-start", defaults.train_start),
        ("--validation-start", defaults.validation_start),
        ("--test-start", defaults.test_start),
        ("--test-end", defaults.test_end),
    ):
        parser.add_argument(
            option, default=value, type=utc_argument, help="UTC; default %(default)s"
        )
    args = parser.parse_args(argv)
    try:
        readings = pd.read_parquet(args.data / "readings.parquet")
        buildings = pd.read_parquet(args.data / "buildings.parquet")
    except FileNotFoundError as exc:
        print(f"error: {exc}. Prepare the data first (e.g. bdg2_prepare).", file=sys.stderr)
        return 1
    config = SplitConfig(
        time=Chronological(
            train_start=args.train_start,
            validation_start=args.validation_start,
            test_start=args.test_start,
            test_end=args.test_end,
        )
    )
    result = run(make_split(readings, config, buildings), default_baselines(buildings))
    args.output.mkdir(parents=True, exist_ok=True)
    comparison = common_rows_comparison(result)
    (args.output / "common_rows.json").write_bytes(
        (json.dumps(comparison, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    for report in result.reports:
        write_report(report, args.output, report.forecaster.name)
        for score in report.scores:
            o, m = score.overall, score.macro
            print(
                f"{report.forecaster.name:22s} {score.role.value:10s} MAE {o.mae} RMSE {o.rmse} "
                f"bias {o.bias} WAPE {o.wape} | macro MAE {m.mae} WAPE {m.wape} "
                f"({m.wape_meters} meters) | scored {o.scored:,}, missing prediction "
                f"{o.missing_prediction:,}"
            )
    for row in comparison:
        print(
            f"common rows: {row['forecaster']:22s} {row['role']:10s} rows {row['common_rows']:,} "
            f"MAE {row['mae']} WAPE {row['wape']}"
        )
    return 0


def utc_argument(text: str) -> datetime:
    """An argparse type: an ISO 8601 time with a time zone, converted to UTC."""
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r}: give a time zone, e.g. 2017-10-01T00:00Z")
    return value.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
