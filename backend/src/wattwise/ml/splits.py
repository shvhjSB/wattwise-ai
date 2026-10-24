"""Leakage-safe evaluation splits (docs/EVALUATION.md).

A split never shuffles rows. It is defined by time windows, so a model is always tested on a period
after the data it learned from:

- `Chronological`: one train / optional validation / test split.
- `RollingOrigin`: several folds whose training window expands from a fixed start.
- `Holdout` (optional, with either): buildings, or whole sites, that are never used for training or
  validation. They are tested only in the test window, under the role `test_unseen`.

A reading belongs to a window only if its whole interval, [timestamp, timestamp + the meter's
inferred interval), lies inside it. `make_split` gives every row a role or a reason for not using
it, then re-checks the result on the actual rows and raises `LeakageError` on any violation. The
same config and data always give the same split; the manifest records the config and what each
role contains.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import combinations, pairwise
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from wattwise.data.quality import infer_interval

SPLIT_VERSION: Final = "1"
REQUIRED_COLUMNS: Final = ("timestamp", "meter_id", "building_id", "value")

IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)


class LeakageError(ValueError):
    """A split's rows would let later or held-out data into training or validation."""


class Role(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"  # buildings also used for training, in the later test window
    TEST_UNSEEN = "test_unseen"  # held-out buildings, test window only


class Unused(StrEnum):
    """Why a reading has no role. Counted per fold in the manifest."""

    HELD_OUT = "held_out_before_test"  # a held-out building's rows in the train/validation window
    GAP = "gap"  # between two windows
    STRADDLES_BOUNDARY = "straddles_boundary"  # the reading's interval crosses a window boundary
    OUTSIDE_WINDOWS = "outside_windows"  # before the first or after the last window
    UNKNOWN_INTERVAL = "unknown_interval"  # a meter with a single timestamp


#: Time order of the roles; roles in the same group share a window.
_ROLE_ORDER: Final = ((Role.TRAIN,), (Role.VALIDATION,), (Role.TEST, Role.TEST_UNSEEN))
_CODE: Final = {label: code for code, label in enumerate((*Role, *Unused))}


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
NonNegativeDuration = Annotated[timedelta, Field(ge=timedelta(0))]
PositiveDuration = Annotated[timedelta, Field(gt=timedelta(0))]


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Window(_Config):
    """A half-open UTC window: start <= t < end."""

    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} must be before its end {self.end}")
        return self


class Fold(_Config):
    name: str
    train: Window
    validation: Window | None = None
    test: Window

    @model_validator(mode="after")
    def _in_time_order(self) -> Self:
        for (earlier, a), (later, b) in pairwise(self.windows()):
            if a.end > b.start:
                raise ValueError(
                    f"the {earlier} window must end by the start of the {later} window"
                )
        return self

    def windows(self) -> tuple[tuple[Role, Window], ...]:
        """The windows in time order. `test_unseen` shares the test window."""
        ordered = [(Role.TRAIN, self.train)]
        if self.validation is not None:
            ordered.append((Role.VALIDATION, self.validation))
        ordered.append((Role.TEST, self.test))
        return tuple(ordered)


class Chronological(_Config):
    """Train on [train_start, validation_start - gap), validate on [validation_start,
    test_start - gap) and test on [test_start, test_end). Without `validation_start`, training runs
    to test_start - gap."""

    kind: Literal["chronological"] = "chronological"
    train_start: UtcDatetime
    validation_start: UtcDatetime | None = None
    test_start: UtcDatetime
    test_end: UtcDatetime
    gap: NonNegativeDuration = timedelta(0)

    @model_validator(mode="after")
    def _valid_windows(self) -> Self:
        self.folds()
        return self

    def folds(self) -> tuple[Fold, ...]:
        test = Window(start=self.test_start, end=self.test_end)
        if self.validation_start is None:
            train = Window(start=self.train_start, end=self.test_start - self.gap)
            return (Fold(name="chronological", train=train, test=test),)
        train = Window(start=self.train_start, end=self.validation_start - self.gap)
        validation = Window(start=self.validation_start, end=self.test_start - self.gap)
        return (Fold(name="chronological", train=train, validation=validation, test=test),)


