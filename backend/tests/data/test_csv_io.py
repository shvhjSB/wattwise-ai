import io
from pathlib import Path

import pandas as pd

from wattwise.data.contracts import READINGS, TIMESTAMP_DTYPE
from wattwise.data.csv_io import read_csv
from wattwise.data.validation import IssueCode, to_canonical

HEADER = "timestamp,meter_id,building_id,meter_type,unit,value"
ROWS = (
    "2016-01-01T00:00:00Z,b1:electricity,b1,electricity,kWh,10.5",
    "2016-01-01T02:00:00+01:00,b1:electricity,b1,electricity,kWh,",
    '2016-01-01T00:00:00Z,b2:electricity,"b2",electricity,kWh,3',
)


def csv_text(*lines: str) -> io.StringIO:
    return io.StringIO("\n".join(lines) + "\n")


def codes(*lines: str) -> set[IssueCode]:
    return {issue.code for issue in read_csv(csv_text(*lines), READINGS).report.errors}


def test_valid_file_yields_the_canonical_table() -> None:
    result = read_csv(csv_text(HEADER, *ROWS), READINGS)

    assert result.report.ok, result.report.issues
    assert result.frame is not None
    assert str(result.frame["timestamp"].dtype) == TIMESTAMP_DTYPE
    assert result.frame["timestamp"].iloc[1] == pd.Timestamp("2016-01-01T01:00:00Z")
    assert result.frame["value"].isna().sum() == 1, "an empty cell is a missing value"
    assert result.frame["building_id"].tolist() == ["b1", "b1", "b2"]


def test_csv_round_trip_matches_the_in_memory_canonical_table(readings: pd.DataFrame) -> None:
    exported = readings.copy()
    exported["timestamp"] = exported["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    buffer = io.StringIO(exported.to_csv(index=False))

    result = read_csv(buffer, READINGS)

    assert result.frame is not None
    pd.testing.assert_frame_equal(result.frame, to_canonical(readings, READINGS))


def test_reads_from_a_path(tmp_path: Path) -> None:
    path = tmp_path / "readings.csv"
    path.write_text("\n".join((HEADER, *ROWS)) + "\n", encoding="utf-8")

    assert read_csv(path, READINGS).report.ok


def test_a_callers_binary_stream_is_left_open() -> None:
    stream = io.BytesIO(("\n".join((HEADER, *ROWS)) + "\n").encode("utf-8"))

    assert read_csv(stream, READINGS).report.ok
    assert not stream.closed


def test_byte_order_mark_and_header_whitespace_are_tolerated() -> None:
    header = " timestamp , meter_id,building_id,meter_type,unit,value "
    data = ("﻿" + "\n".join((header, *ROWS)) + "\n").encode("utf-8")

    assert read_csv(io.BytesIO(data), READINGS).report.ok


def test_invalid_utf8_is_reported() -> None:
    data = ("\n".join((HEADER, *ROWS)) + "\n").replace("b2", "bâtiment").encode("latin-1")

    result = read_csv(io.BytesIO(data), READINGS)

    assert [i.code for i in result.report.errors] == [IssueCode.INVALID_ENCODING]
    assert result.frame is None


def test_empty_file_and_header_only_file_are_empty_tables() -> None:
    assert [i.code for i in read_csv(io.StringIO(""), READINGS).report.errors] == [
        IssueCode.EMPTY_TABLE
    ]
    assert codes(HEADER) == {IssueCode.EMPTY_TABLE}


def test_rows_with_extra_fields_are_malformed() -> None:
    result = read_csv(csv_text(HEADER, ROWS[0], ROWS[1] + ",surplus"), READINGS)

    issue = result.report.errors[0]
    assert issue.code is IssueCode.MALFORMED_CSV
    assert "line 3" in issue.message


def test_rows_with_missing_fields_are_malformed() -> None:
    result = read_csv(csv_text(HEADER, ROWS[0], "2016-01-01T01:00:00Z,b1:electricity"), READINGS)

    issue = next(i for i in result.report.errors if i.code is IssueCode.MALFORMED_CSV)
    assert issue.rows == (2,)


def test_unnamed_and_duplicate_header_columns_are_rejected() -> None:
    assert codes(HEADER + ",", ROWS[0] + ",") == {IssueCode.MALFORMED_CSV}
    assert IssueCode.DUPLICATE_COLUMN in codes(HEADER + ",value", ROWS[0] + ",1")


def test_csv_timestamps_without_offset_are_rejected() -> None:
    naive = ROWS[0].replace("2016-01-01T00:00:00Z", "2016-01-01 00:00:00")

    assert codes(HEADER, naive) == {IssueCode.NAIVE_TIMESTAMP}


def test_nan_text_is_not_accepted_as_missing() -> None:
    assert codes(HEADER, ROWS[0].replace("10.5", "NaN")) == {IssueCode.NON_NUMERIC_VALUE}


def test_missing_required_column_in_header() -> None:
    header = HEADER.replace(",unit", "")
    row = ROWS[0].replace(",kWh", "")

    assert codes(header, row) == {IssueCode.MISSING_COLUMN}
