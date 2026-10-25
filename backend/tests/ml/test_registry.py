"""T015 registry: round trips, atomic writes and promotion, integrity, and no-model handling.
Trained on the synthetic load in conftest (not real performance)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml import registry
from wattwise.ml.evaluation import CodeVersion
from wattwise.ml.models import Family, Variant
from wattwise.ml.registry import (
    CURRENT,
    MODEL_FILE,
    STATE_FILE,
    IncompatibleModelError,
    IntegrityError,
    NoModelError,
    RegistryError,
    Trained,
    current,
    load,
    main,
    promote,
    reevaluate,
    save,
    train,
    verify,
    versions,
)
from wattwise.ml.splits import Role, make_split

SMALL = {"n_estimators": 40.0, "learning_rate": 0.1, "num_leaves": 15.0, "min_child_samples": 20.0}
CODE = CodeVersion(package_version="0.1.0", git_commit="abc", git_dirty=False)
T1 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def data() -> tuple[pd.DataFrame, pd.DataFrame]:
    readings, weather = synthetic()
    return readings, features_of(readings, weather)


@pytest.fixture(scope="module")
def trained(data: tuple[pd.DataFrame, pd.DataFrame]) -> Trained:
    readings, features = data
    return train(readings, BUILDINGS, features, SPLIT, settings=SMALL)


def split_test_rows(data: tuple[pd.DataFrame, pd.DataFrame]) -> pd.DataFrame:
    """The split's test rows, without values."""
    return make_split(data[0], SPLIT).folds[0].rows(Role.TEST).drop(columns="value")


