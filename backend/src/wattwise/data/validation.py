"""Validate tables against the canonical contracts and convert them to canonical form.

One code path serves both inputs: frames of raw strings (as read from CSV uploads) and typed
in-memory frames (as produced by dataset adapters). Each column is coerced to its canonical dtype
while recording what was missing or invalid, so every problem is reported exactly once, with a
stable code, the affected rows and a hint on how to fix it.

Rows are reported as 1-based positions in the table (for CSV files: the first data row after the
header is row 1).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from typing import Any
from zoneinfo import available_timezones

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict

from wattwise.data.contracts import (
    ANALYSIS_SUPPORTED,
    CANONICAL_UNIT,
    IDENTIFIER_PATTERN,
    NUMBER_DTYPE,
    READINGS,
    TEXT_DTYPE,
    TIMESTAMP_DTYPE,
    Column,
    ColumnKind,
    MeterType,
    TableContract,
)

BoolArray = npt.NDArray[np.bool_]

#: How many example rows and values an issue lists.
MAX_EXAMPLES = 5

_DATE_TIME = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?"
_TIMESTAMP_WITH_OFFSET = _DATE_TIME + r"(?:[Zz]|[+-]\d{2}:?\d{2})"
_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class IssueCode(StrEnum):
    """Stable, machine-readable issue codes. Documented in docs/DATA_CONTRACT.md."""

    EMPTY_TABLE = "empty_table"
    MISSING_COLUMN = "missing_column"
    UNEXPECTED_COLUMN = "unexpected_column"
    DUPLICATE_COLUMN = "duplicate_column"
    MALFORMED_CSV = "malformed_csv"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_DTYPE = "invalid_dtype"
    MISSING_VALUE = "missing_value"
    INVALID_IDENTIFIER = "invalid_identifier"
    INVALID_TIMESTAMP = "invalid_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"
    UNKNOWN_METER_TYPE = "unknown_meter_type"
    UNKNOWN_UNIT = "unknown_unit"
    NON_CANONICAL_UNIT = "non_canonical_unit"
    NON_NUMERIC_VALUE = "non_numeric_value"
    NON_FINITE_VALUE = "non_finite_value"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TIMEZONE = "invalid_timezone"
    DUPLICATE_KEY = "duplicate_key"
    INCONSISTENT_METER = "inconsistent_meter"
    UNSUPPORTED_METER_TYPE = "unsupported_meter_type"


#: Issue code for values outside a category column's vocabulary.
UNKNOWN_CATEGORY_CODES: dict[str, IssueCode] = {
    "meter_type": IssueCode.UNKNOWN_METER_TYPE,
    "unit": IssueCode.UNKNOWN_UNIT,
}


class ValidationIssue(BaseModel):
    """One problem found in a table. `count` is the number of affected rows (0 if table-level)."""

    model_config = ConfigDict(frozen=True)

    code: IssueCode
    severity: Severity
    column: str | None
    message: str
    count: int
    rows: tuple[int, ...] = ()
    examples: tuple[str, ...] = ()


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    contract_version: str
    row_count: int
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """True when the table satisfies the contract. Warnings do not make a table invalid."""
        return not self.errors


class ContractViolationError(ValueError):
    """Raised when a table cannot be converted because it violates its contract."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        details = "; ".join(issue.message for issue in report.errors[:3])
        more = len(report.errors) - 3
        suffix = f" (and {more} more)" if more > 0 else ""
        super().__init__(
            f"{report.table}: {len(report.errors)} contract error(s): {details}{suffix}"
        )


def validate(frame: pd.DataFrame, contract: TableContract) -> ValidationReport:
    """Check `frame` against `contract` without modifying it."""
    report, _ = check_table(frame, contract)
    return report


