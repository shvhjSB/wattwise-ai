"""ML forecasters on the T013 features, compared with the baselines (docs/EVALUATION.md, D026).

Three model families (ridge regression, scikit-learn's HistGradientBoosting, LightGBM), each in
two variants:

- **full:** every feature group. The target is the reading divided by the meter's mean over the
  168 h ending one horizon before it (`rolling_mean_168h`), and history features are divided by
  the same scale. The model is global (no meter identity), so it can forecast buildings it was
  not trained on, from their own past readings.
- **conditions:** no consumption history, so a sustained anomaly cannot become its own baseline.
  The scale is the meter's mean over its training rows, and the meter's training median for the
  local hour of the week (relative to that mean) is a feature. It needs training data for the
  meter, so it cannot forecast unseen buildings.

Rows whose scale is missing or below MIN_SCALE get no prediction. Everything learned from data
(scales, profiles, imputation, standardisation, the model) is fitted on training rows only.
Predictions below zero are clipped to zero. Settings and the winner are chosen on the validation
window; the test window is scored once, for the chosen settings only.

    uv run python -m wattwise.ml.models --data ../data/processed/bdg2/cleaned \
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import lightgbm
import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from wattwise.ml.baselines import DEFAULT_SPLIT, BaselineRun, SeasonalNaive, run
from wattwise.ml.evaluation import Param, compute_metrics, write_report
from wattwise.ml.features import (
    ALL_GROUPS,
    FEATURE_SET_VERSION,
    FeatureConfig,
    Group,
    build_features,
    feature_manifest,
    feature_names,
)
from wattwise.ml.splits import Holdout, Role, SplitConfig, make_split

FloatArray = npt.NDArray[np.float64]

MODELS_VERSION: Final = "1"
SEED: Final = 0
#: In the readings' unit per interval. A smaller scale cannot normalise a target sensibly.
MIN_SCALE: Final = 0.01
DEFAULT_OUTPUT: Final = Path("../data/processed/evaluation/models")
HOLDOUTS: Final = (
    Holdout(fraction=0.25, seed=SEED, group_by="building"),
    Holdout(fraction=0.25, seed=SEED, group_by="site"),
)
HISTORY: Final = tuple(feature_names([Group.HISTORY]))
RAW_CALENDAR: Final = ("hour_local", "day_of_week_local", "month_local", "day_of_year_local")
SEASONAL_NAIVE: Final = SeasonalNaive().name


Settings = dict[str, float]


class Family(StrEnum):
    RIDGE = "ridge"
    HIST_GBM = "hist-gbm"
    LIGHTGBM = "lightgbm"


class Variant(StrEnum):
    FULL = "full"
    CONDITIONS = "conditions"


VARIANT_GROUPS: Final = {
    Variant.FULL: ALL_GROUPS,
    Variant.CONDITIONS: tuple(g for g in Group if g is not Group.HISTORY),
}

#: Settings tried per family; the validation window chooses among them.
GRID: Final[Mapping[Family, tuple[Settings, ...]]] = {
    Family.RIDGE: tuple({"alpha": a} for a in (0.1, 1.0, 10.0, 100.0)),
    Family.HIST_GBM: tuple(
        {"max_iter": n, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 50}
        for n in (200, 500)
    ),
    Family.LIGHTGBM: tuple(
        {"n_estimators": n, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 50}
        for n in (200, 500)
    ),
}


class FeatureModel:
    """A forecaster with the baselines' interface (`fit`, `predict`). It looks up its features by
    the readings' index labels in `features` (built on the same readings table)."""

    def __init__(
        self,
        family: Family,
        variant: Variant,
        settings: Mapping[str, float | str],
        features: pd.DataFrame,
        seed: int = SEED,
    ) -> None:
        self.family, self.variant, self.settings, self.seed = family, variant, dict(settings), seed
        self.features = features  # shared, not copied
        self.inputs = feature_names(VARIANT_GROUPS[variant])
        self.name = f"{family}-{variant}-" + "-".join(
            f"{k}{v}" for k, v in sorted(settings.items())
        )
        self.level: pd.Series | None = None
        self.profile: pd.Series | None = None
        self.model: Any = None
        self.columns: list[str] = []
        self.best_iteration: int | None = None  # set when fitted with early stopping

    @property
    def params(self) -> dict[str, Param]:
        return {
            "family": self.family.value,
            "variant": self.variant.value,
            "feature_set_version": FEATURE_SET_VERSION,
            "seed": self.seed,
            **self.settings,
        }

    def fit(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame | None = None,
        stopping_rounds: int | None = None,
    ) -> None:
        """Fit on `train`. For LightGBM, `validation` rows with `stopping_rounds` stop the boosting
        when the weighted L1 error on them has not improved for that many rounds (T043)."""
        observed = train.dropna(subset=["value"])
        if self.variant is Variant.CONDITIONS:
            self.level = observed.groupby("meter_id")["value"].mean()
            how = self._hour_of_week(observed.index)
            self.profile = observed.assign(how=how).groupby(["meter_id", "how"])["value"].median()
        design, scale = self._design(observed)
        usable = np.isfinite(scale) & (scale >= MIN_SCALE)
        if not usable.any():
            raise ValueError(f"{self.name}: no training row has a usable scale.")
        target = observed["value"].to_numpy(dtype=float)[usable] / scale[usable]
        design = design[usable]  # one copy of the training rows; the full frame is released
        # A column with no value in the training rows carries nothing to learn (e.g. ERA5 for a
        # sample of unlocated sites); calendar columns are always kept for the ridge encoding.
        present = design.notna().any()
        self.columns = [c for c in design.columns if present[c] or c in RAW_CALENDAR]
        inputs = self._inputs(design)
        del design  # only the estimator's input matrix is kept while it trains (T043)
        self.model = self._estimator()
        extra: dict[str, Any] = {}
        if validation is not None and stopping_rounds and self.family is Family.LIGHTGBM:
            checked = validation.dropna(subset=["value"])
            v_design, v_scale = self._design(checked)
            v_ok = np.isfinite(v_scale) & (v_scale >= MIN_SCALE)
            v_target = checked["value"].to_numpy(dtype=float)[v_ok] / v_scale[v_ok]
            extra = {
                "eval_X": (self._inputs(v_design[v_ok]),),  # LightGBM 4.7 replaces eval_set
                "eval_y": (v_target,),
                "eval_sample_weight": [v_scale[v_ok]],
                "eval_metric": "l1",
                "callbacks": [lightgbm.early_stopping(stopping_rounds, verbose=False)],
            }
        self.model.fit(inputs, target, **{self._weight_arg(): scale[usable]}, **extra)
        if extra:
            self.best_iteration = int(self.model.best_iteration_)

    def predict(self, rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        """Features only; `history` is not used (history features are already past-only)."""
        if self.model is None:
            raise RuntimeError("Fit the model on training rows first.")
        design, scale = self._design(rows)
        out = np.full(len(rows), np.nan)
        usable = np.isfinite(scale) & (scale >= MIN_SCALE)
        if usable.any():
            ratio = np.asarray(self.model.predict(self._inputs(design[usable])), dtype=float)
            out[usable] = np.maximum(ratio, 0.0) * scale[usable]
        return pd.Series(out, index=rows.index)

    def usable(self, rows: pd.DataFrame) -> npt.NDArray[np.bool_]:
        """Rows with a usable scale: the rows the model fits on (with a value) or predicts."""
        _, scale = self._design(rows)
        return np.isfinite(scale) & (scale >= MIN_SCALE)

    def contributions(self, rows: pd.DataFrame) -> pd.DataFrame | None:
        """Each input column's additive contribution to the expected value, in the readings'
        unit, for the rows with a usable scale, plus a `bias` column (T020).

        LightGBM computes exact TreeSHAP values (`pred_contrib`) for the scaled target; they are
        multiplied by each row's scale. They add up to the expected value before clipping at
        zero. None for families without tree contributions. Contributions describe how the
        model arrives at its expected value: associations, not causes."""
        if self.family is not Family.LIGHTGBM or self.model is None:
            return None
        design, scale = self._design(rows)
        usable = np.isfinite(scale) & (scale >= MIN_SCALE)
        if not usable.any():
            return pd.DataFrame(columns=[*self.columns, "bias"], dtype=float)
        raw = np.asarray(
            self.model.predict(self._inputs(design[usable]), pred_contrib=True), dtype=float
        )
        frame = pd.DataFrame(
            raw * scale[usable][:, None], columns=[*self.columns, "bias"], index=rows.index[usable]
        )
        return frame

    # -- design matrix --------------------------------------------------------------------------

    def _design(self, rows: pd.DataFrame) -> tuple[pd.DataFrame, FloatArray]:
        design = self.features.loc[rows.index, self.inputs]
        if self.variant is Variant.FULL:
            scale = design["rolling_mean_168h"].to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                for column in HISTORY:
                    design[column] = design[column].to_numpy(dtype=float) / scale
        else:
            assert self.level is not None and self.profile is not None
            meters = rows["meter_id"]
            scale = meters.map(self.level).to_numpy(dtype=float)
            slots = pd.MultiIndex.from_arrays([meters, self._hour_of_week(rows.index)])
            with np.errstate(divide="ignore", invalid="ignore"):
                design["profile_ratio"] = self.profile.reindex(slots).to_numpy(dtype=float) / scale
        design["log_scale"] = np.log1p(np.clip(scale, 0.0, None))
        return design, scale

    def _hour_of_week(self, index: pd.Index) -> FloatArray:
        calendar = self.features.loc[index, ["day_of_week_local", "hour_local"]]
        return np.asarray(
            calendar["day_of_week_local"] * 24 + calendar["hour_local"], dtype=np.float64
        )

    def _inputs(self, design: pd.DataFrame) -> Any:
        if self.family is Family.RIDGE:
            frame = design[self.columns].copy()
            frame["hour_weekend"] = frame["hour_local"] + 24 * frame["is_weekend_local"]
            return frame
        # float32: the feature store is float32 already, and LightGBM trains on it natively;
        # float64 would double the input matrix's memory for no gain in a tree model (T043).
        return design[self.columns].to_numpy(dtype=np.float32)

    def _weight_arg(self) -> str:
        return "ridge__sample_weight" if self.family is Family.RIDGE else "sample_weight"

    def _estimator(self) -> Any:
        s = self.settings
        if self.family is Family.RIDGE:
            numeric = [c for c in self.columns if c not in RAW_CALENDAR]
            prepare = ColumnTransformer(
                [
                    (
                        "calendar",
                        OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ["hour_weekend", "month_local"],
                    ),
                    (
                        "numeric",
                        make_pipeline(
                            SimpleImputer(
                                strategy="median", add_indicator=True, keep_empty_features=True
                            ),
                            StandardScaler(),
                        ),
                        numeric,
                    ),
                ]
            )
            return Pipeline([("prepare", prepare), ("ridge", Ridge(alpha=float(s["alpha"])))])
        if self.family is Family.HIST_GBM:
            return HistGradientBoostingRegressor(
                max_iter=int(s["max_iter"]),
                learning_rate=float(s["learning_rate"]),
                max_leaf_nodes=int(s["max_leaf_nodes"]),
                min_samples_leaf=int(s["min_samples_leaf"]),
                early_stopping=False,
                random_state=self.seed,
            )
        objective = str(s.get("objective", "regression"))
        optional: dict[str, Any] = {}
        if objective == "huber":
            optional["alpha"] = float(s.get("alpha", 0.9))  # the Huber transition, ratio units
        return lightgbm.LGBMRegressor(
            objective=objective,
            n_estimators=int(s["n_estimators"]),
            learning_rate=float(s["learning_rate"]),
            num_leaves=int(s["num_leaves"]),
            min_child_samples=int(s["min_child_samples"]),
            colsample_bytree=float(s.get("feature_fraction", 1.0)),
            random_state=self.seed,
            deterministic=True,
            force_row_wise=True,
            n_jobs=int(s.get("n_jobs", 1)),  # results are reproducible for a fixed thread count
            verbose=-1,
            **optional,
        )


# ---------------------------------------------------------------------------
# Selection and comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """A model against seasonal-naive on the rows both predicted (and that have a value)."""

    model: str
    fold: str
    role: Role
    rows: int
    model_mae: float | None
    naive_mae: float | None
    model_wape: float | None
    naive_wape: float | None

    @property
    def improvement(self) -> float | None:
        """Relative MAE reduction against seasonal-naive; positive means better."""
        if self.model_mae is None or not self.naive_mae:
            return None
        return 1.0 - self.model_mae / self.naive_mae

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "fold": self.fold,
            "role": self.role.value,
            "common_rows": self.rows,
            "model_mae": self.model_mae,
            "seasonal_naive_mae": self.naive_mae,
            "model_wape": self.model_wape,
            "seasonal_naive_wape": self.naive_wape,
            "mae_improvement": None if self.improvement is None else round(self.improvement, 4),
        }


