"""Schemas for alerts and reviewers' feedback."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wattwise.api.schemas.catalog import DataKindName, UtcDatetime
from wattwise.db.models import NOTE_LENGTH, REVIEWER_LENGTH, FeedbackLabel

Severity = Literal["high", "medium", "low"]
AlertKind = Literal["above_expected", "below_expected", "meter_problem"]
ReviewStatus = Literal[
    "unreviewed",
    "confirmed_waste",
    "expected_behaviour",
    "sensor_or_data_fault",
    "needs_investigation",
]
#: Control characters other than tab, line feed and carriage return (PostgreSQL text also
#: cannot hold NUL).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Shown with every alert: what the numbers are, and what they are not.
CAVEATS = (
    "An alert is an anomaly to investigate, not confirmed waste.",
    "The potential excess is an estimate above the model's interval, not a verified saving.",
    "Model influences are associations, not causes.",
)


class AlertSummary(BaseModel):
    alert_id: int
    meter_id: str
    building_id: str
    dataset_id: str
    data_kind: DataKindName
    detector: str
    start: UtcDatetime
    end: UtcDatetime
    duration_hours: int
    flagged_hours: int
    direction: Literal["high", "low"]
    signature: str
    kind: AlertKind
    severity: Severity = Field(description="Band of the priority score: high >= 60, medium >= 40.")
    priority_score: float = Field(description="0-100, for review order (T022); not a probability.")
    potential_excess_kwh: float | None = Field(
        description="Potential, not verified; null for meter problems."
    )
    review_status: ReviewStatus
    reviewed_at: UtcDatetime | None
    feedback_count: int
    superseded: bool = Field(description="No longer detected, kept because it was reviewed.")


class FeedbackIn(BaseModel):
    """A reviewer's verdict. Stored as given; no model is retrained from it (D047)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: FeedbackLabel
    note: str | None = Field(default=None, max_length=NOTE_LENGTH)
    reviewer: str | None = Field(default=None, min_length=1, max_length=REVIEWER_LENGTH)

    @field_validator("note", "reviewer")
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("must not contain control characters")
        return value or None


class FeedbackOut(BaseModel):
    feedback_id: int
    alert_id: int
    label: FeedbackLabel
    note: str | None
    reviewer: str | None
    created_at: UtcDatetime


class AlertDetail(AlertSummary):
    model_version: str | None
    explanation: str | None = Field(description="The plain-language explanation (T020).")
    evidence: dict[str, Any] = Field(description="The full evidence bundle as detected.")
    feedback: list[FeedbackOut] = Field(description="Every review, oldest first.")
    caveats: list[str]
    retrained_from_feedback: Literal[False] = Field(
        default=False, description="Feedback is stored for review; no model learns from it."
    )
