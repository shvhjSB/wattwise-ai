import dataclasses
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from wattwise.data.synthetic import generate
from wattwise.ml.splits import (
    Chronological,
    FoldSplit,
    Holdout,
    LeakageError,
    Role,
    RollingOrigin,
    Split,
    SplitConfig,
    Unused,
    make_split,
    read_config,
    select_holdout,
    verify,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
JAN = datetime(2017, 1, 1, tzinfo=UTC)


def at(day: float) -> datetime:
    """Midnight UTC on 2017-01-(1 + day); fractions give hours."""
    return JAN + day * DAY


def readings(
    buildings: Sequence[str] = ("A", "B"), days: int = 10, freq: str = "h"
) -> pd.DataFrame:
    """Canonical electricity readings from 2017-01-01: one meter per building, regular intervals."""
    times = pd.date_range(JAN, JAN + days * DAY, freq=freq, inclusive="left").as_unit("us")
    frames = [
        pd.DataFrame(
            {
                "timestamp": times,
                "meter_id": f"{b}-electricity",
                "building_id": b,
                "meter_type": "electricity",
                "unit": "kWh",
                "value": np.arange(len(times), dtype=float),
            }
        )
        for b in buildings
    ]
    return pd.concat(frames, ignore_index=True)


def chronological(gap: timedelta = timedelta(0), validation: bool = True) -> SplitConfig:
    return SplitConfig(
        time=Chronological(
            train_start=at(0),
            validation_start=at(5) if validation else None,
            test_start=at(7),
            test_end=at(10),
            gap=gap,
        )
    )


def counts(split: Split, fold: int = 0) -> dict[str, int]:
    part = split.folds[fold]
    return {role.value: p.size for role, p in part.positions.items()}


def keys(part: FoldSplit, role: Role) -> set[tuple[str, pd.Timestamp]]:
    rows = part.rows(role)
    return set(zip(rows["meter_id"], rows["timestamp"], strict=True))


def assert_time_ordered(part: FoldSplit) -> None:
    """Acceptance: the latest training timestamp is earlier than the earliest test timestamp."""
    later = [r for r in (Role.VALIDATION, Role.TEST, Role.TEST_UNSEEN) if r in part.positions]
    last_train = part.rows(Role.TRAIN)["timestamp"].max()
    for role in later:
        assert last_train < part.rows(role)["timestamp"].min(), (part.fold.name, role)
    if Role.VALIDATION in part.positions:
        last_validation = part.rows(Role.VALIDATION)["timestamp"].max()
        assert last_validation < part.rows(Role.TEST)["timestamp"].min()


# ---------------------------------------------------------------------------
# Chronological split
# ---------------------------------------------------------------------------


def test_chronological_split_assigns_whole_days_to_each_role() -> None:
    split = make_split(readings(), chronological())
    part = split.folds[0]

    assert counts(split) == {"train": 5 * 24 * 2, "validation": 2 * 24 * 2, "test": 3 * 24 * 2}
    assert sum(part.unused.values()) == 0
    assert part.rows(Role.TEST)["timestamp"].min() == pd.Timestamp(at(7))
    assert part.rows(Role.TRAIN)["timestamp"].max() == pd.Timestamp(at(5) - HOUR)
    assert_time_ordered(part)


def test_the_gap_is_left_out_before_validation_and_test() -> None:
    split = make_split(readings(), chronological(gap=DAY))
    part = split.folds[0]

    assert counts(split) == {"train": 4 * 24 * 2, "validation": 1 * 24 * 2, "test": 3 * 24 * 2}
    assert part.unused[Unused.GAP] == 2 * 24 * 2
    assert part.rows(Role.TRAIN)["timestamp"].max() == pd.Timestamp(at(4) - HOUR)
    test_start = part.rows(Role.TEST)["timestamp"].min()
    assert test_start - part.rows(Role.VALIDATION)["timestamp"].max() > DAY


def test_without_validation_training_runs_up_to_the_test_window() -> None:
    split = make_split(readings(), chronological(validation=False))

    assert counts(split) == {"train": 7 * 24 * 2, "test": 3 * 24 * 2}
    assert split.folds[0].fold.validation is None


def test_rows_outside_every_window_are_counted() -> None:
    config = SplitConfig(time=Chronological(train_start=at(2), test_start=at(6), test_end=at(8)))
    part = make_split(readings(), config).folds[0]

    assert part.unused[Unused.OUTSIDE_WINDOWS] == (2 + 2) * 24 * 2


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"train_start": datetime(2017, 1, 1)}, "timezone"),  # naive
        ({"test_end": at(7)}, "must be before its end"),
        ({"validation_start": at(8)}, "must be before its end"),
        ({"train_start": at(6)}, "must be before its end"),
        ({"gap": 2 * DAY}, "must be before its end"),  # validation window becomes empty
        ({"gap": -HOUR}, "greater than or equal"),
        ({"test_ends": at(9)}, "Extra inputs are not permitted"),  # a typo is not ignored
    ],
)
def test_invalid_chronological_configs_are_rejected(changes: dict[str, Any], message: str) -> None:
    fields: dict[str, Any] = {
        "train_start": at(0),
        "validation_start": at(5),
        "test_start": at(7),
        "test_end": at(10),
        **changes,
    }

    with pytest.raises(ValidationError, match=message):
        Chronological(**fields)