def test_a_saved_model_loads_and_predicts_exactly_the_same(
    trained: Trained, data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    readings, features = data
    rows = split_test_rows(data)

    version = save(trained, tmp_path, T1, CODE)
    promote(version, tmp_path)
    loaded = load(features, root=tmp_path)

    pd.testing.assert_series_equal(
        loaded.model.predict(rows, readings), trained.model.predict(rows, readings)
    )
    assert loaded.metadata.version == version == current(tmp_path)


def test_the_metadata_records_what_the_model_is_and_how_it_was_made(
    trained: Trained, tmp_path: Path
) -> None:
    version = save(trained, tmp_path, T1, CODE)
    m = verify(version, tmp_path)

    assert version.startswith("20261025T090000Z-") and m.created_at == "2026-10-25T09:00:00Z"
    assert (m.model.family, m.model.variant, m.model.seed) == ("lightgbm", "full", 0)
    assert m.model.settings == SMALL
    assert m.feature_set_version == "1" and m.horizon_hours == 168
    assert "log_scale" in m.feature_columns and "lag_168h" in m.feature_columns
    assert m.training.first == "2017-01-11T11:00:00Z"  # the first hour with a usable scale
    assert m.training.last == "2017-02-28T23:00:00Z"
    assert m.training.meters == 3 and m.training.data_rows == 3 * 100 * 24
    assert m.training.split_config_sha256 == SPLIT.sha256()
    assert m.code == CODE
    assert set(m.libraries) == {"lightgbm", "numpy", "pandas"}
    assert set(m.metrics) == {"validation", "test"} and m.metrics == trained.metrics
    assert set(m.files) == {MODEL_FILE, STATE_FILE}


def test_reevaluating_an_artifact_reproduces_its_recorded_metrics(
    trained: Trained, data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    readings, features = data
    version = save(trained, tmp_path, T1, CODE)

    again = reevaluate(load(features, version, tmp_path), readings, BUILDINGS)

    assert again == trained.metrics


def test_a_conditions_model_round_trips_its_scales_and_profiles(
    data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    readings, features = data
    conditions = train(
        readings, BUILDINGS, features, SPLIT, Family.LIGHTGBM, Variant.CONDITIONS, SMALL
    )
    rows = split_test_rows(data)

    version = save(conditions, tmp_path, T1, CODE)
    loaded = load(features, version, tmp_path)

    state = json.loads((tmp_path / version / STATE_FILE).read_text(encoding="utf-8"))
    assert set(state["level"]) == {"A-electricity", "B-electricity", "C-electricity"}
    assert len(state["profile"]) == 3 * 168
    pd.testing.assert_series_equal(
        loaded.model.predict(rows, readings), conditions.model.predict(rows, readings)
    )


def test_only_lightgbm_can_be_saved_because_nothing_is_pickled(
    data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    readings, features = data
    ridge = train(readings, BUILDINGS, features, SPLIT, Family.RIDGE, Variant.FULL, {"alpha": 1.0})

    with pytest.raises(RegistryError, match="never pickled"):
        save(ridge, tmp_path, T1, CODE)
    assert not any(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# No model, versions and promotion
# ---------------------------------------------------------------------------


def test_without_a_promoted_model_loading_raises_no_model_error(
    data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path, trained: Trained
) -> None:
    with pytest.raises(NoModelError):
        load(data[1], root=tmp_path / "missing")
    assert versions(tmp_path / "missing") == []

    save(trained, tmp_path, T1, CODE)  # saved but not promoted
    with pytest.raises(NoModelError):
        current(tmp_path)
    (tmp_path / CURRENT).write_text("\n", encoding="utf-8")
    with pytest.raises(NoModelError, match="empty"):
        load(data[1], root=tmp_path)


def test_promotion_switches_versions_and_keeps_the_old_one_for_rollback(
    trained: Trained, data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    first = save(trained, tmp_path, T1, CODE)
    second = save(trained, tmp_path, T2, CODE)
    promote(first, tmp_path)

    promote(second, tmp_path)
    assert current(tmp_path) == second
    promote(first, tmp_path)  # rollback

    assert current(tmp_path) == first
    assert versions(tmp_path) == [first, second]
    assert load(data[1], second, tmp_path).metadata.version == second
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([CURRENT, first, second])


def test_versions_are_never_overwritten(trained: Trained, tmp_path: Path) -> None:
    version = save(trained, tmp_path, T1, CODE)
    before = (tmp_path / version / MODEL_FILE).read_bytes()

    with pytest.raises(RegistryError, match="already exists"):
        save(trained, tmp_path, T1, CODE)
    assert (tmp_path / version / MODEL_FILE).read_bytes() == before


def test_a_failed_save_leaves_nothing_behind(
    trained: Trained, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = save(trained, tmp_path, T1, CODE)
    promote(good, tmp_path)
    calls = {"n": 0}
    real = registry._write_file

    def fail_on_second(path: Path, content: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(path, content)

    monkeypatch.setattr(registry, "_write_file", fail_on_second)
    with pytest.raises(OSError, match="disk full"):
        save(trained, tmp_path, T2, CODE)

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([CURRENT, good])
    assert current(tmp_path) == good


def test_a_failed_promotion_keeps_the_current_model(
    trained: Trained, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = save(trained, tmp_path, T1, CODE)
    other = save(trained, tmp_path, T2, CODE)
    promote(good, tmp_path)

    def fail(src: object, dst: object) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="rename failed"):
        promote(other, tmp_path)
    monkeypatch.undo()

    assert current(tmp_path) == good
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]


def test_a_missing_or_tampered_version_cannot_be_promoted_or_loaded(
    trained: Trained, data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    good = save(trained, tmp_path, T1, CODE)
    bad = save(trained, tmp_path, T2, CODE)
    promote(good, tmp_path)
    model_file = tmp_path / bad / MODEL_FILE
    model_file.write_bytes(model_file.read_bytes().replace(b"tree", b"TREE", 1))

    with pytest.raises(IntegrityError, match="SHA-256"):
        promote(bad, tmp_path)
    with pytest.raises(IntegrityError):
        load(data[1], bad, tmp_path)
    with pytest.raises(RegistryError, match="does not exist"):
        promote("20991231T000000Z-0123456789ab", tmp_path)
    assert current(tmp_path) == good


@pytest.mark.parametrize("name", ["../outside", "CURRENT", "x/../../y", ""])
def test_version_names_cannot_escape_the_registry(tmp_path: Path, name: str) -> None:
    (tmp_path / CURRENT).write_text(name or "bad name", encoding="utf-8")

    with pytest.raises(RegistryError, match="not a version name"):
        current(tmp_path)
    with pytest.raises(RegistryError, match="not a version name"):
        verify(name or "bad name", tmp_path)


def test_an_artifact_for_another_feature_set_is_refused(
    trained: Trained, data: tuple[pd.DataFrame, pd.DataFrame], tmp_path: Path
) -> None:
    version = save(trained, tmp_path, T1, CODE)
    path = tmp_path / version / "metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["feature_set_version"] = "0"
    path.write_text(json.dumps(metadata), encoding="utf-8")

    good = save(trained, tmp_path, T2, CODE)

    with pytest.raises(IncompatibleModelError, match="feature set 0"):
        load(data[1], version, tmp_path)
    with pytest.raises(IncompatibleModelError, match="lacks"):
        load(data[1].drop(columns="lag_168h"), good, tmp_path)


def test_unreadable_metadata_is_an_integrity_error(trained: Trained, tmp_path: Path) -> None:
    version = save(trained, tmp_path, T1, CODE)
    (tmp_path / version / "metadata.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(IntegrityError, match="not valid"):
        verify(version, tmp_path)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_the_command_line_trains_promotes_evaluates_and_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readings, weather = synthetic()
    folder = tmp_path / "data"
    folder.mkdir()
    readings.to_parquet(folder / "readings.parquet")
    BUILDINGS.to_parquet(folder / "buildings.parquet")
    weather.to_parquet(folder / "weather.parquet")
    root = ["--root", str(tmp_path / "models")]
    dates = [
        "--train-start", "2017-01-01T00:00Z", "--validation-start", "2017-03-01T00:00Z",
        "--test-start", "2017-03-22T00:00Z", "--test-end", "2017-04-11T00:00Z",
    ]  # fmt: skip

    assert main([*root, "list"]) == 0
    assert "no saved models" in capsys.readouterr().out
    assert main([*root, "evaluate", "--data", str(folder)]) == 1
    assert "No model has been promoted" in capsys.readouterr().err

    assert main([*root, "train", "--data", str(folder), *dates, "--promote"]) == 0
    out = capsys.readouterr().out
    assert "saved " in out and "current model:" in out
    assert main([*root, "evaluate", "--data", str(folder)]) == 0
    assert "recorded metrics reproduced exactly" in capsys.readouterr().out
    assert main([*root, "list"]) == 0
    listed = capsys.readouterr().out.strip().splitlines()
    assert len(listed) == 1 and listed[0].startswith("* ")

    changed = readings.assign(value=readings["value"] * np.float64(1.1))
    changed.to_parquet(folder / "readings.parquet")
    assert main([*root, "evaluate", "--data", str(folder)]) == 0
    assert "DIFFERENT from training" in capsys.readouterr().out
    assert main([*root, "promote", "20991231T000000Z-0123456789ab"]) == 1


def test_artifacts_are_git_ignored() -> None:
    gitignore = (Path(__file__).resolve().parents[3] / ".gitignore").read_text(encoding="utf-8")

    assert "artifacts/" in gitignore.splitlines()
    assert Path("../artifacts/models") == registry.DEFAULT_ROOT
