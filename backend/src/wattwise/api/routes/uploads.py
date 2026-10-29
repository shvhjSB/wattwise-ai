"""CSV upload validation and the analysis of an uploaded dataset."""

import io
import math
import re
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from wattwise.api.dependencies import get_app_settings
from wattwise.api.schemas.uploads import (
    AnalysisResponse,
    IssueOut,
    TableName,
    UploadReport,
)
from wattwise.core.config import Settings
from wattwise.data.contracts import CONTRACTS
from wattwise.data.csv_io import read_csv
from wattwise.ml.analysis import analyze, events_as_records

router = APIRouter(tags=["data"])

#: Bounds on one analysis, so a request cannot occupy the server for long.
MAX_ANALYSIS_ROWS = 200_000
MAX_ANALYSIS_METERS = 50
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
CAVEATS = [
    "Uploaded data is analysed as given; it is not checked against any source.",
    "An alert is an anomaly to investigate, not confirmed waste.",
    "Expected consumption for an uploaded building is an extrapolation that has not been "
    "validated.",
    "Nothing is stored, and no model is retrained.",
]

SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def safe_filename(name: str | None) -> str | None:
    """The client's file name for display only: no directories, only safe characters, at most
    100 characters. It is never used to open or write a file."""
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    cleaned = _UNSAFE.sub("_", base)[:100].lstrip(".")
    return cleaned or None


def _check_length(request: Request, settings: Settings, files: int) -> None:
    """Refuse an oversized request before reading it, when it declares its size."""
    declared = request.headers.get("content-length")
    overhead = 64_000  # multipart boundaries and headers
    if (
        declared
        and declared.isdigit()
        and int(declared) > files * settings.max_upload_bytes + overhead
    ):
        raise HTTPException(status_code=413, detail="the request is larger than the upload limit")


def _read(file: UploadFile, settings: Settings) -> bytes:
    """The file's bytes, refusing more than the limit (the declared size is not trusted)."""
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{safe_filename(file.filename) or 'the file'} is larger than "
            f"{settings.max_upload_bytes:,} bytes",
        )
    return data


def _report(
    table: TableName, file: UploadFile, data: bytes
) -> tuple[UploadReport, pd.DataFrame | None]:
    result = read_csv(io.BytesIO(data), CONTRACTS[table])
    report = result.report

    def issues(found: Any) -> list[IssueOut]:
        return [
            IssueOut(
                code=i.code.value,
                severity=i.severity.value,
                column=i.column,
                message=i.message,
                count=i.count,
                rows=list(i.rows),
                examples=[str(e) for e in i.examples],
            )
            for i in found
        ]

    return (
        UploadReport(
            table=table,
            filename=safe_filename(file.filename),
            bytes=len(data),
            valid=report.ok,
            row_count=report.row_count,
            contract_version=report.contract_version,
            errors=issues(report.errors),
            warnings=issues(report.warnings),
        ),
        result.frame if report.ok else None,
    )


@router.post(
    "/data/upload",
    summary="Validate a CSV file against the data contract",
    response_model=UploadReport,
    responses={
        413: {"description": "The file is larger than the upload limit."},
        422: {"model": UploadReport, "description": "The file violates the contract."},
    },
)
def upload(
    request: Request,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="A CSV file in the documented format.")],
    table: Annotated[TableName, Query(description="Which table the file holds.")] = "readings",
) -> UploadReport | JSONResponse:
    """Validate one CSV file and return its report: 200 when valid, 422 with the same report when
    not. The file is read in memory, never written to disk under its name, and not stored."""
    _check_length(request, settings, files=1)
    report, _ = _report(table, file, _read(file, settings))
    if not report.valid:
        return JSONResponse(status_code=422, content=report.model_dump(mode="json"))
    return report


@router.post(
    "/inference/analyze",
    summary="Expected consumption and alerts for an uploaded dataset",
    responses={
        413: {"description": "A file, or the dataset, is larger than the limits."},
        422: {"description": "A file violates the contract, or the files do not match."},
    },
)
def analyze_upload(
    request: Request,
    settings: SettingsDep,
    readings: Annotated[UploadFile, File(description="readings CSV")],
    buildings: Annotated[UploadFile, File(description="buildings CSV")],
    weather: Annotated[UploadFile | None, File(description="optional weather CSV")] = None,
) -> AnalysisResponse:
    """Validate the files, then return each meter's readings with the model's expectation and the
    default detector's alerts. Nothing is stored and nothing is retrained."""
    _check_length(request, settings, files=3)
    parts: list[tuple[TableName, UploadFile]] = [("readings", readings), ("buildings", buildings)]
    if weather is not None:
        parts.append(("weather", weather))
    reports, frames = [], {}
    for table, file in parts:
        report, frame = _report(table, file, _read(file, settings))
        reports.append(report)
        frames[table] = frame
    if any(not r.valid for r in reports):
        raise HTTPException(status_code=422, detail=[r.model_dump(mode="json") for r in reports])
    table_readings, table_buildings = frames["readings"], frames["buildings"]
    assert table_readings is not None and table_buildings is not None
    missing = sorted(set(table_readings["building_id"]) - set(table_buildings["building_id"]))
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"readings name buildings not in the buildings file: {missing[:5]}",
        )
    if len(table_readings) > MAX_ANALYSIS_ROWS:
        raise HTTPException(status_code=413, detail=f"at most {MAX_ANALYSIS_ROWS:,} readings")
    if table_readings["meter_id"].nunique() > MAX_ANALYSIS_METERS:
        raise HTTPException(status_code=413, detail=f"at most {MAX_ANALYSIS_METERS} meters")

    result = analyze(table_readings, table_buildings, frames.get("weather"), settings.registry_root)
    ordered = table_readings.reset_index(drop=True)
    meters = []
    for (meter_id, building_id), group in ordered.groupby(["meter_id", "building_id"], sort=True):
        expected = None if result.expected is None else result.expected.loc[group.index]
        meters.append(
            {
                "meter_id": str(meter_id),
                "building_id": str(building_id),
                "points": [
                    {
                        "timestamp": t,
                        "observed": _number(v),
                        "expected": None if expected is None else _number(e),
                    }
                    for t, v, e in zip(
                        group["timestamp"],
                        group["value"],
                        group["value"] if expected is None else expected,
                        strict=True,
                    )
                ],
            }
        )
    return AnalysisResponse.model_validate(
        {
            "detector": result.detector.value,
            "model_version": result.model_version,
            "prediction_note": result.prediction_note,
            "meters": meters,
            "alerts": events_as_records(result.events),
            "caveats": CAVEATS,
            "reports": reports,
        }
    )


def _number(value: Any) -> float | None:
    number = float(value)
    return None if math.isnan(number) else number