def compare_with_naive(result: BaselineRun, model: str) -> list[Comparison]:
    folds = {part.fold.name: part for part in result.split.folds}
    made, naive = result.predictions[model], result.predictions[SEASONAL_NAIVE]
    out = []
    for fold, role in sorted(set(made) & set(naive), key=lambda k: (k[0], list(Role).index(k[1]))):
        actual = folds[fold].rows(role)["value"].to_numpy(dtype=float)
        a = made[(fold, role)].to_numpy(dtype=float)
        b = naive[(fold, role)].to_numpy(dtype=float)
        common = ~(np.isnan(actual) | np.isnan(a) | np.isnan(b))
        m, n = (
            compute_metrics(actual[common], a[common]),
            compute_metrics(actual[common], b[common]),
        )
        out.append(Comparison(model, fold, role, int(common.sum()), m.mae, n.mae, m.wape, n.wape))
    return out


def overall(result: BaselineRun, name: str, role: Role) -> dict[str, float | int | None]:
    report = next(r for r in result.reports if r.forecaster.name == name)
    score = next(s for s in report.scores if s.role is role)
    o = score.overall
    return {
        "mae": o.mae,
        "rmse": o.rmse,
        "bias": o.bias,
        "wape": o.wape,
        "scored": o.scored,
        "missing_prediction": o.missing_prediction,
    }