def test_boundaries_in_other_time_zones_are_converted_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    config = Chronological(
        train_start=datetime(2017, 1, 1, 2, tzinfo=plus_two),
        test_start=datetime(2017, 1, 8, 2, tzinfo=plus_two),
        test_end=datetime(2017, 1, 11, 2, tzinfo=plus_two),
    )

    assert config.test_start == at(7)
    assert SplitConfig(time=config).model_dump(mode="json")["time"]["test_start"] == (
        "2017-01-08T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# Interval rule: a reading belongs to a window only if its whole interval does
# ---------------------------------------------------------------------------


def test_a_reading_whose_interval_crosses_a_boundary_is_not_used() -> None:
    daily = readings(("D",), days=10, freq="D")
    config = SplitConfig(time=Chronological(train_start=at(0), test_start=at(6.5), test_end=at(10)))

    part = make_split(daily, config).folds[0]

    assert part.unused[Unused.STRADDLES_BOUNDARY] == 1  # the day 2017-01-07 spans 12:00
    assert part.ends[part.positions[Role.TRAIN]].max() <= pd.Timestamp(at(6.5)).value // 1000
    assert set(part.rows(Role.TEST)["timestamp"]) == {pd.Timestamp(at(d)) for d in (7, 8, 9)}


def test_sub_hourly_meters_use_their_own_interval() -> None:
    quarter = readings(("Q",), days=10, freq="15min")

    assert counts(make_split(quarter, chronological())) == {
        "train": 5 * 96,
        "validation": 2 * 96,
        "test": 3 * 96,
    }


def test_a_meter_with_a_single_reading_is_not_used() -> None:
    lone = pd.concat([readings(), readings(("Z",)).iloc[[30]]], ignore_index=True)

    part = make_split(lone, chronological()).folds[0]

    assert part.unused[Unused.UNKNOWN_INTERVAL] == 1
    assert "Z" not in set(
        part.readings.iloc[np.concatenate(list(part.positions.values()))]["building_id"]
    )


# ---------------------------------------------------------------------------
# Rolling origin (acceptance: in every fold, training ends before testing starts)
# ---------------------------------------------------------------------------


def test_rolling_origin_folds_expand_the_training_window() -> None:
    config = SplitConfig(
        time=RollingOrigin(
            train_start=at(0), first_test_start=at(4), horizon=DAY, step=DAY, n_folds=3
        )
    )

    split = make_split(readings(), config)

    assert [p.fold.name for p in split.folds] == ["fold-1", "fold-2", "fold-3"]
    assert [counts(split, k) for k in range(3)] == [
        {"train": d * 24 * 2, "test": 24 * 2} for d in (4, 5, 6)
    ]
    for part in split.folds:
        assert part.rows(Role.TRAIN)["timestamp"].min() == pd.Timestamp(at(0))
        assert_time_ordered(part)


@pytest.mark.parametrize("gap_hours", [0, 1, 24])
@pytest.mark.parametrize(("horizon_days", "step_days"), [(1, 1), (2, 1), (1, 2)])
def test_every_rolling_fold_tests_strictly_after_training(
    gap_hours: int, horizon_days: int, step_days: int
) -> None:
    config = SplitConfig(
        time=RollingOrigin(
            train_start=at(0),
            first_test_start=at(3),
            horizon=horizon_days * DAY,
            step=step_days * DAY,
            n_folds=3,
            gap=gap_hours * HOUR,
        ),
        holdout=Holdout(fraction=0.25, seed=1),
    )

    split = make_split(readings(("A", "B", "C", "D"), days=12), config)

    for part in split.folds:
        assert_time_ordered(part)
        last_train = part.rows(Role.TRAIN)["timestamp"].max()
        first_test = part.rows(Role.TEST)["timestamp"].min()
        assert first_test - (last_train + HOUR) >= gap_hours * HOUR
        assert not set(split.holdout) & set(part.rows(Role.TRAIN)["building_id"])


def test_fold_names_are_zero_padded() -> None:
    config = RollingOrigin(
        train_start=at(0), first_test_start=at(1), horizon=HOUR, step=HOUR, n_folds=12
    )

    assert [f.name for f in config.folds()][:2] == ["fold-01", "fold-02"]


def test_rolling_origin_rejects_a_gap_that_empties_the_first_training_window() -> None:
    with pytest.raises(ValidationError, match="must be before its end"):
        RollingOrigin(
            train_start=at(0), first_test_start=at(1), horizon=DAY, step=DAY, n_folds=2, gap=DAY
        )


# ---------------------------------------------------------------------------
# Building holdout (acceptance: held-out buildings never appear in training)
# ---------------------------------------------------------------------------

FIVE = ("A", "B", "C", "D", "E")


def test_held_out_buildings_are_only_tested_never_trained_or_validated() -> None:
    config = chronological().model_copy(update={"holdout": Holdout(fraction=0.4, seed=7)})

    split = make_split(readings(FIVE), config)
    part = split.folds[0]
    held = set(split.holdout)

    assert len(held) == 2
    assert not held & set(part.rows(Role.TRAIN)["building_id"])
    assert not held & set(part.rows(Role.VALIDATION)["building_id"])
    assert not held & set(part.rows(Role.TEST)["building_id"])
    assert set(part.rows(Role.TEST_UNSEEN)["building_id"]) == held
    assert part.unused[Unused.HELD_OUT] == len(held) * 7 * 24
    assert counts(split)["test_unseen"] == len(held) * 3 * 24


def test_a_site_holdout_holds_out_every_building_on_the_chosen_sites() -> None:
    sites = {"A": "north", "B": "north", "C": "south", "D": "south", "E": "east"}
    buildings = pd.DataFrame({"building_id": list(sites), "site_id": list(sites.values())})
    config = chronological().model_copy(
        update={"holdout": Holdout(fraction=0.34, seed=3, group_by="site")}
    )

    split = make_split(readings(FIVE), config, buildings)
    held_sites = {sites[b] for b in split.holdout}

    assert len(held_sites) == 1
    assert set(split.holdout) == {b for b, s in sites.items() if s in held_sites}
    assert not set(split.holdout) & set(split.folds[0].rows(Role.TRAIN)["building_id"])


def test_a_site_holdout_needs_every_building_s_site() -> None:
    holdout = Holdout(fraction=0.5, seed=0, group_by="site")
    partial = pd.DataFrame({"building_id": ["A"], "site_id": ["north"]})

    with pytest.raises(ValueError, match="needs the buildings table"):
        select_holdout(readings(), holdout)
    with pytest.raises(ValueError, match="No site for building"):
        select_holdout(readings(), holdout, partial)


@pytest.mark.parametrize(("fraction", "expected"), [(0.01, 1), (0.4, 2), (0.99, 4)])
def test_the_holdout_size_is_at_least_one_and_never_everything(
    fraction: float, expected: int
) -> None:
    assert len(select_holdout(readings(FIVE), Holdout(fraction=fraction, seed=0))) == expected


def test_a_holdout_needs_two_groups() -> None:
    with pytest.raises(ValueError, match="at least two buildings"):
        select_holdout(readings(("A",)), Holdout(fraction=0.5, seed=0))


def test_the_holdout_depends_on_the_seed_not_on_row_order() -> None:
    data = readings(FIVE)
    shuffled = data.sample(frac=1.0, random_state=0).reset_index(drop=True)

    first = select_holdout(data, Holdout(fraction=0.4, seed=11))

    assert first == select_holdout(shuffled, Holdout(fraction=0.4, seed=11))
    assert first == tuple(sorted(first))
    picks = {select_holdout(data, Holdout(fraction=0.4, seed=s)) for s in range(8)}
    assert len(picks) > 1, "the seed changes the holdout"


# ---------------------------------------------------------------------------
# Determinism (acceptance: splits are deterministic from their config)
# ---------------------------------------------------------------------------


def holdout_config() -> SplitConfig:
    return SplitConfig(
        time=RollingOrigin(
            train_start=at(0),
            first_test_start=at(5),
            horizon=DAY,
            step=DAY,
            n_folds=3,
            gap=HOUR,
        ),
        holdout=Holdout(fraction=0.4, seed=5),
    )


def test_the_same_config_gives_the_same_split_and_manifest(tmp_path: Path) -> None:
    data = readings(FIVE)
    config = holdout_config()
    restored = SplitConfig.model_validate_json(config.model_dump_json())

    first, second = make_split(data, config), make_split(data, restored)
    write_manifest(first, tmp_path / "a.json")
    write_manifest(second, tmp_path / "b.json")

    assert restored == config
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    for a, b in zip(first.folds, second.folds, strict=True):
        assert a.positions.keys() == b.positions.keys()
        for role in a.positions:
            np.testing.assert_array_equal(a.positions[role], b.positions[role])


def test_row_order_does_not_change_the_split() -> None:
    data = readings(FIVE)
    shuffled = data.sample(frac=1.0, random_state=1).reset_index(drop=True)

    original, reordered = make_split(data, holdout_config()), make_split(shuffled, holdout_config())

    assert original.manifest() == reordered.manifest()
    for a, b in zip(original.folds, reordered.folds, strict=True):
        for role in a.positions:
            assert keys(a, role) == keys(b, role)


def test_a_saved_manifest_re_creates_the_split(tmp_path: Path) -> None:
    data = readings(FIVE)
    split = make_split(data, holdout_config())
    write_manifest(split, tmp_path / "split.json")

    config = read_config(tmp_path / "split.json")

    assert config == holdout_config()
    assert make_split(data, config).manifest() == split.manifest()


def test_an_edited_or_foreign_manifest_is_rejected(tmp_path: Path) -> None:
    write_manifest(make_split(readings(FIVE), holdout_config()), tmp_path / "split.json")
    manifest = json.loads((tmp_path / "split.json").read_text(encoding="utf-8"))

    edited = {**manifest, "config": {**manifest["config"], "holdout": None}}
    (tmp_path / "edited.json").write_text(json.dumps(edited), encoding="utf-8")
    foreign = {**manifest, "split_version": "0"}
    (tmp_path / "foreign.json").write_text(json.dumps(foreign), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match its recorded config_sha256"):
        read_config(tmp_path / "edited.json")
    with pytest.raises(ValueError, match="split version"):
        read_config(tmp_path / "foreign.json")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_the_manifest_records_config_windows_roles_and_unused_rows() -> None:
    config = chronological(gap=DAY).model_copy(update={"holdout": Holdout(fraction=0.4, seed=7)})
    data = readings(FIVE)
    data.loc[data.index[:10], "value"] = np.nan  # missing values are kept, not counted as values

    manifest = make_split(data, config).manifest()
    fold = manifest["folds"][0]

    assert manifest["split_version"] == "1"
    assert manifest["config_sha256"] == config.sha256()
    assert manifest["config"]["time"]["gap"] == "P1D"
    assert manifest["config"]["holdout"] == {"fraction": 0.4, "seed": 7, "group_by": "building"}
    assert len(manifest["holdout_building_ids"]) == 2
    assert fold["windows"] == {
        "train": {"start": "2017-01-01T00:00:00Z", "end": "2017-01-05T00:00:00Z"},
        "validation": {"start": "2017-01-06T00:00:00Z", "end": "2017-01-07T00:00:00Z"},
        "test": {"start": "2017-01-08T00:00:00Z", "end": "2017-01-11T00:00:00Z"},
    }
    assert list(fold["roles"]) == ["train", "validation", "test", "test_unseen"]
    assert fold["roles"]["test_unseen"] == {
        "rows": 2 * 72,
        "values": 2 * 72,
        "meters": 2,
        "buildings": 2,
        "first": "2017-01-08T00:00:00Z",
        "last": "2017-01-10T23:00:00Z",
    }
    train = fold["roles"]["train"]
    seen_a = "A" not in manifest["holdout_building_ids"]
    assert train["values"] == train["rows"] - (10 if seen_a else 0)
    assert fold["unused_rows"]["gap"] == 2 * 24 * 5
    assert set(fold["unused_rows"]) == {u.value for u in Unused}


# ---------------------------------------------------------------------------
# Verification catches leakage (the split re-checks itself on the rows)
# ---------------------------------------------------------------------------


def tampered(part: FoldSplit, **positions: np.ndarray[Any, Any]) -> FoldSplit:
    updated = {**part.positions, **{Role(k): v.astype(np.int64) for k, v in positions.items()}}
    return dataclasses.replace(part, positions=updated)


def test_verification_rejects_test_rows_in_training() -> None:
    part = make_split(readings(), chronological()).folds[0]
    moved = part.positions[Role.TEST][:1]
    bad = tampered(
        part,
        train=np.concatenate([part.positions[Role.TRAIN], moved]),
        test=part.positions[Role.TEST][1:],
    )

    with pytest.raises(LeakageError, match="train rows fall outside the train window"):
        verify(bad)


def test_verification_rejects_rows_with_two_roles() -> None:
    part = make_split(readings(), chronological()).folds[0]
    bad = tampered(part, validation=np.concatenate([part.positions[Role.VALIDATION], [0]]))

    with pytest.raises(LeakageError, match="more than one role"):
        verify(bad)


def test_verification_rejects_held_out_buildings_in_training() -> None:
    split = make_split(
        readings(FIVE),
        chronological().model_copy(update={"holdout": Holdout(fraction=0.4, seed=7)}),
    )
    part = split.folds[0]
    claimed = (*split.holdout, sorted(set(FIVE) - set(split.holdout))[0])

    with pytest.raises(LeakageError, match="held-out buildings in training"):
        verify(part, claimed)


def test_verification_rejects_training_after_testing_even_in_a_tampered_fold() -> None:
    part = make_split(readings(), chronological(validation=False)).folds[0]
    # model_copy skips validation: the train window now overlaps the test window.
    stretched = part.fold.model_copy(
        update={"train": part.fold.train.model_copy(update={"end": at(10)})}
    )
    test = part.positions[Role.TEST]
    last_day = part.readings.iloc[test]["timestamp"] >= pd.Timestamp(at(9))
    bad = dataclasses.replace(
        part,
        fold=stretched,
        positions={
            Role.TRAIN: np.concatenate([part.positions[Role.TRAIN], test[last_day.to_numpy()]]),
            Role.TEST: test[~last_day.to_numpy()],
        },
    )

    with pytest.raises(LeakageError, match="train data reaches"):
        verify(bad)


# ---------------------------------------------------------------------------
# Inputs and empty roles
# ---------------------------------------------------------------------------


def test_a_window_without_data_is_an_error() -> None:
    config = SplitConfig(time=Chronological(train_start=at(0), test_start=at(20), test_end=at(30)))

    with pytest.raises(ValueError, match="no readings for test"):
        make_split(readings(), config)


def test_readings_must_be_canonical() -> None:
    naive = readings().assign(timestamp=lambda f: f["timestamp"].dt.tz_localize(None))

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        make_split(naive, chronological())
    with pytest.raises(ValueError, match="lack column"):
        make_split(readings().drop(columns="meter_id"), chronological())


def test_the_evaluation_doc_lists_every_role_and_unused_reason() -> None:
    doc = (REPO_ROOT / "docs" / "EVALUATION.md").read_text(encoding="utf-8")
    table_rows = {line.split("|")[1].strip() for line in doc.splitlines() if line.startswith("| `")}

    assert {f"`{label}`" for label in (*Role, *Unused)} <= table_rows


# ---------------------------------------------------------------------------
# The synthetic fixture
# ---------------------------------------------------------------------------


def test_the_synthetic_fixture_splits_cleanly() -> None:
    dataset = generate()
    first = dataset.readings["timestamp"].min().to_pydatetime()
    config = SplitConfig(
        time=Chronological(
            train_start=first,
            validation_start=first + timedelta(weeks=5),
            test_start=first + timedelta(weeks=6),
            test_end=first + timedelta(weeks=8),
        ),
        holdout=Holdout(fraction=0.25, seed=2016, group_by="site"),
    )

    split = make_split(dataset.readings, config, dataset.buildings)
    part = split.folds[0]

    assert len(split.holdout) >= 1
    assert sum(part.unused.values()) == part.unused[Unused.HELD_OUT]
    assert_time_ordered(part)