class RollingOrigin(_Config):
    """`n_folds` folds with an expanding training window. Fold k (from 0) tests on
    [first_test_start + k * step, + horizon) and trains on [train_start, its test start - gap).
    Multiples of 7 days keep the weekday mix of every window equal."""

    kind: Literal["rolling_origin"] = "rolling_origin"
    train_start: UtcDatetime
    first_test_start: UtcDatetime
    horizon: PositiveDuration
    step: PositiveDuration
    n_folds: int = Field(ge=1)
    gap: NonNegativeDuration = timedelta(0)

    @model_validator(mode="after")
    def _valid_windows(self) -> Self:
        self.folds()
        return self

    def folds(self) -> tuple[Fold, ...]:
        digits = len(str(self.n_folds))
        folds = []
        for k in range(self.n_folds):
            test_start = self.first_test_start + k * self.step
            folds.append(
                Fold(
                    name=f"fold-{k + 1:0{digits}d}",
                    train=Window(start=self.train_start, end=test_start - self.gap),
                    test=Window(start=test_start, end=test_start + self.horizon),
                )
            )
        return tuple(folds)


class Holdout(_Config):
    """Hold out round(fraction x groups) buildings or whole sites (at least one, never all),
    drawn with numpy's default_rng(seed) from the sorted group IDs. A site holdout is stricter:
    buildings on one site share weather and often schedules."""

    fraction: float = Field(gt=0, lt=1)
    seed: int
    group_by: Literal["building", "site"] = "building"


class SplitConfig(_Config):
    time: Annotated[Chronological | RollingOrigin, Field(discriminator="kind")]
    holdout: Holdout | None = None

    def sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, eq=False)
class FoldSplit:
    """One fold's assignment, as row positions into the source readings (which are not copied)."""

    fold: Fold
    readings: pd.DataFrame
    positions: Mapping[Role, IntArray]
    unused: Mapping[Unused, int]
    ends: IntArray  # per source row: end of its interval in microseconds (= start if unknown)

    def rows(self, role: Role) -> pd.DataFrame:
        return self.readings.iloc[self.positions[role]]


@dataclass(frozen=True, eq=False)
class Split:
    config: SplitConfig
    holdout: tuple[str, ...]  # held-out building IDs, sorted
    folds: tuple[FoldSplit, ...]

    def manifest(self) -> dict[str, Any]:
        return {
            "split_version": SPLIT_VERSION,
            "config_sha256": self.config.sha256(),
            "config": self.config.model_dump(mode="json"),
            "holdout_building_ids": list(self.holdout),
            "folds": [_fold_manifest(part) for part in self.folds],
        }


# ---------------------------------------------------------------------------
# Building the split
# ---------------------------------------------------------------------------


def make_split(
    readings: pd.DataFrame, config: SplitConfig, buildings: pd.DataFrame | None = None
) -> Split:
    """Assign canonical readings to roles for every fold of `config`, and verify the result.
    `buildings` (with `site_id`) is needed only for a site holdout."""
    _check_readings(readings)
    holdout = () if config.holdout is None else select_holdout(readings, config.holdout, buildings)
    starts = _microseconds(readings["timestamp"])
    ends = starts + _intervals(readings["meter_id"], starts)
    held = readings["building_id"].isin(holdout).to_numpy(dtype=bool)
    folds = tuple(
        _assign(readings, fold, starts, ends, held, bool(holdout)) for fold in config.time.folds()
    )
    for part in folds:
        verify(part, holdout)
        empty = [role.value for role, positions in part.positions.items() if positions.size == 0]
        if empty:
            raise ValueError(
                f"{part.fold.name}: no readings for {', '.join(empty)}. Check that the windows lie "
                f"within the data ({_iso(readings['timestamp'].min())} to "
                f"{_iso(readings['timestamp'].max())})."
            )
    return Split(config=config, holdout=holdout, folds=folds)


