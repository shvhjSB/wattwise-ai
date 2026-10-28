"""Load detected alerts into the database (docs/DATABASE.md, D047, T025).

The input is the evidence bundles written by `wattwise.ml.explanations` (its
`explanations.json`). Each bundle is scored with the T022 priority formula and stored with its
severity band and its whole bundle as evidence.

**Reloading keeps reviews.** Alerts are matched on (meter, detector, start):
- a matched alert is updated in place, so its id and its feedback survive;
- an alert no longer detected is deleted, unless someone has reviewed it, in which case it is
  kept and marked `superseded` (feedback is never deleted);
- anything new is inserted.

The scope of a load is one dataset and the detectors in the file: alerts of other datasets or
other detectors are never touched.

    uv run --env-file .env python -m wattwise.db.alerts --dataset-id bdg2-cleaned \\
        --explanations ../data/processed/fullscale-downstream/explanations-lean/explanations.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, exists, func, insert, select, update

from wattwise.core.config import get_settings
from wattwise.db.engine import create_db_engine
from wattwise.db.models import Alert, AlertFeedback, Building, Meter
from wattwise.ml.prioritisation import PriorityConfig, components, kind_of, score_of, severity_of


@dataclass(frozen=True)
class AlertLoadSummary:
    inserted: int
    updated: int
    deleted: int
    superseded: int


def alert_row(bundle: Mapping[str, Any], config: PriorityConfig) -> dict[str, Any]:
    """The `alerts` columns for one evidence bundle (without the id or review fields)."""
    event = bundle["event"]
    score = round(score_of(components(bundle, config), config), 2)
    excess = bundle["impact"].get("potential_excess_kwh")
    return {
        "meter_id": event["meter_id"],
        "detector": bundle["detector"]["name"],
        "start": datetime.fromisoformat(event["start"]),
        "end": datetime.fromisoformat(event["end"]),
        "duration_hours": int(event["duration_hours"]),
        "flagged_hours": int(event["flagged_hours"]),
        "direction": event["direction"],
        "signature": bundle["signature"]["primary"],
        "kind": kind_of(bundle),
        "peak_score": event.get("peak_z"),
        "priority_score": score,
        "severity": severity_of(score),
        "potential_excess_kwh": None if excess is None else float(excess),
        "model_version": bundle.get("model", {}).get("version"),
        "evidence": dict(bundle),
    }


def load_alerts(
    connection: Connection,
    dataset_id: str,
    bundles: Sequence[Mapping[str, Any]],
    config: PriorityConfig | None = None,
) -> AlertLoadSummary:
    """Store `bundles` as `dataset_id`'s alerts, inside the caller's transaction.

    Raises `ValueError` if a bundle's meter is not one of the dataset's meters, or if two
    bundles are the same alert."""
    config = config or PriorityConfig()
    rows = [alert_row(b, config) for b in bundles]
    keys = [(r["meter_id"], r["detector"], r["start"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("two bundles describe the same alert (meter, detector, start)")
    dataset_meters = set(
        connection.scalars(
            select(Meter.meter_id).join(Building).where(Building.dataset_id == dataset_id)
        )
    )
    foreign = sorted({r["meter_id"] for r in rows} - dataset_meters)
    if foreign:
        raise ValueError(f"meters not in dataset {dataset_id!r}: {foreign[:5]}")

    detectors = sorted({r["detector"] for r in rows})
    in_scope = Alert.meter_id.in_(sorted(dataset_meters)) & Alert.detector.in_(detectors)
    existing = {
        (m, d, s): i
        for i, m, d, s in connection.execute(
            select(Alert.alert_id, Alert.meter_id, Alert.detector, Alert.start).where(in_scope)
        )
    }
    new_rows = [r for r, k in zip(rows, keys, strict=True) if k not in existing]
    matched = [
        {**r, "alert_id": existing[k], "superseded": False}
        for r, k in zip(rows, keys, strict=True)
        if k in existing
    ]
    gone = set(existing.values()) - {r["alert_id"] for r in matched}
    reviewed = (
        set(
            connection.scalars(
                select(Alert.alert_id).where(
                    Alert.alert_id.in_(sorted(gone)),
                    exists().where(AlertFeedback.alert_id == Alert.alert_id),
                )
            )
        )
        if gone
        else set()
    )

    if new_rows:
        connection.execute(insert(Alert), new_rows)
    for row in matched:  # one statement per alert keeps the JSONB evidence typed
        alert_id = row.pop("alert_id")
        connection.execute(
            update(Alert).where(Alert.alert_id == alert_id).values(**row, updated_at=func.now())
        )
    if reviewed:
        connection.execute(
            update(Alert)
            .where(Alert.alert_id.in_(sorted(reviewed)))
            .values(superseded=True, updated_at=func.now())
        )
    if gone - reviewed:
        connection.execute(delete(Alert).where(Alert.alert_id.in_(sorted(gone - reviewed))))
    return AlertLoadSummary(
        inserted=len(new_rows),
        updated=len(matched),
        deleted=len(gone - reviewed),
        superseded=len(reviewed),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.db.alerts",
        description="Score and store the alerts of an explanations.json (keeping reviews).",
    )
    parser.add_argument("--explanations", type=Path, required=True, help="explanations.json")
    parser.add_argument("--dataset-id", required=True, help="the dataset the meters belong to")
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if url is None:
        print("error: WATTWISE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_db_engine(url.get_secret_value())
    try:
        bundles = json.loads(args.explanations.read_text(encoding="utf-8"))["events"]
        with engine.begin() as connection:
            summary = load_alerts(connection, args.dataset_id, bundles)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"alerts for {args.dataset_id}: {summary.inserted} inserted, {summary.updated} updated, "
        f"{summary.deleted} deleted, {summary.superseded} kept as superseded (reviewed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
