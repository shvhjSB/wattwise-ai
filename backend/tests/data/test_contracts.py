import re

import pytest

from wattwise.data.contracts import (
    ANALYSIS_SUPPORTED,
    CANONICAL_UNIT,
    CONTRACTS,
    IDENTIFIER_PATTERN,
    READINGS,
    ColumnKind,
    MeterType,
    TableContract,
    Unit,
)
from wattwise.data.validation import UNKNOWN_CATEGORY_CODES


def test_every_meter_type_has_exactly_one_canonical_unit() -> None:
    assert set(CANONICAL_UNIT) == set(MeterType)


def test_electricity_is_measured_in_kwh_and_supported_for_analysis() -> None:
    assert CANONICAL_UNIT[MeterType.ELECTRICITY] is Unit.KWH
    assert MeterType.ELECTRICITY in ANALYSIS_SUPPORTED


@pytest.mark.parametrize("contract", CONTRACTS.values(), ids=list(CONTRACTS))
def test_primary_key_columns_are_required_and_never_missing(contract: TableContract) -> None:
    for name in contract.primary_key:
        column = contract.column(name)
        assert column.required
        assert not column.nullable


@pytest.mark.parametrize("contract", CONTRACTS.values(), ids=list(CONTRACTS))
def test_column_names_are_unique(contract: TableContract) -> None:
    assert len(contract.column_names) == len(set(contract.column_names))


def test_every_category_column_has_a_vocabulary_and_an_issue_code() -> None:
    for contract in CONTRACTS.values():
        for column in contract.columns:
            if column.kind is ColumnKind.CATEGORY:
                assert column.choices, column.name
                assert column.name in UNKNOWN_CATEGORY_CODES, column.name


def test_column_lookup() -> None:
    assert READINGS.column("value").nullable
    with pytest.raises(KeyError):
        READINGS.column("kwh")


@pytest.mark.parametrize(
    "identifier",
    ["b1", "Panther_parking_Lorriane", "site-a:electricity", "M.01", "x" * 128],
)
def test_identifier_pattern_accepts(identifier: str) -> None:
    assert re.fullmatch(IDENTIFIER_PATTERN, identifier)


@pytest.mark.parametrize(
    "identifier",
    ["", " b1", "b 1", "_b1", "b1,b2", "bâtiment", "x" * 129, "../etc"],
)
def test_identifier_pattern_rejects(identifier: str) -> None:
    assert not re.fullmatch(IDENTIFIER_PATTERN, identifier)