@dataclass(frozen=True)
class Study:
    trials: list[dict[str, Any]]
    best: dict[str, FeatureModel]  # "family-variant" -> chosen settings
    winner: str  # "family-variant" with the lowest validation MAE
    future: BaselineRun  # best models and seasonal-naive on validation and test
    holdouts: list[BaselineRun]  # best models and seasonal-naive on test and unseen buildings


def study(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    features: pd.DataFrame,
    split_config: SplitConfig = DEFAULT_SPLIT,
    holdouts: Sequence[Holdout] = HOLDOUTS,
    grid: Mapping[Family, Sequence[Mapping[str, float]]] = GRID,
    log: Any = print,
) -> Study:
    """Choose settings per family and variant on validation, then score the choices once on
    test, and on unseen buildings under each holdout."""
    split = make_split(readings, split_config, buildings)
    trials: list[dict[str, Any]] = []
    best: dict[str, FeatureModel] = {}
    best_mae: dict[str, float] = {}
    for family, settings_list in grid.items():
        for variant in Variant:
            key = f"{family}-{variant}"
            for settings in settings_list:
                model = FeatureModel(family, variant, settings, features)
                started = time.perf_counter()
                result = run(split, [model], roles=(Role.VALIDATION,))
                scores = overall(result, model.name, Role.VALIDATION)
                seconds = round(time.perf_counter() - started, 1)
                trials.append({"model": model.name, **model.params, "validation": scores})
                log(f"  {model.name:70s} validation MAE {scores['mae']} ({seconds} s)")
                mae = scores["mae"]
                if isinstance(mae, float) and mae < best_mae.get(key, float("inf")):
                    best[key], best_mae[key] = model, mae
    winner = min(best_mae, key=lambda k: best_mae[k])
    chosen = [_fresh(m, features) for m in best.values()]
    future = run(split, [SeasonalNaive(), *chosen], roles=(Role.VALIDATION, Role.TEST))
    unseen = []
    for holdout in holdouts:
        config = SplitConfig(time=split_config.time, holdout=holdout)
        held = make_split(readings, config, buildings)
        models = [_fresh(m, features) for m in best.values()]
        unseen.append(run(held, [SeasonalNaive(), *models], roles=(Role.TEST, Role.TEST_UNSEEN)))
    return Study(trials=trials, best=best, winner=winner, future=future, holdouts=unseen)


