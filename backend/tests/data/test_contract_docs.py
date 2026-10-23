"""Keep docs/DATA_CONTRACT.md truthful: it must name everything the code defines, and its
CSV examples must behave exactly as the document says."""

import io
import re
from pathlib import Path

from wattwise.data.contracts import CONTRACT_VERSION, CONTRACTS, READINGS, MeterType, Unit
from wattwise.data.csv_io import read_csv
from wattwise.data.validation import IssueCode

DOC = Path(__file__).resolve().parents[3] / "docs" / "DATA_CONTRACT.md"


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def fenced_blocks(language: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", doc_text(), flags=re.DOTALL)


def test_documents_the_contract_version() -> None:
    assert f"**Contract version: `{CONTRACT_VERSION}`**" in doc_text()


def test_documents_every_column_of_every_table() -> None:
    text = doc_text()
    for contract in CONTRACTS.values():
        assert f"### `{contract.name}`" in text
        for column in contract.columns:
            assert f"| `{column.name}` |" in text, f"{contract.name}.{column.name}"


def test_documents_every_issue_code() -> None:
    text = doc_text()
    for code in IssueCode:
        assert f"| `{code.value}` |" in text, code.value


def test_documents_every_meter_type_and_unit() -> None:
    text = doc_text()
    for meter_type in MeterType:
        assert f"| `{meter_type.value}` |" in text, meter_type.value
    for unit in Unit:
        assert f"`{unit.value}`" in text, unit.value


def test_valid_csv_example_is_valid() -> None:
    valid, _ = fenced_blocks("csv")

    report = read_csv(io.StringIO(valid), READINGS).report

    assert report.ok, report.issues
    assert report.issues == ()


def test_faulty_csv_example_produces_exactly_the_documented_messages() -> None:
    _, faulty = fenced_blocks("csv")
    (documented,) = fenced_blocks("text")

    report = read_csv(io.StringIO(faulty), READINGS).report
    actual = [f"[{issue.code.value}] {issue.message}" for issue in report.issues]

    assert actual == documented.strip().splitlines()
