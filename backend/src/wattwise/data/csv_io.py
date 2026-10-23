"""Read CSV files in the documented upload format (docs/DATA_CONTRACT.md).

Format: UTF-8 (a byte-order mark is allowed), comma-separated, one header row with the contract's
column names, standard double-quote quoting, '.' as decimal separator, an empty cell for a missing
value, and ISO 8601 timestamps with an explicit offset. Every cell is read as text and then
validated by the same rules as in-memory tables, so the file never decides its own types.

Rows are parsed with the standard library `csv` module rather than pandas, because pandas pads
rows that have too few fields with empty strings, which makes them indistinguishable from rows
with empty cells.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, cast

import pandas as pd

from wattwise.data.contracts import TEXT_DTYPE, TableContract
from wattwise.data.validation import (
    MAX_EXAMPLES,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
    check_table,
)

CsvSource = str | os.PathLike[str] | IO[str] | IO[bytes]


@dataclass(frozen=True)
class CsvReadResult:
    """The validation report, and the canonical table when the file satisfies the contract."""

    report: ValidationReport
    frame: pd.DataFrame | None


def read_csv(source: CsvSource, contract: TableContract) -> CsvReadResult:
    """Read and validate a CSV file against `contract`.

    Never raises for problems in the file's content; they are returned in the report.
    """
    rows: list[list[str]] = []
    lines: list[int] = []
    try:
        with _open_text(source) as stream:
            reader = csv.reader(stream, strict=True)
            for row in reader:
                if row:  # blank lines are skipped
                    rows.append(row)
                    lines.append(reader.line_num)
    except UnicodeDecodeError as exc:
        return _failed(
            contract,
            IssueCode.INVALID_ENCODING,
            f"The file is not valid UTF-8 text ({exc.reason} at byte {exc.start}). Save it as "
            "UTF-8 CSV.",
        )
    except csv.Error as exc:
        return _failed(
            contract,
            IssueCode.MALFORMED_CSV,
            f"The file is not valid CSV ({exc}). Quote values that contain commas, quotes or "
            "line breaks with double quotes.",
        )

    if not rows:
        return _failed(
            contract,
            IssueCode.EMPTY_TABLE,
            f"The file is empty. A {contract.name} CSV needs a header row and data rows.",
        )

    header = [name.lstrip("﻿").strip() for name in rows[0]]
    unnamed = [position + 1 for position, name in enumerate(header) if not name]
    if unnamed:
        return _failed(
            contract,
            IssueCode.MALFORMED_CSV,
            f"Header column(s) {', '.join(map(str, unnamed))} have no name. The first row must "
            f"name every column, e.g. {','.join(contract.column_names)}.",
        )

    data, data_lines = rows[1:], lines[1:]
    ragged = [i for i, row in enumerate(data) if len(row) != len(header)]
    if ragged:
        shown = ragged[:MAX_EXAMPLES]
        more = len(ragged) - len(shown)
        details = ", ".join(f"row {i + 1} (line {data_lines[i]}) has {len(data[i])}" for i in shown)
        message = (
            f"{len(ragged)} row(s) do not have {len(header)} fields like the header: {details}"
            f"{f' and {more} more' if more > 0 else ''}. Every row needs one field per column; "
            "use an empty field for a missing value and quote values that contain commas."
        )
        issue = ValidationIssue(
            code=IssueCode.MALFORMED_CSV,
            severity=Severity.ERROR,
            column=None,
            message=message,
            count=len(ragged),
            rows=tuple(i + 1 for i in shown),
        )
        return CsvReadResult(report=_report(contract, len(data), (issue,)), frame=None)

    table = pd.DataFrame(data, columns=pd.Index(header), dtype=TEXT_DTYPE)
    report, canonical = check_table(table, contract)
    return CsvReadResult(report=report, frame=canonical if report.ok else None)


@contextmanager
def _open_text(source: CsvSource) -> Generator[IO[str]]:
    """Yield a text stream for `source`, decoding bytes as UTF-8 (with optional BOM)."""
    if isinstance(source, str | os.PathLike):
        with open(source, encoding="utf-8-sig", newline="") as handle:
            yield handle
        return
    # read(0) consumes nothing and tells text streams ('') from binary ones (b'') of any class.
    if isinstance(source.read(0), str):
        yield cast(IO[str], source)
        return
    wrapper = io.TextIOWrapper(cast(IO[bytes], source), encoding="utf-8-sig", newline="")
    try:
        yield wrapper
    finally:
        wrapper.detach()  # leave the caller's binary stream open


def _report(
    contract: TableContract, row_count: int, issues: tuple[ValidationIssue, ...]
) -> ValidationReport:
    return ValidationReport(
        table=contract.name,
        contract_version=contract.version,
        row_count=row_count,
        issues=issues,
    )


def _failed(contract: TableContract, code: IssueCode, message: str) -> CsvReadResult:
    issue = ValidationIssue(
        code=code, severity=Severity.ERROR, column=None, message=message, count=0
    )
    return CsvReadResult(report=_report(contract, 0, (issue,)), frame=None)