def _fresh(model: FeatureModel, features: pd.DataFrame) -> FeatureModel:
    return FeatureModel(model.family, model.variant, model.settings, features, model.seed)


def decide(result: Study) -> dict[str, Any]:
    """The adoption decision. Seen buildings: the validation winner must have a lower test MAE
    than seasonal-naive on their common rows. Unseen buildings: the best full model (by
    validation) must beat seasonal-naive on held-out buildings under every holdout."""
    winner = result.best[result.winner]
    test = [c for c in compare_with_naive(result.future, winner.name) if c.role is Role.TEST]
    seen = bool(test) and all((c.improvement or 0.0) > 0 for c in test)
    full = min(
        (k for k in result.best if k.endswith(Variant.FULL)),
        key=lambda k: _validation_mae(result, result.best[k].name),
    )
    unseen_rows = [
        c
        for held in result.holdouts
        for c in compare_with_naive(held, result.best[full].name)
        if c.role is Role.TEST_UNSEEN
    ]
    unseen = bool(unseen_rows) and all((c.improvement or 0.0) > 0 for c in unseen_rows)
    return {
        "seen_buildings": {
            "candidate": winner.name,
            "chosen_by": "lowest validation MAE",
            "adopted": seen,
            "test_vs_seasonal_naive": [c.as_dict() for c in test],
        },
        "unseen_buildings": {
            "candidate": result.best[full].name,
            "chosen_by": "lowest validation MAE among full models (conditions models cannot "
            "forecast unseen buildings)",
            "adopted": unseen,
            "test_unseen_vs_seasonal_naive": [c.as_dict() for c in unseen_rows],
        },
        "rule": "Adopt only if the candidate's MAE is lower than seasonal-naive's on the rows both "
        "predicted, in every compared window; otherwise seasonal-naive stays the default.",
    }


