"""Evidence bundles shaped like `wattwise.ml.explanations` output, for the synthetic sample's
meters (crafted for tests; not detections)."""

from typing import Any


def bundle(
    meter: str,
    start: str,
    hours: int,
    *,
    flagged: int | None = None,
    signature: str = "sustained",
    direction: str = "high",
    excess: float | None = 100.0,
    peak: float = 10.0,
    agrees: bool | None = True,
    detector: str = "rolling-z",
) -> dict[str, Any]:
    from datetime import datetime, timedelta

    begin = datetime.fromisoformat(start)
    end = begin + timedelta(hours=hours)
    building = meter.split(":")[0]
    return {
        "event": {
            "meter_id": meter,
            "building_id": building,
            "direction": direction,
            "start": f"{begin:%Y-%m-%dT%H:%M:%SZ}",
            "end": f"{end:%Y-%m-%dT%H:%M:%SZ}",
            "duration_hours": hours,
            "flagged_hours": hours if flagged is None else flagged,
            "missing_hours": 0,
            "peak_time": f"{begin:%Y-%m-%dT%H:%M:%SZ}",
            "peak_z": peak,
        },
        "detector": {"name": detector, "baseline": "the same hour on the previous 14 days"},
        "model": {"version": "test-model", "agrees_with_detector": agrees},
        "signature": {"primary": signature, "all": [signature], "evidence": {}},
        "influences": [],
        "impact": {
            "status": "potential",
            "meter_problem": signature in ("data_fault", "flatline"),
            "potential_excess_kwh": excess,
        },
        "check": "Check the schedule.",
        "explanation": f"{meter}: crafted test alert, an anomaly to investigate.",
    }


#: Five alerts across the sample's four meters, one of each kind and a range of priorities.
SAMPLE_BUNDLES = [
    bundle("syn-office-a:electricity", "2016-01-20T14:00:00+00:00", 3, excess=1500.0, peak=40.0),
    bundle("syn-retail-b:electricity", "2016-02-08T00:00:00+00:00", 72, excess=800.0),
    bundle(
        "syn-lab-c:electricity",
        "2016-02-01T00:00:00+00:00",
        30,
        signature="flatline",
        excess=None,
        agrees=None,
    ),
    bundle(
        "syn-office-d:electricity",
        "2016-01-25T00:00:00+00:00",
        12,
        direction="low",
        signature="sustained",
        excess=0.0,
    ),
    bundle(
        "syn-office-a:electricity",
        "2016-02-15T01:00:00+00:00",
        4,
        flagged=2,
        signature="overnight_excess",
        excess=20.0,
        peak=5.0,
        agrees=False,
    ),
]
