"""T043 full-scale study on a small synthetic store (not real performance)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, synthetic
from wattwise.ml.baselines import SeasonalNaive
from wattwise.ml.fullscale import (
    lagged,
    load_features,
    load_keys,
    main,
    run_study,
    sample_rows,
)
from wattwise.ml.registry import current, verify
from wattwise.ml.scale import build_store, load_store
from wattwise.ml.splits import Holdout

SMALL = tuple(
    {
        "learning_rate": 0.1,
        "n_estimators": 80,
        "min_child_samples": 20,
        "feature_fraction": 0.8,
        "n_jobs": 1,
        "objective": objective,
        "num_leaves": 15,
    }
    for objective in ("regression", "regression_l1")
)
HOLDOUT = (Holdout(fraction=0.34, seed=0, group_by="building"),)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    readings, weather = synthetic()
    folder = tmp_path_factory.mktemp("store")
    build_store(readings, BUILDINGS, weather, None, folder, batch_meters=2, log=lambda _: None)
    return folder


def study(store: Path, root: Path, output: Path, promote: bool = False) -> dict[str, Any]:
    return run_study(
        store, BUILDINGS, output, root, SPLIT, SMALL, HOLDOUT, fraction=0.5,
        stopping_rounds=10, promote_if_adopted=promote, log=lambda _: None,
    )  # fmt: skip


def test_samples_are_seeded_and_only_from_candidates() -> None:
    candidates = np.arange(10_000) % 3 != 0

    first, again = sample_rows(candidates, 0.25, 7), sample_rows(candidates, 0.25, 7)

    np.testing.assert_array_equal(first, again)
    assert candidates[first].all()
    assert len(first) == pytest.approx(0.25 * candidates.sum(), rel=0.05)
    assert not np.array_equal(first, sample_rows(candidates, 0.25, 8))


def test_the_fast_lag_matches_the_seasonal_naive_baseline(store: Path) -> None:
    keys = load_keys(store)
    ids = np.arange(len(keys), dtype=np.int64)[::7]

    fast = lagged(keys, ids)
    slow = SeasonalNaive().predict(keys.loc[ids].drop(columns="value"), keys)

    np.testing.assert_array_equal(fast.to_numpy(), slow.to_numpy())


def test_features_load_for_exactly_the_requested_rows(store: Path) -> None:
    whole = load_store(store)
    ids = np.array([5, 0, 4000, 7199], dtype=np.int64)

    part = load_features(store, ids)

    assert part.index.tolist() == [0, 5, 4000, 7199]
    expected = whole.loc[[0, 5, 4000, 7199], part.columns]
    np.testing.assert_array_equal(part.to_numpy(), expected.to_numpy())


def test_a_study_chooses_on_validation_and_saves_an_adopted_refit(
    store: Path, tmp_path: Path
) -> None:
    summary = study(store, tmp_path / "models", tmp_path / "out", promote=True)

    validation = [t["validation"]["mae"] for t in summary["search"]]
    assert (
        summary["chosen"]["settings"]["objective"] == SMALL[int(np.argmin(validation))]["objective"]
    )
    assert all(
        t["best_iteration"] is not None and t["best_iteration"] <= 80 for t in summary["search"]
    )
    test = summary["test"]
    assert test["chosen"]["common_rows"] > 1000 and "refit" in test and test["per_site"]
    assert "unavailable" in test["sample_trained_model"]
    assert {u["holdout"]["group_by"] for u in summary["unseen"]} == {"building"}
    assert summary["unseen"][0]["test_unseen"]["common_rows"] > 0
    decision = summary["decision"]
    assert decision["adopted"] == (test["chosen"]["mae_reduction"] > 0)
    if decision["adopted"]:
        version = current(tmp_path / "models")
        assert version == decision["artifact"]
        metadata = verify(version, tmp_path / "models")
        assert set(metadata.metrics) == {"test"}
        assert metadata.training.split_config["time"]["validation_start"] is None
        assert metadata.model.settings["n_estimators"] == summary["chosen"]["best_iteration"]
    assert (tmp_path / "out" / "fullscale.md").exists()
    assert (tmp_path / "out" / "test" / "chosen.json").exists()


def test_a_study_is_reproducible(store: Path, tmp_path: Path) -> None:
    first = study(store, tmp_path / "a", tmp_path / "out-a")
    second = study(store, tmp_path / "b", tmp_path / "out-b")

    def stable(s: dict[str, Any]) -> str:
        trimmed = {k: v for k, v in s.items() if k != "seconds"}
        trimmed["search"] = [{k: v for k, v in t.items() if k != "seconds"} for t in s["search"]]
        artifact = s["decision"]["artifact"]  # "<created_at>-<model hash>": keep the hash
        trimmed["decision"] = {**s["decision"], "artifact": artifact and artifact.split("-")[-1]}
        # The reference model's absence is reported with each run's own registry path.
        trimmed["test"] = {k: v for k, v in s["test"].items() if k != "sample_trained_model"}
        return json.dumps(trimmed, sort_keys=True, default=str)

    assert stable(first) == stable(second)


def test_the_command_line_needs_its_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data", str(tmp_path), "--store", str(tmp_path / "none")]) == 1
    assert "error:" in capsys.readouterr().err
