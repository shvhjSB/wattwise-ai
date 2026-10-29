"""Schemas for CSV uploads and the analysis of an uploaded dataset."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from wattwise.api.schemas.catalog import UtcDatetime

TableName = Literal["readings", "buildings", "weather"]


class IssueOut(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    column: str | None
    message: str = Field(description="What is wrong and how to fix it.")
    count: int = Field(description="Affected rows.")
    rows: list[int] = Field(description="Up to 5 data-row numbers (row 1 follows the header).")
    examples: list[str]


class UploadReport(BaseModel):
    """The validation report of one uploaded CSV file (docs/DATA_CONTRACT.md)."""

    table: TableName
    filename: str | None = Field(description="The client's file name, sanitised; display only.")
    bytes: int
    valid: bool = Field(description="True when the file satisfies the contract.")
    row_count: int
    contract_version: str
    errors: list[IssueOut]
    warnings: list[IssueOut]
    stored: Literal[False] = Field(default=False, description="Uploads are validated, not kept.")


class AnalysisPoint(BaseModel):
    timestamp: UtcDatetime
    observed: float | None
    expected: float | None = Field(description="The model's expectation; null without a model.")


class MeterAnalysis(BaseModel):
    meter_id: str
    building_id: str
    points: list[AnalysisPoint]


class AnalysisAlert(BaseModel):
    meter_id: str
    building_id: str
    direction: Literal["high", "low"]
    start: UtcDatetime
    end: UtcDatetime
    duration_hours: int
    flagged_hours: int
    peak_score: float
    signature: str
    description: str
    evidence: dict[str, Any]


class AnalysisResponse(BaseModel):
    data_label: Literal["uploaded"] = Field(
        default="uploaded",
        description="Supplied by the client: not checked against any source, synthetic or not.",
    )
    detector: str = Field(description="The alert source (D030), which needs no model.")
    model_version: str | None
    prediction_note: str
    meters: list[MeterAnalysis]
    alerts: list[AnalysisAlert]
    caveats: list[str]
    reports: list[UploadReport]
    stored: Literal[False] = False
    retrained: Literal[False] = False
