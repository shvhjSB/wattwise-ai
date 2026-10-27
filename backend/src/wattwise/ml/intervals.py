"""Split-conformal prediction intervals with measured coverage (docs/EVALUATION.md, D032).

An interval around expected consumption is predicted +- q * s, with three methods:
- **absolute:** s = 1, so q is in kWh, fixed per meter from the calibration window
- **relative:** s is the meter's mean reading over the week ending one horizon before the hour
  (`rolling_mean_168h`, past-only, the scale the model already uses), so the interval follows
  the meter's recent level; q is fixed per meter from the calibration window
- **rolling:** like relative, but q is recomputed every day (UTC) from the meter's scores in the
  28 days ending 7 days before that day. Only past readings are used, and the 7-day lag keeps a
  current anomaly from widening its own interval at once.

q is the conformal quantile of the scores |actual - predicted| / s: the ceil((n + 1)(1 - alpha))-th
smallest of n. If later errors were exchangeable with those scores, at least 1 - alpha of later
readings would fall inside. Energy data drifts with the seasons, so this is **measured, not
assumed**: coverage is reported on the test window, overall, per month and per meter. A method
is called **calibrated** only if its coverage is within 2 percentage points of nominal overall
and in every month with at least MIN_MONTH_ROWS rows.

Scores come only from windows the model did not train on (its validation window and later).
Lower bounds are clipped at zero. Rows without a prediction, a scale or enough scores get no
interval.

    uv run python -m wattwise.ml.intervals --data ../data/processed/bdg2/cleaned \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.ml.fullscale import downstream_inputs
from wattwise.ml.registry import (
    DEFAULT_ROOT,
    NO_VALIDATION_WINDOW,
    NoModelError,
    RegistryError,
    load,
)
from wattwise.ml.scale import quality_mask
from wattwise.ml.splits import Chronological, SplitConfig

FloatArray = npt.NDArray[np.float64]

INTERVALS_VERSION: Final = "1"
ALPHAS: Final = (0.2, 0.1, 0.05)  # nominal coverage 80%, 90%, 95%
TOLERANCE: Final = 0.02  # "calibrated": within 2 points of nominal, overall and every month
MIN_MONTH_ROWS: Final = 1000  # smaller months are reported but do not decide "calibrated"
LEVEL_COLUMN: Final = "rolling_mean_168h"
ROLLING_DAYS: Final = 28
ROLLING_LAG_DAYS: Final = 7
ROLLING_MIN_SCORES: Final = 168
#: A row's recent level is a usable scale only if it is at least this share of the meter's own
#: median level: the detectors' `scale_floor_fraction` (T016), applied to intervals (D041).
SCALE_FLOOR_FRACTION: Final = 0.01
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/intervals")


class Method(StrEnum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    ROLLING = "rolling"


def conformal_quantile(scores: npt.ArrayLike, alpha: float) -> float:
    """The ceil((n + 1)(1 - alpha))-th smallest finite score; infinite if n is too small."""
    values = np.sort(np.asarray(scores, dtype=float))
    values = values[np.isfinite(values)]
    n = len(values)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(values[k - 1]) if 1 <= k <= n else math.inf


def usable_level(
    rows: pd.DataFrame,
    level: npt.ArrayLike,
    first_time: datetime,
    last_time: datetime,
    fraction: float = SCALE_FLOOR_FRACTION,
) -> FloatArray:
    """`level` with NaN where it is not a usable scale (D041).

    The level is the mean of the week ending a week earlier, so a week of zero readings (an
    outage) makes it about 0 a week later, while consumption has returned to normal. Relative
    scores there are in the thousands: they flood the calibration windows of the following five
    weeks, and the rows themselves would get collapsed intervals. A level below `fraction` of the
    meter's own median level in [first_time, last_time) (the calibration window, so no test
    information is used) is therefore unusable: no interval, no calibration score, and, as
    everywhere, "unknown" rather than zero. A meter with no level in that window keeps its
    levels (it has nothing to compare with)."""
    lvl = np.asarray(level, dtype=float).copy()
    times = pd.DatetimeIndex(rows["timestamp"])
    inside = np.asarray((times >= pd.Timestamp(first_time)) & (times < pd.Timestamp(last_time)))
    known = inside & np.isfinite(lvl) & (lvl > 0)
    meters = rows["meter_id"].to_numpy()
    reference = (
        pd.Series(lvl[known]).groupby(meters[known], sort=False).median()
        if known.any()
        else pd.Series(dtype=float)
    )
    floor = pd.Series(meters).map(reference * fraction).to_numpy(dtype=float)
    unusable = np.isfinite(floor) & (lvl < floor)
    lvl[unusable] = np.nan
    return lvl


def scale(method: Method, level: npt.ArrayLike) -> FloatArray:
    """The per-row scale s: 1 for absolute intervals, the recent level otherwise."""
    values = np.asarray(level, dtype=float)
    if method is Method.ABSOLUTE:
        return np.ones_like(values)
    return np.where(values > 0, values, np.nan)


def scores(
    method: Method, actual: npt.ArrayLike, predicted: npt.ArrayLike, level: npt.ArrayLike
) -> FloatArray:
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    return np.asarray(np.abs(a - p) / scale(method, level), dtype=float)


def _bounds(predicted: FloatArray, half: FloatArray) -> tuple[FloatArray, FloatArray]:
    half = np.where(np.isfinite(half), half, np.nan)
    return np.maximum(predicted - half, 0.0), predicted + half


@dataclass(frozen=True)
class Intervals:
    """Fixed per-meter quantiles (absolute and relative methods)."""

    method: Method
    alpha: float
    quantiles: pd.Series  # meter_id -> q
    calibration_rows: pd.Series  # meter_id -> scores used

    def bounds(
        self, meters: npt.ArrayLike, predicted: npt.ArrayLike, level: npt.ArrayLike
    ) -> tuple[FloatArray, FloatArray]:
        """Lower and upper bounds; NaN where there is no prediction, scale or quantile."""
        p = np.asarray(predicted, dtype=float)
        q = pd.Series(np.asarray(meters)).map(self.quantiles).to_numpy(dtype=float)
        return _bounds(p, q * scale(self.method, level))


def fit(
    method: Method,
    alpha: float,
    meters: npt.ArrayLike,
    actual: npt.ArrayLike,
    predicted: npt.ArrayLike,
    level: npt.ArrayLike,
) -> Intervals:
    """Per-meter conformal quantiles from calibration rows."""
    if method is Method.ROLLING:
        raise ValueError("Rolling intervals are computed with rolling_bounds.")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1.")
    frame = pd.DataFrame(
        {"meter_id": np.asarray(meters), "score": scores(method, actual, predicted, level)}
    )
    frame = frame[np.isfinite(frame["score"])]
    grouped = frame.groupby("meter_id", sort=True)["score"]
    return Intervals(
        method=method,
        alpha=alpha,
        quantiles=grouped.apply(lambda s: conformal_quantile(s, alpha)).astype(float),
        calibration_rows=grouped.size().astype("int64"),
    )


def _nanoseconds(times: pd.DatetimeIndex) -> npt.NDArray[np.int64]:
    """Nanoseconds since the epoch (UTC), the units of `Timestamp.value`."""
    naive = times.tz_convert(None) if times.tz is not None else times
    return np.asarray(naive.as_unit("ns").to_numpy(), dtype="datetime64[ns]").astype(np.int64)


def daily_window_statistics(
    rows: pd.DataFrame,
    values: npt.ArrayLike,
    first_value_time: datetime,
    statistics: Callable[[FloatArray], Sequence[float]],
    outputs: int,
    days: int = ROLLING_DAYS,
    lag_days: int = ROLLING_LAG_DAYS,
    min_values: int = ROLLING_MIN_SCORES,
) -> FloatArray:
    """Per-row statistics of the meter's own recent values, recomputed each UTC day.

    For each meter and day D, `statistics` receives the meter's finite `values` (aligned with
    `rows`: timestamp, meter_id) in [D - lag_days - days, D - lag_days), counting only rows at
    or after `first_value_time`. It returns `outputs` numbers, written to every row of that
    meter and day. With fewer than `min_values` values the row gets NaN. Shape: (outputs, rows).
    """
    v = np.asarray(values, dtype=float)
    times = pd.DatetimeIndex(rows["timestamp"])
    stamps_all = _nanoseconds(times)  # like Timestamp.value
    usable = (stamps_all >= pd.Timestamp(first_value_time).value) & np.isfinite(v)
    days_all = _nanoseconds(times.floor("D"))
    lag, span = pd.Timedelta(days=lag_days).value, pd.Timedelta(days=days).value
    out = np.full((outputs, len(rows)), np.nan)
    # Each meter's rows are found once (sorted by meter), then each of its days once, so the
    # work grows with the number of rows, not with meters x days x rows (T044a, full scale).
    codes, _ = pd.factorize(rows["meter_id"].to_numpy(), sort=True)
    by_meter = np.argsort(codes, kind="stable")
    edges = np.flatnonzero(np.diff(codes[by_meter])) + 1
    for mine in np.split(by_meter, edges) if len(by_meter) else []:
        known_rows = mine[usable[mine]]
        known_rows = known_rows[np.argsort(stamps_all[known_rows], kind="stable")]
        stamps, known = stamps_all[known_rows], v[known_rows]
        mine = mine[np.argsort(days_all[mine], kind="stable")]
        day_edges = np.flatnonzero(np.diff(days_all[mine])) + 1
        for targets in np.split(mine, day_edges):
            end = days_all[targets[0]] - lag
            lo, hi = np.searchsorted(stamps, [end - span, end])
            if hi - lo < min_values:
                continue
            out[:, targets] = np.asarray(statistics(known[lo:hi]), dtype=float)[:, None]
    return out


def rolling_bounds(
    rows: pd.DataFrame,
    predicted: npt.ArrayLike,
    level: npt.ArrayLike,
    alpha: float,
    first_score_time: datetime,
    days: int = ROLLING_DAYS,
    lag_days: int = ROLLING_LAG_DAYS,
    min_scores: int = ROLLING_MIN_SCORES,
    usable: npt.ArrayLike | None = None,
) -> tuple[FloatArray, FloatArray]:
    """Rolling relative intervals for every row of `rows` (timestamp, meter_id, value).

    For each meter and UTC day D, q is the conformal quantile of the meter's relative scores
    in [D - lag_days - days, D - lag_days), counting only rows at or after `first_score_time`
    (where the model's residuals are out-of-sample) and, if given, rows where `usable` is True
    (the T042 quality mask: calibration excludes long flatlines, D035). Every row still gets an
    interval. Fewer than `min_scores` scores: no interval."""
    p = np.asarray(predicted, dtype=float)
    s = scale(Method.RELATIVE, level)
    score = np.abs(rows["value"].to_numpy(dtype=float) - p) / s
    if usable is not None:
        score = np.where(np.asarray(usable, dtype=bool), score, np.nan)
    (q,) = daily_window_statistics(
        rows,
        score,
        first_score_time,
        lambda window: (conformal_quantile(window, alpha),),
        outputs=1,
        days=days,
        lag_days=lag_days,
        min_values=min_scores,
    )
    return _bounds(p, q * s)


def coverage(actual: FloatArray, lower: FloatArray, upper: FloatArray) -> tuple[float | None, int]:
    """Share of rows with an actual value and an interval that fall inside it, and that count."""
    ok = np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
    n = int(ok.sum())
    if not n:
        return None, 0
    inside = (actual[ok] >= lower[ok]) & (actual[ok] <= upper[ok])
    return float(inside.mean()), n


def assess(
    rows: pd.DataFrame, lower: FloatArray, upper: FloatArray, alpha: float
) -> dict[str, Any]:
    """Coverage overall, per month and per meter, width, and the interval score, on `rows`
    (timestamp, meter_id, value) with the given bounds."""
    actual = rows["value"].to_numpy(dtype=float)
    meters = rows["meter_id"].to_numpy()
    overall, n = coverage(actual, lower, upper)
    nominal = 1 - alpha
    ok = np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
    months = pd.DatetimeIndex(rows["timestamp"]).tz_convert("UTC").strftime("%Y-%m").to_numpy()
    by_month: dict[str, dict[str, Any]] = {}
    for month in sorted(set(months[ok])):
        mask = months == month
        share, count = coverage(actual[mask], lower[mask], upper[mask])
        by_month[str(month)] = {"coverage": _round(share), "rows": count}
    inside = (actual[ok] >= lower[ok]) & (actual[ok] <= upper[ok])
    # One group-by rather than a comparison of every row per meter (T044a, full scale).
    per_meter = [
        float(share) for share in pd.Series(inside).groupby(meters[ok], sort=True).mean().to_numpy()
    ]
    a, lo, hi = actual[ok], lower[ok], upper[ok]
    width = hi - lo
    # A few meters with a tiny recent level can have enormous relative intervals, which dominate
    # the mean width; the typical meter is each meter's mean width against its mean reading.
    by_meter = (
        pd.DataFrame({"width": width, "actual": np.abs(a)}).groupby(meters[ok], sort=True).mean()
    )
    typical = (by_meter["width"] / by_meter["actual"].where(by_meter["actual"] > 0)).dropna()
    # Winkler interval score: the width plus 2/alpha times the distance outside the interval.
    penalty = (2 / alpha) * (np.clip(lo - a, 0, None) + np.clip(a - hi, 0, None))
    deciding = [m for m in by_month.values() if m["rows"] >= MIN_MONTH_ROWS]
    months_ok = all(abs(m["coverage"] - nominal) <= TOLERANCE for m in deciding)
    calibrated = overall is not None and abs(overall - nominal) <= TOLERANCE and months_ok
    return {
        "nominal": nominal,
        "coverage": _round(overall),
        "rows": n,
        "rows_without_interval": int((np.isfinite(actual) & ~ok).sum()),
        "calibrated": bool(calibrated),
        "by_month": by_month,
        "per_meter_coverage": {
            "meters": len(per_meter),
            "min": _round(min(per_meter)) if per_meter else None,
            "median": _round(float(np.median(per_meter))) if per_meter else None,
            "max": _round(max(per_meter)) if per_meter else None,
            "within_tolerance": int(sum(abs(c - nominal) <= TOLERANCE for c in per_meter)),
        },
        "mean_width": _round(float(width.mean())) if n else None,
        "mean_width_relative_to_actual": _round(float(width.mean() / np.abs(a).mean()))
        if n and np.abs(a).mean() > 0
        else None,
        "median_width": _round(float(np.median(width))) if n else None,
        "per_meter_relative_width": {
            "median": _round(float(typical.median())) if len(typical) else None,
            "p90": _round(float(typical.quantile(0.9))) if len(typical) else None,
            "max": _round(float(typical.max())) if len(typical) else None,
        },
        "interval_score": _round(float((width + penalty).mean())) if n else None,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


# ---------------------------------------------------------------------------
# Running on the promoted model
# ---------------------------------------------------------------------------


def run_intervals(
    readings: pd.DataFrame, features: pd.DataFrame, root: Path = DEFAULT_ROOT
) -> dict[str, Any]:
    """Fit every method from the promoted model's validation window (rolling: from scores
    since its start) and assess it on the test window, at every nominal level."""
    loaded = load(features, root=root)
    split = SplitConfig.model_validate(loaded.metadata.training.split_config).time
    if not isinstance(split, Chronological) or split.validation_start is None:
        raise RegistryError(NO_VALIDATION_WINDOW)
    predicted = loaded.model.predict(readings.drop(columns="value"), readings).to_numpy(float)
    level = features[LEVEL_COLUMN].reindex(readings.index).to_numpy(dtype=float)
    scale_less = int(np.isfinite(level).sum())
    level = usable_level(readings, level, split.validation_start, split.test_start)
    scale_less -= int(np.isfinite(level).sum())  # rows whose level is not a usable scale
    times = readings["timestamp"]
    ok = quality_mask(readings)  # calibration uses quality rows only; assessment every row (D035)
    calibration = ((times >= split.validation_start) & (times < split.test_start)).to_numpy()
    test = ((times >= split.test_start) & (times < split.test_end)).to_numpy()
    since_validation = (times >= split.validation_start).to_numpy()
    fit_rows = calibration & ok
    results: dict[str, Any] = {}
    for method in Method:
        for alpha in ALPHAS:
            if method is Method.ROLLING:
                part = readings[since_validation]
                lower, upper = rolling_bounds(
                    part,
                    predicted[since_validation],
                    level[since_validation],
                    alpha,
                    first_score_time=split.validation_start,
                    usable=ok[since_validation],
                )
                on_test = test[since_validation]
                cal_result = None
                test_result = assess(part[on_test], lower[on_test], upper[on_test], alpha)
            else:
                fitted = fit(
                    method,
                    alpha,
                    readings.loc[fit_rows, "meter_id"],
                    readings.loc[fit_rows, "value"],
                    predicted[fit_rows],
                    level[fit_rows],
                )
                cal_bounds = fitted.bounds(
                    readings.loc[calibration, "meter_id"],
                    predicted[calibration],
                    level[calibration],
                )
                test_bounds = fitted.bounds(
                    readings.loc[test, "meter_id"], predicted[test], level[test]
                )
                cal_result = assess(readings[calibration], *cal_bounds, alpha)
                test_result = assess(readings[test], *test_bounds, alpha)
            results[f"{method.value}@{1 - alpha:.0%}"] = {
                "method": method.value,
                "calibration_window": cal_result,
                "test_window": test_result,
            }
    return {
        "intervals_version": INTERVALS_VERSION,
        "model_version": loaded.metadata.version,
        "calibration_window_utc": [_iso(split.validation_start), _iso(split.test_start)],
        "test_window_utc": [_iso(split.test_start), _iso(split.test_end)],
        "tolerance": TOLERANCE,
        "min_month_rows": MIN_MONTH_ROWS,
        "level_column": LEVEL_COLUMN,
        "calibration_rows_masked": int((calibration & ~ok).sum()),
        "rows_without_usable_scale": scale_less,
        "scale_floor_fraction": SCALE_FLOOR_FRACTION,
        "rolling": {
            "days": ROLLING_DAYS,
            "lag_days": ROLLING_LAG_DAYS,
            "min_scores": ROLLING_MIN_SCORES,
        },
        "results": results,
    }


def to_markdown(report: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "-" if value is None else f"{value:.1%}"

    lines = [
        "# Prediction intervals (T019)",
        "",
        f"- Model `{report['model_version']}`; calibration "
        f"{' to '.join(report['calibration_window_utc'])}; test "
        f"{' to '.join(report['test_window_utc'])}",
        f"- Calibrated means test coverage within {report['tolerance']:.0%} of nominal overall "
        f"and in every month with at least {report['min_month_rows']:,} rows.",
        "",
        "| Method | Nominal | Coverage (calibration) | Coverage (test) | Months (test) | Meters "
        "within tolerance | Mean width (kWh) | Median width (kWh) | Width / mean actual | "
        "Typical meter: width / mean actual (median, 90th pct, max) | Interval score | "
        "Calibrated |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["results"].values():
        c, t = r["calibration_window"], r["test_window"]
        months = ", ".join(f"{m}: {pct(v['coverage'])}" for m, v in t["by_month"].items())
        meters = t["per_meter_coverage"]
        spread = t["per_meter_relative_width"]
        lines.append(
            f"| {r['method']} | {t['nominal']:.0%} | {pct(c['coverage'] if c else None)} | "
            f"{pct(t['coverage'])} | {months} | {meters['within_tolerance']} of "
            f"{meters['meters']} | {t['mean_width']} | {t['median_width']} | "
            f"{pct(t['mean_width_relative_to_actual'])} | {pct(spread['median'])}, "
            f"{pct(spread['p90'])}, {pct(spread['max'])} | {t['interval_score']} | "
            f"{'yes' if t['calibrated'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.intervals",
        description="Fit conformal intervals for the promoted model and measure their coverage.",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument(
        "--store", type=Path, help="T042 feature store: read full-scale inputs from it"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        readings, _, features = downstream_inputs(args.data, args.enrichment, args.store, args.root)
        report = run_intervals(readings, features, args.root)
    except NoModelError as exc:
        print(f"error: {exc} Train and promote one first.", file=sys.stderr)
        return 1
    except (RegistryError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "intervals.json").write_bytes(
        (json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    text = to_markdown(report)
    (args.output / "intervals.md").write_bytes(text.encode("utf-8"))
    print(text)
    for name in ("intervals.json", "intervals.md"):
        print(f"{name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