def select_holdout(
    readings: pd.DataFrame, holdout: Holdout, buildings: pd.DataFrame | None = None
) -> tuple[str, ...]:
    """The held-out building IDs, sorted. Independent of row order."""
    ids = sorted(set(readings["building_id"].astype(str)))
    if holdout.group_by == "site":
        if buildings is None:
            raise ValueError("A site holdout needs the buildings table (building_id, site_id).")
        site_of = dict(
            zip(buildings["building_id"].astype(str), buildings["site_id"].astype(str), strict=True)
        )
        unknown = [b for b in ids if b not in site_of]
        if unknown:
            raise ValueError(f"No site for building(s) {unknown[:5]} in the buildings table.")
        group_of = {b: site_of[b] for b in ids}
    else:
        group_of = {b: b for b in ids}
    groups = sorted(set(group_of.values()))
    if len(groups) < 2:
        raise ValueError(f"A holdout needs at least two {holdout.group_by}s; found {len(groups)}.")
    count = min(max(1, round(holdout.fraction * len(groups))), len(groups) - 1)
    rng = np.random.default_rng(holdout.seed)
    chosen = {groups[int(i)] for i in rng.choice(len(groups), size=count, replace=False)}
    return tuple(b for b in ids if group_of[b] in chosen)


def verify(part: FoldSplit, holdout: Sequence[str] = ()) -> None:
    """Re-check one fold on its actual rows; raise LeakageError on any violation."""
    name = part.fold.name
    assigned = np.concatenate([np.asarray(p, dtype=np.int64) for p in part.positions.values()])
    if (np.bincount(assigned, minlength=len(part.readings)) > 1).any():
        raise LeakageError(f"{name}: a reading is assigned to more than one role.")

    starts = _microseconds(part.readings["timestamp"])
    windows = {**dict(part.fold.windows()), Role.TEST_UNSEEN: part.fold.test}
    for role, positions in part.positions.items():
        if positions.size and (
            starts[positions].min() < _to_microseconds(windows[role].start)
            or part.ends[positions].max() > _to_microseconds(windows[role].end)
        ):
            raise LeakageError(f"{name}: {role} rows fall outside the {role} window.")

    present = {role: p for role, p in part.positions.items() if p.size}
    groups = [[present[role] for role in group if role in present] for group in _ROLE_ORDER]
    for (i, earlier), (j, later) in combinations(enumerate(groups), 2):
        if not earlier or not later:
            continue
        last_start = max(int(starts[p].max()) for p in earlier)
        last_end = max(int(part.ends[p].max()) for p in earlier)
        first_start = min(int(starts[p].min()) for p in later)
        if last_start >= first_start or last_end > first_start:
            raise LeakageError(
                f"{name}: {_ROLE_ORDER[i][0]} data reaches {_iso_us(last_end)}, after the "
                f"{_ROLE_ORDER[j][0]} data starts ({_iso_us(first_start)})."
            )

    held = set(holdout)
    codes, names = pd.factorize(part.readings["building_id"])
    buildings = {
        role: {str(names[c]) for c in np.unique(codes[positions])}
        for role, positions in part.positions.items()
    }
    leaked = held & (buildings[Role.TRAIN] | buildings.get(Role.VALIDATION, set()))
    if leaked:
        raise LeakageError(
            f"{name}: held-out buildings in training or validation: {sorted(leaked)}"
        )
    if held & buildings[Role.TEST]:
        raise LeakageError(f"{name}: held-out buildings in the seen-building test set.")
    if buildings.get(Role.TEST_UNSEEN, set()) - held:
        raise LeakageError(f"{name}: test_unseen contains buildings that are not held out.")