def _validation_mae(result: Study, name: str) -> float:
    for trial in result.trials:
        if trial["model"] == name:
            scores = trial["validation"]
            assert isinstance(scores, dict)
            return float(scores["mae"])
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def summary(result: Study, decision: Mapping[str, Any]) -> dict[str, Any]:
    future = {
        name: {
            role.value: overall(result.future, name, role) for role in (Role.VALIDATION, Role.TEST)
        }
        for name in [SEASONAL_NAIVE, *(m.name for m in result.best.values())]
    }
    holdouts = []
    for held in result.holdouts:
        holdout = held.split.config.holdout
        assert holdout is not None
        rows = [
            c.as_dict()
            for model in result.best.values()
            for c in compare_with_naive(held, model.name)
        ]
        holdouts.append(
            {
                "holdout": holdout.model_dump(mode="json"),
                "held_out_buildings": list(held.split.holdout),
                "vs_seasonal_naive": rows,
            }
        )
    return {
        "models_version": MODELS_VERSION,
        "split": result.future.split.manifest(),
        "feature_set": feature_manifest(FeatureConfig()),
        "min_scale": MIN_SCALE,
        "grid_validation": result.trials,
        "chosen": {k: m.params for k, m in result.best.items()},
        "validation_winner": result.best[result.winner].name,
        "future_period": future,
        "future_period_vs_seasonal_naive": [
            c.as_dict()
            for m in result.best.values()
            for c in compare_with_naive(result.future, m.name)
        ],
        "unseen_buildings": holdouts,
        "decision": decision,
    }


