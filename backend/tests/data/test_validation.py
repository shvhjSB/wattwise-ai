import pandas as pd
import pytest

from wattwise.data.contracts import BUILDINGS, READINGS, TIMESTAMP_DTYPE, WEATHER
from wattwise.data.validation import (
    ContractViolationError,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
    to_canonical,
    validate,
)


def only(report: ValidationReport, code: IssueCode) -> ValidationIssue:
    matching = [issue for issue in report.issues if issue.code is code]
    assert len(matching) == 1, report.issues
    return matching[0]


def error_codes(report: ValidationReport) -> set[IssueCode]:
    return {issue.code for issue in report.errors}


def as_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame as an upload would deliver it: every cell text, missing as ''."""
    text = frame.copy()
    text["timestamp"] = text["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return text.astype(object).where(text.notna(), "").astype(str)


# ---------------------------------------------------------------------------
# Valid input
# ---------------------------------------------------------------------------


def test_valid_typed_readings_pass_without_issues(readings: pd.DataFrame) -> None:
    report = validate(readings, READINGS)

    assert report.ok
    assert report.issues == ()
    assert report.row_count == 4
    assert report.contract_version == READINGS.version


def test_canonical_readings_have_contract_columns_dtypes_and_key_order(
    readings: pd.DataFrame,
) -> None:
    canonical = to_canonical(readings, READINGS)

    assert list(canonical.columns) == list(READINGS.column_names)
    assert str(canonical["timestamp"].dtype) == TIMESTAMP_DTYPE
    assert str(canonical["value"].dtype) == "float64"
    assert str(canonical["meter_id"].dtype) == "str"
    keys = list(zip(canonical["meter_id"], canonical["timestamp"].dt.hour, strict=True))
    assert keys == [
        ("b1:electricity", 0),
        ("b1:electricity", 1),
        ("b2:electricity", 0),
        ("b2:electricity", 1),
    ]
    assert canonical["value"].isna().sum() == 1, "missing readings stay missing"


def test_validation_does_not_modify_the_input(readings: pd.DataFrame) -> None:
    before = readings.copy()

    to_canonical(readings, READINGS)

    pd.testing.assert_frame_equal(readings, before)


def test_timezone_aware_timestamps_are_converted_to_utc(readings: pd.DataFrame) -> None:
    local = readings.copy()
    local["timestamp"] = local["timestamp"].dt.tz_convert("America/New_York")

    canonical = to_canonical(local, READINGS)

    expected = to_canonical(readings, READINGS)["timestamp"]
    pd.testing.assert_series_equal(canonical["timestamp"], expected)


def test_text_frame_as_from_an_upload_passes(readings: pd.DataFrame) -> None:
    text = as_strings(readings)

    canonical = to_canonical(text, READINGS)

    pd.testing.assert_frame_equal(canonical, to_canonical(readings, READINGS))


def test_offsets_other_than_utc_are_accepted_in_text(readings: pd.DataFrame) -> None:
    text = as_strings(readings)
    text["timestamp"] = [
        "2016-01-01T02:00:00+01:00",
        "2016-01-01T01:00:00+0100",
        "2015-12-31T19:00:00-05:00",
        "2016-01-01 01:00:00Z",
    ]

    canonical = to_canonical(text, READINGS)

    pd.testing.assert_series_equal(
        canonical["timestamp"], to_canonical(readings, READINGS)["timestamp"]
    )


def test_categorical_columns_are_accepted(readings: pd.DataFrame) -> None:
    for name in ("meter_type", "unit", "building_id"):
        readings[name] = readings[name].astype("category")

    assert validate(readings, READINGS).ok


def test_unexpected_columns_are_a_warning_and_dropped(readings: pd.DataFrame) -> None:
    readings["notes"] = "checked"

    report = validate(readings, READINGS)

    assert report.ok
    assert only(report, IssueCode.UNEXPECTED_COLUMN).severity is Severity.WARNING
    assert "notes" not in to_canonical(readings, READINGS).columns


# ---------------------------------------------------------------------------
# Acceptance cases (roadmap T005)
# ---------------------------------------------------------------------------


def test_missing_columns_are_reported_by_name(readings: pd.DataFrame) -> None:
    report = validate(readings.drop(columns=["unit", "value"]), READINGS)

    assert not report.ok
    missing = [i for i in report.errors if i.code is IssueCode.MISSING_COLUMN]
    assert {i.column for i in missing} == {"unit", "value"}
    assert "Required column 'unit' is missing" in missing[0].message
    assert "timestamp, meter_id, building_id, meter_type, unit, value" in missing[0].message


def test_naive_datetime_column_is_rejected(readings: pd.DataFrame) -> None:
    readings["timestamp"] = readings["timestamp"].dt.tz_localize(None)

    report = validate(readings, READINGS)

    issue = only(report, IssueCode.NAIVE_TIMESTAMP)
    assert issue.severity is Severity.ERROR
    assert issue.count == 4
    assert "no time zone" in issue.message


def test_timestamp_text_without_offset_is_rejected_not_assumed_utc(
    readings: pd.DataFrame,
) -> None:
    text = as_strings(readings)
    text.loc[[1, 3], "timestamp"] = ["2016-01-01T00:00:00", "2016-01-01 01:00"]

    report = validate(text, READINGS)

    issue = only(report, IssueCode.NAIVE_TIMESTAMP)
    assert issue.count == 2
    assert issue.rows == (2, 4)
    assert "'2016-01-01T00:00:00'" in issue.message
    assert "2016-01-01T00:00:00Z" in issue.message, "the fix is shown"


def test_unknown_units_are_rejected_with_a_suggestion(readings: pd.DataFrame) -> None:
    readings.loc[0, "unit"] = "kwh"
    readings.loc[2, "unit"] = "Wh"

    report = validate(readings, READINGS)

    issue = only(report, IssueCode.UNKNOWN_UNIT)
    assert issue.count == 2
    assert issue.rows == (1, 3)
    assert set(issue.examples) == {"'kwh'", "'Wh'"}
    assert "Allowed: kWh, m3" in issue.message
    assert "'kwh' -> 'kWh'" in issue.message


def test_non_numeric_values_are_rejected(readings: pd.DataFrame) -> None:
    text = as_strings(readings)
    text["value"] = ["1.5", "abc", "1,234", "NaN"]

    report = validate(text, READINGS)

    issue = only(report, IssueCode.NON_NUMERIC_VALUE)
    assert issue.count == 3
    assert issue.rows == (2, 3, 4)
    assert "empty for a missing value" in issue.message


def test_duplicate_keys_are_rejected(readings: pd.DataFrame) -> None:
    duplicated = pd.concat([readings, readings.iloc[[1]]], ignore_index=True)

    report = validate(duplicated, READINGS)

    issue = only(report, IssueCode.DUPLICATE_KEY)
    assert issue.count == 2
    assert issue.rows == (2, 5)
    assert "(meter_id, timestamp)" in issue.message
    assert "b2:electricity @ 2016-01-01 00:00:00+00:00" in issue.message


# ---------------------------------------------------------------------------
# Other structural rules
# ---------------------------------------------------------------------------


def test_invalid_identifiers_are_rejected(readings: pd.DataFrame) -> None:
    readings.loc[0, "building_id"] = "building two"

    issue = only(validate(readings, READINGS), IssueCode.INVALID_IDENTIFIER)

    assert issue.column == "building_id"
    assert "no spaces" in issue.message


def test_unknown_meter_types_are_rejected(readings: pd.DataFrame) -> None:
    readings.loc[0, "meter_type"] = "Electricity "

    issue = only(validate(readings, READINGS), IssueCode.UNKNOWN_METER_TYPE)

    assert "'Electricity ' -> 'electricity'" in issue.message


def test_non_canonical_unit_for_the_meter_type_is_rejected(readings: pd.DataFrame) -> None:
    readings.loc[[0, 1], "unit"] = "m3"

    report = validate(readings, READINGS)

    issue = only(report, IssueCode.NON_CANONICAL_UNIT)
    assert issue.count == 2
    assert "electricity in m3 (canonical: kWh)" in issue.message
    assert IssueCode.UNKNOWN_UNIT not in error_codes(report)


def test_a_meter_must_belong_to_one_building(readings: pd.DataFrame) -> None:
    readings.loc[0, "building_id"] = "b3"

    issue = only(validate(readings, READINGS), IssueCode.INCONSISTENT_METER)

    assert issue.column == "building_id"
    assert "b2:electricity (b2, b3)" in issue.message


def test_unsupported_meter_types_pass_with_a_warning(readings: pd.DataFrame) -> None:
    readings["meter_id"] = readings["meter_id"].str.replace("electricity", "gas")
    readings["meter_type"] = "gas"

    report = validate(readings, READINGS)

    assert report.ok
    issue = only(report, IssueCode.UNSUPPORTED_METER_TYPE)
    assert issue.severity is Severity.WARNING
    assert issue.count == 4


def test_infinite_values_are_rejected(readings: pd.DataFrame) -> None:
    readings.loc[1, "value"] = float("inf")

    issue = only(validate(readings, READINGS), IssueCode.NON_FINITE_VALUE)

    assert issue.rows == (2,)


def test_required_values_cannot_be_missing(readings: pd.DataFrame) -> None:
    readings["meter_id"] = readings["meter_id"].astype(object)
    readings.loc[0, "meter_id"] = None
    readings.loc[1, "meter_id"] = ""

    issue = only(validate(readings, READINGS), IssueCode.MISSING_VALUE)

    assert issue.column == "meter_id"
    assert issue.rows == (1, 2)


def test_empty_tables_are_rejected(readings: pd.DataFrame) -> None:
    report = validate(readings.iloc[0:0], READINGS)

    assert error_codes(report) == {IssueCode.EMPTY_TABLE}


def test_non_text_identifiers_are_a_dtype_error(readings: pd.DataFrame) -> None:
    readings["building_id"] = [1, 1, 2, 2]

    issue = only(validate(readings, READINGS), IssueCode.INVALID_DTYPE)

    assert "int64" in issue.message
    assert ".astype(str)" in issue.message


def test_unparseable_timestamps_are_rejected(readings: pd.DataFrame) -> None:
    text = as_strings(readings)
    text.loc[[0, 2], "timestamp"] = ["2016-13-01T00:00:00Z", "yesterday"]

    issue = only(validate(text, READINGS), IssueCode.INVALID_TIMESTAMP)

    assert issue.rows == (1, 3)


def test_long_issue_lists_are_truncated(readings: pd.DataFrame) -> None:
    many = pd.concat([readings] * 3, ignore_index=True)
    many["unit"] = "kwh"

    issue = only(validate(many, READINGS), IssueCode.UNKNOWN_UNIT)

    assert issue.count == 12
    assert issue.rows == (1, 2, 3, 4, 5)
    assert "rows 1, 2, 3, 4, 5 and 7 more" in issue.message


def test_to_canonical_raises_with_the_report(readings: pd.DataFrame) -> None:
    readings["unit"] = "kwh"

    with pytest.raises(ContractViolationError) as raised:
        to_canonical(readings, READINGS)

    assert raised.value.report.errors[0].code is IssueCode.UNKNOWN_UNIT
    assert "readings: 1 contract error(s)" in str(raised.value)


# ---------------------------------------------------------------------------
# Buildings and weather
# ---------------------------------------------------------------------------


def test_valid_buildings_gain_absent_optional_columns(buildings: pd.DataFrame) -> None:
    canonical = to_canonical(buildings, BUILDINGS)

    assert list(canonical.columns) == list(BUILDINGS.column_names)
    assert canonical["floor_area_m2"].isna().all()
    assert str(canonical["floor_area_m2"].dtype) == "float64"


def test_unknown_time_zones_are_rejected(buildings: pd.DataFrame) -> None:
    buildings.loc[1, "timezone"] = "EST5EDT/Somewhere"

    issue = only(validate(buildings, BUILDINGS), IssueCode.INVALID_TIMEZONE)

    assert issue.rows == (2,)


@pytest.mark.parametrize(
    ("column", "value"),
    [("latitude", 91.0), ("longitude", -180.5), ("floor_area_m2", 0.0)],
)
def test_physically_impossible_building_values_are_rejected(
    buildings: pd.DataFrame, column: str, value: float
) -> None:
    buildings[column] = [value, None]

    issue = only(validate(buildings, BUILDINGS), IssueCode.OUT_OF_RANGE)

    assert issue.column == column
    assert issue.rows == (1,)


def test_duplicate_buildings_are_rejected(buildings: pd.DataFrame) -> None:
    buildings.loc[1, "building_id"] = "b1"

    assert IssueCode.DUPLICATE_KEY in error_codes(validate(buildings, BUILDINGS))


def test_valid_weather_allows_missing_temperatures(weather: pd.DataFrame) -> None:
    assert validate(weather, WEATHER).ok


def test_negative_wind_speed_is_rejected(weather: pd.DataFrame) -> None:
    weather["wind_speed_m_s"] = [3.0, -1.0]

    issue = only(validate(weather, WEATHER), IssueCode.OUT_OF_RANGE)

    assert issue.column == "wind_speed_m_s"
    assert "(>= 0)" in issue.message


def test_weather_requires_air_temperature_column(weather: pd.DataFrame) -> None:
    report = validate(weather.drop(columns=["air_temperature_c"]), WEATHER)

    assert only(report, IssueCode.MISSING_COLUMN).column == "air_temperature_c"