def to_canonical(frame: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
    """Return the canonical form of `frame`, or raise `ContractViolationError`.

    The result has exactly the contract's columns in contract order (absent optional columns are
    filled with missing values), canonical dtypes, timestamps in UTC, and rows sorted by the
    primary key.
    """
    report, canonical = check_table(frame, contract)
    if not report.ok:
        raise ContractViolationError(report)
    return canonical


def check_table(
    frame: pd.DataFrame,
    contract: TableContract,
    prior_issues: tuple[ValidationIssue, ...] = (),
) -> tuple[ValidationReport, pd.DataFrame]:
    """Validate and coerce in one pass.

    Returns the report and the canonical frame. The frame is only trustworthy when the report is
    ok; invalid cells hold missing values. `prior_issues` lets callers such as the CSV reader
    prepend problems found before the table could be built.
    """
    issues: list[ValidationIssue] = list(prior_issues)
    row_count = len(frame)
    present = [str(name) for name in frame.columns]

    duplicated = sorted({name for name in present if present.count(name) > 1})
    for name in duplicated:
        issues.append(
            _table_issue(
                IssueCode.DUPLICATE_COLUMN,
                name,
                f"Column {name!r} appears more than once. Each column may appear only once.",
            )
        )
    if row_count == 0:
        issues.append(
            _table_issue(
                IssueCode.EMPTY_TABLE, None, f"The {contract.name} table has no data rows."
            )
        )
    for column in contract.columns:
        if column.required and column.name not in present:
            issues.append(
                _table_issue(
                    IssueCode.MISSING_COLUMN,
                    column.name,
                    f"Required column {column.name!r} is missing. The {contract.name} contract "
                    f"expects: {', '.join(contract.column_names)} (see docs/DATA_CONTRACT.md).",
                )
            )
    for name in present:
        if name not in contract.column_names and name not in duplicated:
            issues.append(
                _table_issue(
                    IssueCode.UNEXPECTED_COLUMN,
                    name,
                    f"Column {name!r} is not part of the {contract.name} contract and is ignored.",
                    severity=Severity.WARNING,
                )
            )

    results: dict[str, _ColumnResult] = {}
    if not duplicated:
        for column in contract.columns:
            if column.name in present:
                result = _coerce(frame[column.name].reset_index(drop=True), column)
                results[column.name] = result
                issues.extend(result.issues)

    canonical = _assemble(contract, results, row_count)
    for table_check in _TABLE_CHECKS.get(contract.name, ()):
        issues.extend(table_check(canonical, results))
    issues.extend(_check_primary_key(contract, canonical, results))

    if not any(i.severity is Severity.ERROR for i in issues):
        canonical = canonical.sort_values(list(contract.primary_key), kind="stable")
        canonical = canonical.reset_index(drop=True)

    report = ValidationReport(
        table=contract.name,
        contract_version=contract.version,
        row_count=row_count,
        issues=tuple(issues),
    )
    return report, canonical


# ---------------------------------------------------------------------------
# Column coercion
# ---------------------------------------------------------------------------


@dataclass
class _ColumnResult:
    """A column coerced to its canonical dtype. Missing and invalid cells hold NA."""

    values: pd.Series[Any]
    missing: BoolArray
    invalid: BoolArray
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> BoolArray:
        return ~self.missing & ~self.invalid


def _coerce(series: pd.Series[Any], column: Column) -> _ColumnResult:
    if column.kind is ColumnKind.TIMESTAMP:
        result = _coerce_timestamp(series, column)
    elif column.kind is ColumnKind.NUMBER:
        result = _coerce_number(series, column)
    else:
        result = _coerce_text_like(series, column)

    if not column.nullable and result.missing.any():
        what = _phrase(result.missing, "is missing", "are missing")
        result.issues.insert(
            0,
            _row_issue(
                IssueCode.MISSING_VALUE,
                column.name,
                result.missing,
                f"Column {column.name!r}: {what} ({_where(result.missing)}). This column "
                "requires a value in every row.",
            ),
        )
    return result


def _coerce_text_like(series: pd.Series[Any], column: Column) -> _ColumnResult:
    text = _as_text(series)
    if text is None:
        return _wrong_dtype(series, column, "text")
    missing = (text.isna() | text.eq("")).to_numpy(dtype=bool)
    present = text.where(~missing)
    invalid = np.zeros(len(text), dtype=bool)
    issues: list[ValidationIssue] = []

    if column.kind is ColumnKind.IDENTIFIER:
        # Identifiers repeat on every row of a meter: test each distinct value once.
        codes, uniques = pd.factorize(present)
        valid_unique = np.fromiter(
            (_IDENTIFIER.fullmatch(str(u)) is not None for u in uniques),
            dtype=bool,
            count=len(uniques),
        )
        invalid = _spread(~valid_unique, codes)
        if invalid.any():
            what = _phrase(invalid, "is not a valid identifier", "are not valid identifiers")
            issues.append(
                _row_issue(
                    IssueCode.INVALID_IDENTIFIER,
                    column.name,
                    invalid,
                    f"Column {column.name!r}: {what} "
                    f"({_where(invalid)}): {_shown(text, invalid)}. Identifiers are 1-128 "
                    "characters: letters, digits, '_', '.', ':' or '-', starting with a letter "
                    "or digit, with no spaces.",
                    examples=_examples(text, invalid),
                )
            )
    elif column.kind is ColumnKind.CATEGORY:
        invalid = ~missing & ~present.isin(column.choices).to_numpy(dtype=bool)
        if invalid.any():
            code = UNKNOWN_CATEGORY_CODES[column.name]
            what = _phrase(invalid, "is not", "are not")
            issues.append(
                _row_issue(
                    code,
                    column.name,
                    invalid,
                    f"Column {column.name!r}: {what} in the allowed vocabulary "
                    f"({_where(invalid)}): {_shown(text, invalid)}. Allowed: "
                    f"{', '.join(column.choices)}.{_suggestion(text, invalid, column.choices)}",
                    examples=_examples(text, invalid),
                )
            )
    elif column.kind is ColumnKind.TIMEZONE:
        known = _known_timezones()
        invalid = ~missing & ~present.isin(known).to_numpy(dtype=bool)
        if invalid.any():
            what = _phrase(invalid, "is not an IANA time zone name", "are not IANA time zone names")
            issues.append(
                _row_issue(
                    IssueCode.INVALID_TIMEZONE,
                    column.name,
                    invalid,
                    f"Column {column.name!r}: {what} "
                    f"({_where(invalid)}): {_shown(text, invalid)}. Use names such as "
                    "'Europe/London' or 'America/New_York'.",
                    examples=_examples(text, invalid),
                )
            )

    values = text.where(~missing & ~invalid).astype(TEXT_DTYPE)
    return _ColumnResult(values, missing, invalid, issues)


def _coerce_number(series: pd.Series[Any], column: Column) -> _ColumnResult:
    issues: list[ValidationIssue] = []
    if pd.api.types.is_bool_dtype(series):
        return _wrong_dtype(series, column, "numbers")
    if pd.api.types.is_numeric_dtype(series):
        values = series.astype(NUMBER_DTYPE)
        missing = values.isna().to_numpy(dtype=bool)
        invalid = np.zeros(len(values), dtype=bool)
    else:
        text = _as_text(series)
        if text is None:
            return _wrong_dtype(series, column, "numbers")
        missing = (text.isna() | text.eq("")).to_numpy(dtype=bool)
        values = pd.to_numeric(text.where(~missing), errors="coerce").astype(NUMBER_DTYPE)
        invalid = ~missing & values.isna().to_numpy(dtype=bool)
        if invalid.any():
            what = _phrase(invalid, "is not a number", "are not numbers")
            issues.append(
                _row_issue(
                    IssueCode.NON_NUMERIC_VALUE,
                    column.name,
                    invalid,
                    f"Column {column.name!r}: {what} "
                    f"({_where(invalid)}): {_shown(text, invalid)}. Use '.' as the decimal "
                    "separator, no thousands separators, and leave the cell empty for a "
                    "missing value.",
                    examples=_examples(text, invalid),
                )
            )

    infinite = ~missing & ~invalid & np.isinf(values.to_numpy(dtype=float, na_value=np.nan))
    if infinite.any():
        what = _phrase(infinite, "is infinite", "are infinite")
        issues.append(
            _row_issue(
                IssueCode.NON_FINITE_VALUE,
                column.name,
                infinite,
                f"Column {column.name!r}: {what} ({_where(infinite)}). "
                "Infinite values are not measurements; leave the cell empty if unknown.",
                examples=_examples(values, infinite),
            )
        )
        invalid = invalid | infinite

    out_of_range = ~missing & ~invalid & _outside_bounds(values, column)
    if out_of_range.any():
        what = _phrase(out_of_range, "is outside", "are outside")
        issues.append(
            _row_issue(
                IssueCode.OUT_OF_RANGE,
                column.name,
                out_of_range,
                f"Column {column.name!r}: {what} the possible range "
                f"{_bounds_text(column)} ({_where(out_of_range)}): "
                f"{_shown(values, out_of_range)}.",
                examples=_examples(values, out_of_range),
            )
        )
        invalid = invalid | out_of_range

    return _ColumnResult(values.where(~invalid), missing, invalid, issues)


def _coerce_timestamp(series: pd.Series[Any], column: Column) -> _ColumnResult:
    issues: list[ValidationIssue] = []
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        values = series.dt.tz_convert("UTC").astype(TIMESTAMP_DTYPE)
        missing = values.isna().to_numpy(dtype=bool)
        return _ColumnResult(values, missing, np.zeros(len(values), dtype=bool), issues)

    if pd.api.types.is_datetime64_dtype(series):
        missing = series.isna().to_numpy(dtype=bool)
        naive = ~missing
        if naive.any():
            issues.append(_naive_issue(column, naive, None))
        return _ColumnResult(_missing_series(column, len(series)), missing, naive, issues)

    text = _as_text(series)
    if text is None:
        return _wrong_dtype(series, column, "timestamps")
    missing = (text.isna() | text.eq("")).to_numpy(dtype=bool)
    # Timestamps repeat once per meter: match and parse each distinct string once.
    codes, uniques = pd.factorize(text.where(~missing))
    distinct = pd.Series(uniques, dtype=TEXT_DTYPE)
    distinct_offset = distinct.str.fullmatch(_TIMESTAMP_WITH_OFFSET).to_numpy(
        dtype=bool, na_value=False
    )
    distinct_naive = distinct.str.fullmatch(_DATE_TIME).to_numpy(dtype=bool, na_value=False)
    distinct_parsed = pd.to_datetime(
        distinct.where(distinct_offset), format="ISO8601", utc=True, errors="coerce"
    ).astype(TIMESTAMP_DTYPE)
    parsed = pd.Series(distinct_parsed.array.take(codes, allow_fill=True), dtype=TIMESTAMP_DTYPE)

    naive = _spread(distinct_naive, codes)
    invalid_format = ~missing & ~naive & parsed.isna().to_numpy(dtype=bool)
    if naive.any():
        issues.append(_naive_issue(column, naive, text))
    if invalid_format.any():
        what = _phrase(
            invalid_format, "is not a valid ISO 8601 timestamp", "are not valid ISO 8601 timestamps"
        )
        issues.append(
            _row_issue(
                IssueCode.INVALID_TIMESTAMP,
                column.name,
                invalid_format,
                f"Column {column.name!r}: {what} "
                f"({_where(invalid_format)}): {_shown(text, invalid_format)}. "
                "Use the form 2016-01-01T00:00:00Z or 2016-01-01T01:00:00+01:00.",
                examples=_examples(text, invalid_format),
            )
        )
    invalid = naive | invalid_format
    return _ColumnResult(parsed.where(~invalid), missing, invalid, issues)


def _naive_issue(column: Column, mask: BoolArray, text: pd.Series[Any] | None) -> ValidationIssue:
    shown = f": {_shown(text, mask)}" if text is not None else ""
    what = _phrase(mask, "has no time zone", "have no time zone")
    return _row_issue(
        IssueCode.NAIVE_TIMESTAMP,
        column.name,
        mask,
        f"Column {column.name!r}: {what} ({_where(mask)}){shown}. "
        "Timestamps must state their offset, e.g. 2016-01-01T00:00:00Z or "
        "2016-01-01T01:00:00+01:00; they are stored in UTC.",
        examples=_examples(text, mask) if text is not None else (),
    )


def _as_text(series: pd.Series[Any]) -> pd.Series[Any] | None:
    """Return `series` as canonical text, or None if it holds non-text values."""
    if isinstance(series.dtype, pd.CategoricalDtype):
        series = series.astype("object")
    if pd.api.types.is_object_dtype(series.dtype):
        if all(isinstance(value, str) for value in series.dropna()):
            return series.astype(TEXT_DTYPE)
        return None
    if pd.api.types.is_string_dtype(series.dtype):
        return series.astype(TEXT_DTYPE)
    return None


def _missing_series(column: Column, rows: int) -> pd.Series[Any]:
    """An all-missing series in the column's canonical dtype."""
    if column.kind is ColumnKind.TIMESTAMP:
        return pd.Series(pd.NaT, index=pd.RangeIndex(rows), dtype=TIMESTAMP_DTYPE)
    if column.kind is ColumnKind.NUMBER:
        return pd.Series(np.full(rows, np.nan), dtype=NUMBER_DTYPE)
    return pd.Series([None] * rows, dtype=TEXT_DTYPE)


def _wrong_dtype(series: pd.Series[Any], column: Column, noun: str) -> _ColumnResult:
    issue = _table_issue(
        IssueCode.INVALID_DTYPE,
        column.name,
        f"Column {column.name!r} must contain {noun}, but has dtype {series.dtype}. "
        + _dtype_hint(column),
    )
    rows = len(series)
    return _ColumnResult(
        _missing_series(column, rows),
        np.zeros(rows, dtype=bool),
        np.ones(rows, dtype=bool),
        [issue],
    )


def _dtype_hint(column: Column) -> str:
    if column.kind is ColumnKind.TIMESTAMP:
        return "Provide timezone-aware datetimes or ISO 8601 strings with an offset."
    if column.kind is ColumnKind.NUMBER:
        return "Provide integers or floats (or numeric strings)."
    return "Provide strings, e.g. with .astype(str)."


def _outside_bounds(values: pd.Series[Any], column: Column) -> BoolArray:
    data = values.to_numpy(dtype=float, na_value=np.nan)
    outside = np.zeros(len(data), dtype=bool)
    with np.errstate(invalid="ignore"):
        if column.minimum is not None:
            below = data <= column.minimum if column.exclusive_minimum else data < column.minimum
            outside |= below
        if column.maximum is not None:
            outside |= data > column.maximum
    return outside


def _bounds_text(column: Column) -> str:
    low = "" if column.minimum is None else f"{column.minimum:g}"
    high = "" if column.maximum is None else f"{column.maximum:g}"
    if column.maximum is None:
        return f"(> {low})" if column.exclusive_minimum else f"(>= {low})"
    if column.minimum is None:
        return f"(<= {high})"
    return f"[{low}, {high}]"


def _spread(per_distinct: BoolArray, codes: npt.NDArray[np.intp]) -> BoolArray:
    """Map a per-distinct-value flag back to rows; rows with code -1 (missing) get False."""
    out = np.zeros(len(codes), dtype=bool)
    present = codes >= 0
    out[present] = per_distinct[codes[present]]
    return out


@cache
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


# ---------------------------------------------------------------------------
# Table-level checks
# ---------------------------------------------------------------------------


def _assemble(
    contract: TableContract, results: dict[str, _ColumnResult], row_count: int
) -> pd.DataFrame:
    data: dict[str, pd.Series[Any]] = {}
    for column in contract.columns:
        if column.name in results:
            data[column.name] = results[column.name].values
        else:
            data[column.name] = _missing_series(column, row_count)
    return pd.DataFrame(data, columns=list(contract.column_names))


def _valid_rows(results: dict[str, _ColumnResult], names: tuple[str, ...]) -> BoolArray | None:
    if any(name not in results for name in names):
        return None
    valid = results[names[0]].valid
    for name in names[1:]:
        valid = valid & results[name].valid
    return valid


def _check_primary_key(
    contract: TableContract, canonical: pd.DataFrame, results: dict[str, _ColumnResult]
) -> list[ValidationIssue]:
    valid = _valid_rows(results, contract.primary_key)
    if valid is None or not valid.any():
        return []
    key = list(contract.primary_key)
    duplicated = valid & canonical.duplicated(subset=key, keep=False).to_numpy(dtype=bool)
    if not duplicated.any():
        return []
    key_text = ", ".join(key)
    labels = canonical.loc[duplicated, key].astype(str).agg(" @ ".join, axis=1)
    examples = tuple(dict.fromkeys(labels.tolist()))[:MAX_EXAMPLES]
    return [
        _row_issue(
            IssueCode.DUPLICATE_KEY,
            None,
            duplicated,
            f"{_count(int(duplicated.sum()), 'row')} share their ({key_text}) with another row "
            f"({_where(duplicated)}), e.g. {', '.join(examples)}. The key must be unique.",
            examples=examples,
        )
    ]


def _check_canonical_units(
    canonical: pd.DataFrame, results: dict[str, _ColumnResult]
) -> list[ValidationIssue]:
    valid = _valid_rows(results, ("meter_type", "unit"))
    if valid is None:
        return []
    expected = canonical["meter_type"].map({str(k): str(v) for k, v in CANONICAL_UNIT.items()})
    mismatch = valid & canonical["unit"].ne(expected).to_numpy(dtype=bool)
    if not mismatch.any():
        return []
    pairs = (
        canonical.loc[mismatch, ["meter_type", "unit"]]
        .drop_duplicates()
        .head(MAX_EXAMPLES)
        .itertuples(index=False)
    )
    examples = tuple(
        f"{meter_type} in {unit} (canonical: {CANONICAL_UNIT[MeterType(meter_type)]})"
        for meter_type, unit in pairs
    )
    return [
        _row_issue(
            IssueCode.NON_CANONICAL_UNIT,
            "unit",
            mismatch,
            f"{_count(int(mismatch.sum()), 'row')} use a unit that is not canonical for the "
            f"meter type ({_where(mismatch)}): {'; '.join(examples)}. Convert values to the "
            "canonical unit before loading.",
            examples=examples,
        )
    ]


def _check_meter_consistency(
    canonical: pd.DataFrame, results: dict[str, _ColumnResult]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for attribute in ("building_id", "meter_type", "unit"):
        valid = _valid_rows(results, ("meter_id", attribute))
        if valid is None or not valid.any():
            continue
        subset = canonical.loc[valid, ["meter_id", attribute]]
        distinct = subset.groupby("meter_id", sort=True)[attribute].nunique()
        bad_meters = distinct[distinct > 1].index
        if bad_meters.empty:
            continue
        affected = valid & canonical["meter_id"].isin(bad_meters).to_numpy(dtype=bool)
        examples = []
        for meter in bad_meters[:MAX_EXAMPLES]:
            seen = sorted(
                str(v) for v in subset.loc[subset["meter_id"] == meter, attribute].unique()
            )
            examples.append(f"{meter} ({', '.join(seen)})")
        issues.append(
            _row_issue(
                IssueCode.INCONSISTENT_METER,
                attribute,
                affected,
                f"{_count(len(bad_meters), 'meter')} {_have(len(bad_meters))} more than one "
                f"{attribute} ({_where(affected)}): {'; '.join(examples)}. A meter belongs to "
                "one building and has one meter_type and unit.",
                examples=tuple(examples),
            )
        )
    return issues


def _check_analysis_support(
    canonical: pd.DataFrame, results: dict[str, _ColumnResult]
) -> list[ValidationIssue]:
    valid = _valid_rows(results, ("meter_type",))
    if valid is None:
        return []
    supported = [str(m) for m in ANALYSIS_SUPPORTED]
    unsupported = valid & ~canonical["meter_type"].isin(supported).to_numpy(dtype=bool)
    if not unsupported.any():
        return []
    kinds = sorted(canonical.loc[unsupported, "meter_type"].unique())
    return [
        _row_issue(
            IssueCode.UNSUPPORTED_METER_TYPE,
            "meter_type",
            unsupported,
            f"{_count(int(unsupported.sum()), 'row')} have meter types that WattWise does not "
            f"analyse yet ({', '.join(kinds)}). They satisfy the contract but are excluded from "
            f"forecasting and anomaly detection (supported: {', '.join(sorted(supported))}).",
            severity=Severity.WARNING,
            examples=tuple(kinds[:MAX_EXAMPLES]),
        )
    ]


_TableCheck = Callable[[pd.DataFrame, dict[str, _ColumnResult]], list[ValidationIssue]]

_TABLE_CHECKS: dict[str, tuple[_TableCheck, ...]] = {
    READINGS.name: (_check_canonical_units, _check_meter_consistency, _check_analysis_support),
}


# ---------------------------------------------------------------------------
# Issue construction and wording
# ---------------------------------------------------------------------------


def _table_issue(
    code: IssueCode,
    column: str | None,
    message: str,
    severity: Severity = Severity.ERROR,
) -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, column=column, message=message, count=0)


def _row_issue(
    code: IssueCode,
    column: str | None,
    mask: BoolArray,
    message: str,
    severity: Severity = Severity.ERROR,
    examples: tuple[str, ...] = (),
) -> ValidationIssue:
    positions = np.flatnonzero(mask)
    return ValidationIssue(
        code=code,
        severity=severity,
        column=column,
        message=message,
        count=len(positions),
        rows=tuple(int(p) + 1 for p in positions[:MAX_EXAMPLES]),
        examples=examples,
    )


def _examples(values: pd.Series[Any], mask: BoolArray) -> tuple[str, ...]:
    distinct = pd.unique(values[mask].astype("object"))[:MAX_EXAMPLES]
    return tuple(_format_value(v) for v in distinct)


def _shown(values: pd.Series[Any], mask: BoolArray) -> str:
    return ", ".join(_examples(values, mask))


def _format_value(value: object) -> str:
    text = repr(value) if isinstance(value, str) else str(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _where(mask: BoolArray) -> str:
    positions = np.flatnonzero(mask)
    shown = ", ".join(str(int(p) + 1) for p in positions[:MAX_EXAMPLES])
    if len(positions) == 1:
        return f"row {shown}"
    more = len(positions) - MAX_EXAMPLES
    return f"rows {shown}" + (f" and {more} more" if more > 0 else "")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _phrase(mask: BoolArray, singular: str, plural: str) -> str:
    """'1 value is missing' / '3 values are missing': the verb phrase agrees in number."""
    n = int(mask.sum())
    return f"1 value {singular}" if n == 1 else f"{n} values {plural}"


def _have(n: int) -> str:
    return "has" if n == 1 else "have"


def _suggestion(values: pd.Series[Any], mask: BoolArray, choices: tuple[str, ...]) -> str:
    by_folded = {choice.casefold(): choice for choice in choices}
    hints = []
    for raw in pd.unique(values[mask].astype("object"))[:MAX_EXAMPLES]:
        match = by_folded.get(str(raw).strip().casefold())
        if match is not None:
            hints.append(f"{raw!r} -> {match!r}")
    return f" Did you mean: {', '.join(hints)}?" if hints else ""
