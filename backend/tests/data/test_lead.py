import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.data.conftest import BDG2Builder
from wattwise.data.lead import (
    COMMIT,
    DEFAULT_DESTINATION,
    DEFAULT_OUTPUT,
    FILE,
    LICENCE_STATUS,
    MEMBER,
    Reason,
    main,
    prepare_labels,
    read_lead,
    write,
)
from wattwise.data.time_convention import Clock

CLOCKS = {"Std": Clock.STANDARD, "Wall": Clock.WALL_CLOCK, "Undet": Clock.UNDETERMINED}
METADATA = pd.DataFrame(
    {
        "building_id": ["S1", "W1", "U1"],
        "building_id_kaggle": [10.0, 20.0, 30.0],  # as in BDG2: float, with gaps elsewhere
        "site_id": ["Std", "Wall", "Undet"],
        "timezone": ["US/Eastern", "US/Pacific", "Europe/London"],
    }
)
#: Local naive hours around both 2016 US clock changes.
GRID = pd.DatetimeIndex(
    list(pd.date_range("2016-03-12", "2016-03-15", freq="h", inclusive="left"))
    + list(pd.date_range("2016-11-05", "2016-11-08", freq="h", inclusive="left"))
)
RAW = pd.DataFrame(
    {b: np.arange(len(GRID), dtype=float) + 100 * i for i, b in enumerate(("S1", "W1", "U1"))},
    index=GRID,
)
BLANK = pd.Timestamp("2016-03-12 05:00")
SCALED = pd.Timestamp("2016-03-12 06:00")  # LEAD's reading is 3.6 x BDG2's here
ANOMALIES = (pd.Timestamp("2016-03-14 12:00"), pd.Timestamp("2016-11-07 09:00"))


def lead_table() -> pd.DataFrame:
    """LEAD rows copied from RAW for kaggle ids 10, 20, 30 plus an unknown id 99."""
    frames = []
    for kaggle, column in ((10, "S1"), (20, "W1"), (30, "U1"), (99, "S1")):
        frames.append(
            pd.DataFrame(
                {
                    "building_id": kaggle,
                    "timestamp": GRID,
                    "meter_reading": RAW[column].to_numpy(),
                    "anomaly": GRID.isin(ANOMALIES).astype(int),
                }
            )
        )
    lead = pd.concat(frames, ignore_index=True)
    s1 = lead["building_id"] == 10
    lead.loc[s1 & (lead["timestamp"] == BLANK), "meter_reading"] = np.nan
    lead.loc[s1 & (lead["timestamp"] == SCALED), "meter_reading"] *= 3.6
    return lead


