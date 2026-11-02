"""Generalisation test on independent buildings: the HKUST campus meters (T041, D063).

The question, fixed before the run: **does the expected-consumption model trained on BDG2 (the
promoted evaluation model, D039), applied to HKUST without any retraining, have a lower MAE than
seasonal-naive on the HKUST test rows both predict?** On BDG2's own test window it was 18.0 %
lower, and 8.5 % lower for sites held out of training (docs/MODEL_CARD.md). HKUST is another
region (Hong Kong), other years (2022-2024) and mostly device-level meters, so this is a test
outside BDG2's population, reported separately from every BDG2 result.

- **Readings:** `python -m wattwise.data.hkust prepare` (hourly kWh from cumulative registers).
- **Split (T010):** chronological on local (UTC+8) midnights: training 2022-01-01 to 2023-07-01,
  validation to 2023-10-01, test to 2024-05-28. Training rows only fit the hour-of-week profile;
  the model is never refitted.
- **Forecasters (T011 harness):** seasonal-naive (the bar), the hour-of-week median profile,
  and the BDG2 model twice: with ERA5 weather for the campus substituted for observed weather,
  and with no weather at all. The ERA5 variant is the primary one, chosen before the run because
  it is closest to the inputs the model was trained with.
- **Coverage per meter:** valid hours in each window, and how many test rows each forecaster
  predicted. The model predicts only where a meter's last-week mean is at least 0.01 kWh.

    uv run python -m wattwise.ml.hkust_eval --report ../docs/reports/hkust-generalisation.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from wattwise.data.bdg2_sites import Region
from wattwise.data.hkust import (
    DEFAULT_OUTPUT as DEFAULT_DATA,
)
from wattwise.data.hkust import (
    DEFAULT_WEATHER,
    SITE_ID,
    TIMEZONE,
    buildings_table,
    parse_weather,
)
from wattwise.ml.baselines import HourOfWeekProfile, SeasonalNaive
from wattwise.ml.evaluation import (
    EvaluationReport,
    Forecaster,
    Param,
    compute_metrics,
    evaluate,
    write_report,
)
from wattwise.ml.features import build_features
from wattwise.ml.registry import DEFAULT_ROOT, current, load
from wattwise.ml.splits import Chronological, Role, Split, SplitConfig, make_split

HKUST_EVAL_VERSION: Final = "1"
REGIONS: Final = {SITE_ID: Region(country="HK")}
SCORED: Final = (Role.VALIDATION, Role.TEST)
CHUNK_METERS: Final = 100
DEFAULT_OUTPUT: Final = Path("../data/processed/hkust/evaluation")
BDG2_REFERENCE: Final = {
    "test_change_vs_seasonal_naive": -0.180,
    "unseen_sites_change_vs_seasonal_naive": -0.085,
    "source": "docs/MODEL_CARD.md (T043)",
}
NAIVE, PROFILE, MODEL_ERA5, MODEL_NONE = (
    "seasonal-naive",
    "hour-of-week-median",
    "bdg2-model-era5-weather",
    "bdg2-model-no-weather",
)
MARKER: Final = "<!-- generated: python -m wattwise.ml.hkust_eval -->"


def _local_midnight_utc(day: str) -> datetime:
    return pd.Timestamp(day, tz=TIMEZONE).tz_convert("UTC").to_pydatetime()


SPLIT: Final = SplitConfig(
    time=Chronological(
        train_start=_local_midnight_utc("2022-01-01"),
        validation_start=_local_midnight_utc("2023-07-01"),
        test_start=_local_midnight_utc("2023-10-01"),
        test_end=_local_midnight_utc("2024-05-28"),
    )
)


def load_readings(data: Path) -> pd.DataFrame:
    """The prepared readings, with the harness's unit and meter-type columns."""
    readings = pd.read_parquet(data / "readings.parquet")
    readings["meter_id"] = readings["meter_id"].astype(str)
    readings["building_id"] = readings["building_id"].astype(str)
    readings["meter_type"] = "electricity"
    readings["unit"] = "kWh"
    return readings.sort_values(["meter_id", "timestamp"], kind="stable").reset_index(drop=True)


def baseline_predictions(split: Split) -> dict[str, dict[tuple[str, Role], pd.Series]]:
    part = split.folds[0]
    meters = part.readings["building_id"].unique()
    naive, profile = SeasonalNaive(), HourOfWeekProfile(dict.fromkeys(map(str, meters), TIMEZONE))
    profile.fit(part.rows(Role.TRAIN))
    result: dict[str, dict[tuple[str, Role], pd.Series]] = {NAIVE: {}, PROFILE: {}}
    for role in SCORED:
        rows = part.rows(role).drop(columns="value")
        result[NAIVE][(part.fold.name, role)] = naive.predict(rows, part.readings)
        result[PROFILE][(part.fold.name, role)] = profile.predict(rows, part.readings)
    return result