def to_markdown(data: Mapping[str, Any]) -> str:
    def num(value: object, pct: bool = False) -> str:
        if not isinstance(value, float | int):
            return "—"
        return f"{value:.1%}" if pct else f"{value:.3f}"

    lines = [
        "# Model comparison (T014)",
        "",
        "Expected-consumption accuracy with observed weather, not forecast accuracy (D025). "
        "Settings and the winner were chosen on validation; test was scored once.",
        "",
        "## Future period (all rows each model predicted)",
        "",
        "| Model | Validation MAE | Test MAE | Test RMSE | Test bias | Test WAPE | Test rows "
        "scored | Test rows without prediction |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, roles in data["future_period"].items():
        v, t = roles["validation"], roles["test"]
        lines.append(
            f"| {name} | {num(v['mae'])} | {num(t['mae'])} | {num(t['rmse'])} | {num(t['bias'])} "
            f"| {num(t['wape'], True)} | {t['scored']:,} | {t['missing_prediction']:,} |"
        )
    lines += [
        "",
        "## Against seasonal-naive on common rows",
        "",
        "| Split | Model | Role | Rows | Model MAE | Seasonal-naive MAE | MAE reduction |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in data["future_period_vs_seasonal_naive"]:
        lines.append(_row("future period", c, num))
    for held in data["unseen_buildings"]:
        label = f"{held['holdout']['group_by']} holdout"
        for c in held["vs_seasonal_naive"]:
            lines.append(_row(label, c, num))
    decision = data["decision"]
    lines += [
        "",
        "## Decision",
        "",
        f"- Seen buildings: **{decision['seen_buildings']['candidate']}**, adopted: "
        f"**{'yes' if decision['seen_buildings']['adopted'] else 'no'}**",
        f"- Unseen buildings: **{decision['unseen_buildings']['candidate']}**, adopted: "
        f"**{'yes' if decision['unseen_buildings']['adopted'] else 'no'}**",
        f"- Rule: {decision['rule']}",
    ]
    return "\n".join(lines) + "\n"


def _row(label: str, c: Mapping[str, Any], num: Any) -> str:
    return (
        f"| {label} | {c['model']} | {c['role']} | {c['common_rows']:,} | {num(c['model_mae'])} | "
        f"{num(c['seasonal_naive_mae'])} | {num(c['mae_improvement'], True)} |"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.models",
        description="Train and compare ML forecasters against seasonal-naive on prepared data.",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        readings = pd.read_parquet(args.data / "readings.parquet")
        buildings = pd.read_parquet(args.data / "buildings.parquet")
        weather_path = args.data / "weather.parquet"
        weather = pd.read_parquet(weather_path) if weather_path.exists() else None
        enrichment = pd.read_parquet(args.enrichment) if args.enrichment else None
    except FileNotFoundError as exc:
        print(f"error: {exc}. Prepare the data first.", file=sys.stderr)
        return 1
    features = build_features(readings, buildings, weather, enrichment)
    result = study(readings, buildings, features)
    decision = decide(result)
    data = summary(result, decision)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_bytes(
        (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    (args.output / "comparison.md").write_bytes(to_markdown(data).encode("utf-8"))
    for report in result.future.reports:
        write_report(report, args.output / "future", report.forecaster.name)
    for held in result.holdouts:
        holdout = held.split.config.holdout
        assert holdout is not None
        for report in held.reports:
            write_report(
                report, args.output / f"{holdout.group_by}-holdout", report.forecaster.name
            )
    print(to_markdown(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