def labels_for(cleaned: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    result = prepare_labels(lead_table(), METADATA, RAW, cleaned, CLOCKS, corrections=())
    return result.labels, result.stats


def at(labels: pd.DataFrame, meter: str, utc: str) -> pd.Series:
    rows = labels[(labels["meter_id"] == meter) & (labels["timestamp"] == pd.Timestamp(utc))]
    assert len(rows) == 1, (meter, utc)
    return rows.iloc[0]


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def test_labels_join_to_bdg2_meters_in_utc_with_each_sites_clock() -> None:
    labels, _ = labels_for()

    # 2016-03-14 12:00 local is after the US spring change: standard time stays at -5 h, wall
    # clock time in the Pacific zone is -7 h.
    assert at(labels, "S1:electricity", "2016-03-14T17:00:00Z")["anomaly"] == 1
    assert at(labels, "W1:electricity", "2016-03-14T19:00:00Z")["anomaly"] == 1
    assert set(labels["meter_id"]) == {"S1:electricity", "W1:electricity"}
    assert str(labels["timestamp"].dtype) == "datetime64[us, UTC]"
    assert labels.equals(labels.sort_values(["meter_id", "timestamp"]).reset_index(drop=True))


def test_every_excluded_row_has_one_reason() -> None:
    labels, stats = labels_for()
    hours = len(GRID)

    assert stats["excluded_rows_by_reason"] == {
        Reason.NO_BDG2_BUILDING.value: hours,  # kaggle id 99
        Reason.UNDETERMINED_CLOCK.value: hours,  # U1
        Reason.NOT_ANNOTATED.value: 1,  # S1's blanked reading
        Reason.UNCONVERTIBLE_HOUR.value: 2,  # W1's spring non-existent and autumn repeated hours
    }
    assert len(labels) == 2 * hours - 3
    assert stats["label_buildings"] == 2
    assert stats["lead_rows"] == 4 * hours


def test_only_labels_are_used_and_disagreeing_readings_are_flagged() -> None:
    labels, stats = labels_for()

    scaled = at(labels, "S1:electricity", "2016-03-12T11:00:00Z")
    assert not scaled["lead_reading_matches_bdg2_raw"]
    assert "meter_reading" not in labels.columns, "LEAD's readings are not carried over"
    assert labels["lead_reading_matches_bdg2_raw"].sum() == len(labels) - 1
    assert stats["lead_reading_agreement_pct_at_anomalies"] == 100.0


def test_the_share_of_anomalies_removed_by_bdg2_cleaning_is_measured() -> None:
    cleaned = RAW.copy()
    cleaned.loc[ANOMALIES[0], "S1"] = np.nan  # cleaning removed one of S1's anomalous readings

    _, stats = labels_for(cleaned)

    # Usable anomalies: S1 and W1 at both times = 4; one has no cleaned reading.
    assert stats["anomalies_without_a_cleaned_bdg2_reading_pct"] == 25.0
    assert labels_for()[1]["anomalies_without_a_cleaned_bdg2_reading_pct"] is None


def test_the_exclusion_log_counts_rows_per_building_and_reason() -> None:
    result = prepare_labels(lead_table(), METADATA, RAW, None, CLOCKS, corrections=())
    log = result.exclusions.set_index(["reason", "building_id_kaggle"])["rows"]

    assert log[(Reason.NO_BDG2_BUILDING.value, 99)] == len(GRID)
    assert log[(Reason.UNDETERMINED_CLOCK.value, 30)] == len(GRID)
    assert log[(Reason.UNCONVERTIBLE_HOUR.value, 20)] == 2
    assert list(result.exclusions.columns) == [
        "reason",
        "building_id_kaggle",
        "bdg2_building_id",
        "site_id",
        "rows",
    ]


# ---------------------------------------------------------------------------
# Reading the file, outputs and the command line
# ---------------------------------------------------------------------------


def lead_zip(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = frame.assign(
        timestamp=pd.DatetimeIndex(frame["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MEMBER, table.to_csv(index=False))
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f: f.rename(columns={"anomaly": "label"}), "expected columns"),
        (lambda f: f.assign(anomaly=2), "must be 0 or 1"),
        (lambda f: pd.concat([f, f.iloc[[0]]]), "two rows for one timestamp"),
    ],
)
def test_a_malformed_file_is_rejected(
    tmp_path: Path, change: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    path = lead_zip(tmp_path / "lead.zip", change(lead_table().head(10)))

    with pytest.raises(ValueError, match=message):
        read_lead(path)


def test_the_file_reads_back_with_naive_local_timestamps(tmp_path: Path) -> None:
    lead = read_lead(lead_zip(tmp_path / "lead.zip", lead_table()))

    assert lead["timestamp"].dt.tz is None
    assert len(lead) == 4 * len(GRID)


def test_outputs_are_byte_identical_and_the_manifest_records_the_licence(tmp_path: Path) -> None:
    source = lead_zip(tmp_path / "lead.zip", lead_table())
    result = prepare_labels(lead_table(), METADATA, RAW, None, CLOCKS, corrections=())

    first = write(result, {"lead": source}, tmp_path / "a", inputs_verified=False)
    second = write(result, {"lead": source}, tmp_path / "b", inputs_verified=False)

    assert first == second
    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["licence_status"] == LICENCE_STATUS
    assert manifest["lead_commit"] == COMMIT
    assert manifest["inputs_verified_against_pinned_checksums"] is False
    assert "not** confirmed waste" in (tmp_path / "a" / "report.md").read_text(encoding="utf-8")


def test_the_pinned_file_points_at_the_pinned_commit() -> None:
    assert COMMIT in FILE.url
    assert FILE.size == 10_027_589


def test_cli_prepare_runs_on_bdg2_format_files(make_bdg2_raw: BDG2Builder, tmp_path: Path) -> None:
    # Eagle is pinned as standard time, so the default clocks apply (US/Eastern, -5 h).
    raw = make_bdg2_raw([("Eagle", "US/Eastern", Clock.STANDARD, 2, False)])
    wide = pd.read_csv(raw / "meters" / "raw" / "electricity.csv", nrows=48)
    lead = pd.DataFrame(
        {
            "building_id": 0,  # the fixture's first building, Eagle_office_B0
            "timestamp": pd.to_datetime(wide["timestamp"]),
            "meter_reading": wide["Eagle_office_B0"],
            "anomaly": [1] + [0] * 47,
        }
    )
    lead_zip(tmp_path / "lead" / FILE.local_path, lead)
    out = tmp_path / "out"

    code = main(
        [
            "prepare",
            "--lead",
            str(tmp_path / "lead"),
            "--bdg2",
            str(raw),
            "--output",
            str(out),
            "--skip-input-verification",
        ]
    )

    assert code == 0
    stats = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["stats"]
    assert (stats["label_rows"], stats["label_anomalies"]) == (48, 1)
    assert stats["lead_reading_agreement_pct"] == 100.0
    assert stats["period_utc"] == ["2016-01-01T05:00:00Z", "2016-01-03T04:00:00Z"]
    labels = pd.read_parquet(out / "labels.parquet")
    assert set(labels["meter_id"]) == {"Eagle_office_B0:electricity"}


def test_cli_reports_a_missing_download(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["verify", "--dest", str(tmp_path)]) == 1
    assert main(["prepare", "--lead", str(tmp_path), "--bdg2", str(tmp_path)]) == 1
    assert "lead fetch" in capsys.readouterr().err


def test_lead_data_only_goes_to_git_ignored_folders() -> None:
    gitignore = (Path(__file__).resolve().parents[3] / ".gitignore").read_text(encoding="utf-8")

    assert "data/raw/" in gitignore.splitlines()
    assert "data/processed/" in gitignore.splitlines()
    assert DEFAULT_DESTINATION.as_posix().startswith("../data/raw/")
    assert DEFAULT_OUTPUT.as_posix().startswith("../data/processed/")