def model_predictions(
    split: Split,
    weather: pd.DataFrame | None,
    enrichment: pd.DataFrame | None,
    root: Path,
    version: str,
) -> dict[tuple[str, Role], pd.Series]:
    """The BDG2 model's predictions for the scored rows, built in chunks of meters (features
    need each meter's full history, but only scored rows are kept)."""
    part = split.folds[0]
    readings = part.readings
    wanted = np.zeros(len(readings), dtype=bool)
    for role in SCORED:
        wanted[part.positions[role]] = True
    out = np.full(len(readings), np.nan)
    meters = sorted(readings["meter_id"].unique())
    for start in range(0, len(meters), CHUNK_METERS):
        chunk = meters[start : start + CHUNK_METERS]
        rows = readings[readings["meter_id"].isin(chunk)]
        features = build_features(
            rows[["meter_id", "building_id", "timestamp", "value"]],
            buildings_table(chunk),
            weather,
            enrichment,
            regions=REGIONS,
        )
        keep = wanted[rows.index.to_numpy()]
        if not keep.any():
            continue
        loaded = load(features, version=version, root=root)
        target = rows[keep]
        out[target.index.to_numpy()] = loaded.model.predict(
            target.drop(columns="value"), rows
        ).to_numpy(dtype=float)
    predicted = pd.Series(out, index=readings.index)
    return {(part.fold.name, role): predicted.iloc[part.positions[role]] for role in SCORED}


def common_rows(
    split: Split, predictions: Mapping[str, Mapping[tuple[str, Role], pd.Series]], role: Role
) -> dict[str, Any]:
    """Every forecaster's metrics on the rows of `role` that all of them predicted."""
    part = split.folds[0]
    rows = part.rows(role)
    key = (part.fold.name, role)
    actual = rows["value"].to_numpy(dtype=float)
    stacked = {
        name: p[key].reindex(rows.index).to_numpy(dtype=float) for name, p in predictions.items()
    }
    every = np.isfinite(actual)
    for values in stacked.values():
        every &= np.isfinite(values)
    result: dict[str, Any] = {
        "rows": int(every.sum()),
        "meters": int(rows["meter_id"][every].nunique()),
    }
    for name, values in stacked.items():
        m = compute_metrics(actual[every], values[every])
        result[name] = {"mae": m.mae, "rmse": m.rmse, "bias": m.bias, "wape": m.wape}
    return result


def per_meter(
    split: Split,
    predictions: Mapping[str, Mapping[tuple[str, Role], pd.Series]],
    meters: pd.DataFrame,
) -> pd.DataFrame:
    """Coverage and test errors per meter, on the test rows seasonal-naive and the primary model
    both predicted."""
    part = split.folds[0]
    key = (part.fold.name, Role.TEST)
    test = part.rows(Role.TEST)
    frame = pd.DataFrame(
        {
            "meter_id": test["meter_id"].to_numpy(),
            "actual": test["value"].to_numpy(dtype=float),
            **{
                name: p[key].reindex(test.index).to_numpy(dtype=float)
                for name, p in predictions.items()
            },
        }
    )
    counts = {
        role.value: part.rows(role).groupby("meter_id").size() for role in (Role.TRAIN, *SCORED)
    }
    rows = []
    for meter, group in frame.groupby("meter_id", sort=True):
        both = group[NAIVE].notna() & group[MODEL_ERA5].notna()
        naive = compute_metrics(group["actual"][both], group[NAIVE][both])
        model = compute_metrics(group["actual"][both], group[MODEL_ERA5][both])
        rows.append(
            {
                "meter_id": meter,
                "test_hours_predicted_naive": int(group[NAIVE].notna().sum()),
                "test_hours_predicted_model": int(group[MODEL_ERA5].notna().sum()),
                "test_hours_common": int(both.sum()),
                "naive_mae_kwh": naive.mae,
                "model_mae_kwh": model.mae,
                "naive_wape": naive.wape,
                "model_wape": model.wape,
            }
        )
    scored = pd.DataFrame(rows)
    table = meters.copy()
    for role, series in counts.items():
        table[f"{role}_hours"] = table["meter_id"].map(series).fillna(0).astype(int)
    return table.merge(scored, on="meter_id", how="left")