def _assign(
    readings: pd.DataFrame,
    fold: Fold,
    starts: IntArray,
    ends: IntArray,
    held: BoolArray,
    with_unseen: bool,
) -> FoldSplit:
    windows = fold.windows()
    known = ends > starts
    code = np.full(len(starts), _CODE[Unused.OUTSIDE_WINDOWS], dtype=np.int8)
    first, last = _to_microseconds(windows[0][1].start), _to_microseconds(windows[-1][1].end)
    code[(ends > first) & (starts < last)] = _CODE[Unused.STRADDLES_BOUNDARY]
    for (_, a), (_, b) in pairwise(windows):
        gap = (starts >= _to_microseconds(a.end)) & (ends <= _to_microseconds(b.start))
        code[gap] = _CODE[Unused.GAP]
    for role, window in windows:
        inside = (starts >= _to_microseconds(window.start)) & (ends <= _to_microseconds(window.end))
        code[inside & ~held] = _CODE[role]
        code[inside & held] = _CODE[Role.TEST_UNSEEN if role is Role.TEST else Unused.HELD_OUT]
    code[~known] = _CODE[Unused.UNKNOWN_INTERVAL]

    roles = [role for role, _ in windows] + ([Role.TEST_UNSEEN] if with_unseen else [])
    return FoldSplit(
        fold=fold,
        readings=readings,
        positions={r: np.flatnonzero(code == _CODE[r]).astype(np.int64) for r in roles},
        unused={reason: int((code == _CODE[reason]).sum()) for reason in Unused},
        ends=ends,
    )


def _check_readings(readings: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in readings.columns]
    if missing:
        raise ValueError(
            f"readings lack column(s) {missing}; pass canonical readings (docs/DATA_CONTRACT.md)."
        )
    dtype = readings["timestamp"].dtype
    if not (isinstance(dtype, pd.DatetimeTZDtype) and str(dtype.tz) == "UTC"):
        raise ValueError(f"readings.timestamp must be timezone-aware UTC, not {dtype}.")


def _intervals(meter_ids: pd.Series, starts: IntArray) -> IntArray:
    """Each row's meter interval in microseconds (the quality engine's rule); 0 if unknown."""
    frame = pd.DataFrame({"meter": meter_ids.to_numpy(), "start": starts})
    interval: dict[object, int] = {}
    for meter, times in frame.groupby("meter", sort=False)["start"]:
        interval[meter] = infer_interval(np.diff(np.sort(times.to_numpy(dtype=np.int64)))) or 0
    return np.asarray(frame["meter"].map(interval), dtype=np.int64)


def _microseconds(timestamps: pd.Series) -> IntArray:
    return timestamps.to_numpy(dtype="datetime64[us]").astype(np.int64)


def _to_microseconds(value: datetime) -> int:
    return (value - _EPOCH) // _MICROSECOND


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _fold_manifest(part: FoldSplit) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for role in part.positions:
        rows = part.rows(role)
        roles[role.value] = {
            "rows": len(rows),
            "values": int(rows["value"].notna().sum()),
            "meters": int(rows["meter_id"].nunique()),
            "buildings": int(rows["building_id"].nunique()),
            "first": _iso(rows["timestamp"].min()) if len(rows) else None,
            "last": _iso(rows["timestamp"].max()) if len(rows) else None,
        }
    return {
        "name": part.fold.name,
        "windows": {role.value: w.model_dump(mode="json") for role, w in part.fold.windows()},
        "roles": roles,
        "unused_rows": {reason.value: count for reason, count in part.unused.items()},
    }


def write_manifest(split: Split, path: Path) -> None:
    """Write the manifest as deterministic JSON (LF, trailing newline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(split.manifest(), indent=2) + "\n").encode("utf-8"))


def read_config(path: Path) -> SplitConfig:
    """The config of a saved manifest, checked against its recorded hash, to re-create a split."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("split_version") != SPLIT_VERSION:
        raise ValueError(
            f"{path}: split version {manifest.get('split_version')!r}, expected {SPLIT_VERSION!r}."
        )
    config = SplitConfig.model_validate(manifest["config"])
    if config.sha256() != manifest.get("config_sha256"):
        raise ValueError(f"{path}: the config does not match its recorded config_sha256.")
    return config


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_us(microseconds: int) -> str:
    return _iso(pd.Timestamp(microseconds, unit="us", tz="UTC"))
