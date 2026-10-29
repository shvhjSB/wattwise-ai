"""Schemas for model metadata, metrics and analysis-run records."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from wattwise.api.schemas.catalog import UtcDatetime

#: Why a model's information is unavailable. Never replaced by made-up values.
UnavailableReason = Literal["no_model_promoted", "model_invalid", "model_incompatible"]

METRIC_DEFINITIONS = {
    "mae": "Mean absolute error, kWh per hourly reading.",
    "rmse": "Root mean squared error, kWh per hourly reading.",
    "bias": "Mean of prediction minus observed, kWh (negative: the model under-predicts).",
    "wape": "Sum of absolute errors divided by the sum of observed values.",
    "scored": "Readings with both an observation and a prediction.",
    "missing_prediction": "Readings with an observation but no prediction (no usable scale).",
}


class Unavailable(BaseModel):
    available: Literal[False] = False
    reason: UnavailableReason
    message: str


class ModelMetadataOut(BaseModel):
    available: Literal[True] = True
    version: str
    created_at: UtcDatetime
    serves: str = Field(description="What this model is used for in the API.")
    model: dict[str, Any] = Field(description="Name, family, variant, settings and seed.")
    feature_set_version: str
    horizon_hours: int
    feature_columns: list[str]
    training: dict[str, Any] = Field(description="Training window, rows, meters, data fingerprint.")
    split: dict[str, Any] = Field(
        description="The chronological split it was trained and tested on."
    )
    code: dict[str, Any]
    libraries: dict[str, str]


class RoleMetrics(BaseModel):
    role: Literal["validation", "test"]
    window_start: UtcDatetime | None
    window_end: UtcDatetime | None
    metrics: dict[str, float | int | None] | None = Field(
        description="As recorded at training time; null if not recorded."
    )


class ModelMetricsOut(BaseModel):
    available: Literal[True] = True
    version: str
    data_label: Literal["observed"] = Field(
        default="observed", description="Scored on measured BDG2 readings, not synthetic data."
    )
    roles: list[RoleMetrics]
    definitions: dict[str, str]
    note: str


class AnalysisRunOut(BaseModel):
    run_id: int
    created_at: UtcDatetime = Field(description="When the analysis ran (the prediction time).")
    model_version: str | None = Field(description="Null when no model was available.")
    detector: str
    input_start: UtcDatetime
    input_end: UtcDatetime
    meters: int
    readings: int
    missing_values: int
    predictions: int
    alerts: int