def run(data: Path, weather_path: Path, root: Path, output: Path) -> dict[str, Any]:
    started = time.time()
    readings = load_readings(data)
    meters = pd.read_csv(data / "meters.csv", dtype={"meter_id": str})
    split = make_split(readings, SPLIT)
    weather, enrichment = parse_weather(weather_path.read_bytes())
    version = current(root)
    predictions = baseline_predictions(split)
    predictions[MODEL_ERA5] = model_predictions(split, weather, enrichment, root, version)
    predictions[MODEL_NONE] = model_predictions(split, None, None, root, version)

    reports: dict[str, EvaluationReport] = {}
    model_params: dict[str, Param] = {"model_version": version, "retrained": False}
    params: dict[str, dict[str, Param]] = {
        NAIVE: {"lag_hours": 168},
        PROFILE: {"fit": "training window"},
    }
    for name, made in predictions.items():
        forecaster = Forecaster(
            name=name,
            params=params.get(name, model_params),
        )
        reports[name] = evaluate(split, made, forecaster)
        write_report(reports[name], output, name)

    common = {role.value: common_rows(split, predictions, role) for role in SCORED}
    test = common[Role.TEST.value]
    change = _change(test[MODEL_ERA5]["mae"], test[NAIVE]["mae"])
    table = per_meter(split, predictions, meters)
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "meters.csv", index=False, lineterminator="\n")
    compared = table.dropna(subset=["naive_mae_kwh", "model_mae_kwh"])
    better = int((compared["model_mae_kwh"] < compared["naive_mae_kwh"]).sum())
    summary = {
        "hkust_eval_version": HKUST_EVAL_VERSION,
        "model_version": version,
        "split": SPLIT.model_dump(mode="json"),
        "readings": len(readings),
        "meters_in_archive": len(meters),
        "meters_used": int(meters["used"].sum()),
        "not_used": meters.loc[~meters["used"], "reason"].value_counts().to_dict(),
        "overall": {
            name: {
                s.role.value: {
                    "scored": s.overall.scored,
                    "missing_prediction": s.overall.missing_prediction,
                    "mae": s.overall.mae,
                    "wape": s.overall.wape,
                    "macro_mae": s.macro.mae,
                    "macro_wape": s.macro.wape,
                    "meters": s.macro.meters,
                }
                for s in report.scores
            }
            for name, report in reports.items()
        },
        "common_rows": common,
        "question": "BDG2 model (ERA5 weather) MAE lower than seasonal-naive on common test rows",
        "test_change_vs_seasonal_naive": change,
        "answer": None if change is None else change < 0,
        "no_weather_change_vs_seasonal_naive": _change(test[MODEL_NONE]["mae"], test[NAIVE]["mae"]),
        "profile_change_vs_seasonal_naive": _change(test[PROFILE]["mae"], test[NAIVE]["mae"]),
        "meters_compared": len(compared),
        "meters_model_better": better,
        "by_metered_class": _by_class(compared),
        "by_tier": _by_group(compared, "tier"),
        "bdg2_reference": BDG2_REFERENCE,
        "runtime_s": round(time.time() - started),
    }
    (output / "summary.json").write_text(
        json.dumps(_finite(summary), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return summary


def _change(model: float | None, naive: float | None) -> float | None:
    if model is None or naive is None or naive == 0:
        return None
    return round(model / naive - 1.0, 4)


def _by_group(compared: pd.DataFrame, column: str) -> dict[str, dict[str, Any]]:
    """Per group: meters, how many the model beats, and the median relative MAE change over the
    meters whose seasonal-naive MAE is above zero (a ratio is undefined otherwise)."""
    result = {}
    for value, group in compared.groupby(column, sort=True):
        positive = group[group["naive_mae_kwh"] > 0]
        change = positive["model_mae_kwh"] / positive["naive_mae_kwh"] - 1.0
        result[str(value)] = {
            "meters": len(group),
            "model_better": int((group["model_mae_kwh"] < group["naive_mae_kwh"]).sum()),
            "median_change": round(float(change.median()), 4) if len(positive) else None,
        }
    return result


def _by_class(compared: pd.DataFrame) -> dict[str, dict[str, Any]]:
    top = compared["metered_class"].value_counts().head(8).index
    labelled = compared.assign(
        metered_class=compared["metered_class"].where(compared["metered_class"].isin(top), "other")
    )
    return _by_group(labelled, "metered_class")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def to_markdown(s: Mapping[str, Any]) -> str:
    names = (NAIVE, PROFILE, MODEL_ERA5, MODEL_NONE)
    lines = [
        "## Results (generated by `python -m wattwise.ml.hkust_eval`)",
        "",
        f"- **Model:** `{s['model_version']}` (BDG2 evaluation model), not retrained.",
        f"- **Meters:** {s['meters_used']:,} of {s['meters_in_archive']:,} used; not used: "
        + ", ".join(f"{reason} ({n})" for reason, n in s["not_used"].items())
        + f". {s['readings']:,} hourly readings.",
        f"- **Question (fixed before the run):** {s['question']}. **Answer: "
        f"{_yes_no(s['answer'])}** (change {_pct(s['test_change_vs_seasonal_naive'])}; on BDG2's "
        f"own test window {_pct(s['bdg2_reference']['test_change_vs_seasonal_naive'])}, unseen "
        f"BDG2 sites {_pct(s['bdg2_reference']['unseen_sites_change_vs_seasonal_naive'])}).",
        "",
    ]
    for role in (Role.TEST.value, Role.VALIDATION.value):
        c = s["common_rows"][role]
        lines += [
            f"### {role.capitalize()} window, rows every forecaster predicted "
            f"({c['rows']:,} rows, {c['meters']:,} meters)",
            "",
            "| Forecaster | MAE (kWh) | RMSE | Bias | WAPE | MAE vs seasonal-naive |",
            "|---|---|---|---|---|---|",
        ]
        for name in names:
            m = c[name]
            lines.append(
                f"| {name} | {_num(m['mae'])} | {_num(m['rmse'])} | {_num(m['bias'])} | "
                f"{_share(m['wape'])} | {_pct(_change(m['mae'], c[NAIVE]['mae']))} |"
            )
        lines.append("")
    lines += [
        "### Coverage: every row each forecaster scored (test window)",
        "",
        "| Forecaster | Rows scored | Rows with a reading but no prediction | MAE | WAPE | "
        "Macro MAE (per meter) | Meters |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in names:
        o = s["overall"][name][Role.TEST.value]
        lines.append(
            f"| {name} | {o['scored']:,} | {o['missing_prediction']:,} | {_num(o['mae'])} | "
            f"{_share(o['wape'])} | {_num(o['macro_mae'])} | {o['meters']:,} |"
        )
    lines += [
        "",
        f"### Per meter (test rows both predicted): the model has the lower MAE on "
        f"{s['meters_model_better']:,} of {s['meters_compared']:,} meters",
        "",
        "| Group | Meters | Model better | Median MAE change |",
        "|---|---|---|---|",
    ]
    for label, groups in (("tier", s["by_tier"]), ("metered", s["by_metered_class"])):
        for name, g in groups.items():
            lines.append(
                f"| {label}: {name} | {g['meters']} | {g['model_better']} | "
                f"{_pct(g['median_change'])} |"
            )
    lines += [
        "",
        "Per-meter coverage and errors: [hkust-meters.csv](hkust-meters.csv).",
        "",
    ]
    return "\n".join(lines)


def update_report(path: Path, generated: str) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        raise ValueError(f"{path} has no line {MARKER!r}.")
    head = text.split(MARKER, 1)[0]
    path.write_text(f"{head}{MARKER}\n\n{generated}", encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.hkust_eval",
        description="Evaluate the BDG2 model and the baselines on the HKUST meters (T041).",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--weather", type=Path, default=DEFAULT_WEATHER)
    parser.add_argument("--models", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, help="replace the generated part of this report")
    args = parser.parse_args(argv)
    for needed, how in (
        (args.data / "readings.parquet", "uv run python -m wattwise.data.hkust prepare"),
        (args.weather, "uv run python -m wattwise.data.hkust fetch-weather"),
    ):
        if not needed.exists():
            print(f"error: {needed} is missing. Run: {how}", file=sys.stderr)
            return 1
    summary = run(args.data, args.weather, args.models, args.output)
    print(json.dumps({k: summary[k] for k in ("test_change_vs_seasonal_naive", "answer")}))
    if args.report:
        update_report(args.report, to_markdown(summary))
        meters_csv = args.report.with_name("hkust-meters.csv")
        meters_csv.write_bytes((args.output / "meters.csv").read_bytes())
        print(f"updated {args.report} and {meters_csv}")
    return 0


def _yes_no(value: bool | None) -> str:
    return "not determined" if value is None else ("yes" if value else "no")


def _share(value: float | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:.1%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:,.3f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:+.1%}"


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        return float(value) if np.isfinite(value) else None
    return value


if __name__ == "__main__":
    raise SystemExit(main())
