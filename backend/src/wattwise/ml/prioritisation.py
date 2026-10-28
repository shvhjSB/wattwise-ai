"""Alert prioritisation: rank alerts by likely business impact (docs/EVALUATION.md, D044, T022).

The score is a transparent weighted sum of four components, each between 0 and 1, scaled to
0-100. **It orders alerts for review; it is not a probability, a verified saving or a measure of
waste.** An anomaly is not confirmed waste, and the impact component is the *potential* excess
of T021, never a verified figure.

| Component | Weight | What it measures | 0 means | 1 means |
|---|---|---|---|---|
| impact | 0.40 | potential excess kWh above the upper bound | none | `impact_cap_kwh` |
| persistence | 0.20 | flagged hours | 1 hour | `persistence_cap_hours` |
| severity | 0.20 | the detector's peak score | the threshold | `severity_cap` |
| confidence | 0.20 | agreement and coverage (below) | all against | all for |

- **Impact, persistence and severity** use a logarithmic scale: each doubling counts the same,
  so one extreme reading cannot swamp the ordering (real peak scores range from 4 to 15
  million).
- **Confidence** is the mean of two things: whether the model's interval agrees with the
  detector (1 if some hour was outside the interval in the alert's direction, 0 if none, 0.5 if
  the model had no interval), and the share of the event's hours the detector flagged.
- **Meter problems** (`data_fault`, `flatline`) are not consumption (D029, D040), so their impact
  component is 0. They still rank on persistence, severity and confidence, and they are marked
  `kind: "meter_problem"` so a caller can list them apart. The same holds for alerts below the
  expected level, which have no excess above the bound (`kind: "below_expected"`).
- **Cost and carbon do not enter the score**: a tariff is optional and per geography, and mixing
  currencies would change the ordering depending on configuration.
- **Deterministic ties:** the score rounded to 2 decimals, then larger potential excess, then
  more flagged hours, then the earlier start, then meter id, then the later end.
- **Severity bands** (T025): `high` from 60, `medium` from 40, `low` below. On the 5,546
  full-scale alerts that is 4.2%, 28.6% and 67.2%. A band is a coarser view of the same score,
  for filtering, and says nothing more than the score does.

The weights and caps are **product assumptions, not fitted to labels**. They were set from the
range of real alerts at full scale (D044): the impact cap is just above the largest potential
excess seen (19,307 kWh), so large differences still count; the persistence cap (72 hours) is
the 99th percentile of flagged hours and the severity cap (100) the 98th percentile of peak
scores, as beyond them a longer or sharper alert is not meaningfully more urgent.

    uv run python -m wattwise.ml.prioritisation \\
        --explanations ../data/processed/fullscale-downstream/explanations-lean/explanations.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wattwise.data.acquisition import sha256_of
from wattwise.ml.explanations import wording_problems
from wattwise.ml.signatures import METER_PROBLEMS, Signature

PRIORITY_VERSION: Final = "1"
DEFAULT_OUTPUT: Final = Path("../data/processed/detection/priorities")
THRESHOLD_SCORE: Final = 4.0  # the detector's alert threshold: peak score 0 on the scale below
#: Lower score bounds of the severity bands, highest first (a product assumption, D047).
SEVERITY_BANDS: Final = (("high", 60.0), ("medium", 40.0), ("low", 0.0))


class PriorityConfig(BaseModel):
    """Weights (summing to 1) and the caps at which a component saturates."""

    model_config = ConfigDict(frozen=True)

    impact_weight: float = Field(default=0.4, ge=0)
    persistence_weight: float = Field(default=0.2, ge=0)
    severity_weight: float = Field(default=0.2, ge=0)
    confidence_weight: float = Field(default=0.2, ge=0)
    impact_cap_kwh: float = Field(default=20_000.0, gt=0)
    persistence_cap_hours: float = Field(default=72.0, gt=1)
    severity_cap: float = Field(default=100.0, gt=THRESHOLD_SCORE)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> Self:
        total = (
            self.impact_weight
            + self.persistence_weight
            + self.severity_weight
            + self.confidence_weight
        )
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"the weights must sum to 1, got {total}")
        return self


def _number(value: Any) -> float | None:
    """A finite float, or None (bundles carry null for anything not finite)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _saturating(value: float, low: float, cap: float) -> float:
    """0 at `low`, 1 at `cap`, logarithmic between, clipped to [0, 1]."""
    if value <= low:
        return 0.0
    return min(1.0, math.log(value / low) / math.log(cap / low))


def kind_of(bundle: Mapping[str, Any]) -> str:
    """`meter_problem`, `below_expected` or `above_expected`: what kind of alert this is."""
    if Signature(bundle["signature"]["primary"]) in METER_PROBLEMS:
        return "meter_problem"
    return "above_expected" if bundle["event"]["direction"] == "high" else "below_expected"


def components(bundle: Mapping[str, Any], config: PriorityConfig) -> dict[str, float]:
    """The four components of one evidence bundle, each in [0, 1]."""
    event, model = bundle["event"], bundle["model"]
    excess = _number(bundle["impact"].get("potential_excess_kwh"))
    impact = 0.0
    if kind_of(bundle) == "above_expected" and excess is not None and excess > 0:
        # a log scale on excess + 1 kWh, so that no excess scores exactly 0
        impact = _saturating(excess + 1.0, 1.0, config.impact_cap_kwh + 1.0)
    flagged = _number(event.get("flagged_hours")) or 0.0
    duration = _number(event.get("duration_hours")) or 0.0
    peak = _number(event.get("peak_z"))
    agree = model.get("agrees_with_detector")
    return {
        "impact": impact,
        "persistence": _saturating(flagged, 1.0, config.persistence_cap_hours),
        "severity": 0.0
        if peak is None
        else _saturating(peak, THRESHOLD_SCORE, config.severity_cap),
        "confidence": 0.5 * (0.5 if agree is None else float(bool(agree)))
        + 0.5 * (min(1.0, flagged / duration) if duration > 0 else 0.0),
    }


def severity_of(score: float) -> str:
    """The severity band of a 0-100 priority score."""
    return next(name for name, low in SEVERITY_BANDS if score >= low)


def score_of(parts: Mapping[str, float], config: PriorityConfig) -> float:
    """The 0-100 score: the weighted sum of the components."""
    return 100.0 * (
        config.impact_weight * parts["impact"]
        + config.persistence_weight * parts["persistence"]
        + config.severity_weight * parts["severity"]
        + config.confidence_weight * parts["confidence"]
    )


def prioritise(
    bundles: Sequence[Mapping[str, Any]], config: PriorityConfig | None = None
) -> list[dict[str, Any]]:
    """Rank evidence bundles (`wattwise.ml.explanations`), highest priority first.

    Each result carries its rank (1 is first), score, components and enough of the event to
    find its bundle. The order does not depend on the order of `bundles`."""
    config = config or PriorityConfig()
    rows = []
    for bundle in bundles:
        parts = components(bundle, config)
        event = bundle["event"]
        excess = _number(bundle["impact"].get("potential_excess_kwh"))
        rows.append(
            {
                "meter_id": event["meter_id"],
                "building_id": event["building_id"],
                "start": event["start"],
                "end": event["end"],
                "signature": bundle["signature"]["primary"],
                "direction": event["direction"],
                "kind": kind_of(bundle),
                "flagged_hours": int(event["flagged_hours"]),
                "potential_excess_kwh": excess,
                "score": round(score_of(parts, config), 2),
                "components": {name: round(value, 4) for name, value in parts.items()},
            }
        )
    rows.sort(
        key=lambda r: (
            -r["score"],
            -(r["potential_excess_kwh"] or 0.0),
            -r["flagged_hours"],
            r["start"],
            r["meter_id"],
            _reversed_text(r["end"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _reversed_text(text: str) -> tuple[int, ...]:
    """Sorts text in descending order inside an ascending key (the later end first)."""
    return tuple(-ord(c) for c in text)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def to_markdown(
    ranked: Sequence[Mapping[str, Any]], config: PriorityConfig, limit: int = 20
) -> str:
    kinds = {
        k: sum(1 for r in ranked if r["kind"] == k) for k in sorted({r["kind"] for r in ranked})
    }
    counts = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in kinds.items())
    header = "| Rank | Score | Meter | Start (UTC) | Kind | Signature | Flagged h | Excess kWh |"
    lines = [
        "# Alert priorities (T022)",
        "",
        f"{len(ranked)} alerts ranked ({counts}).",
        "The score (0-100) orders alerts for review. It is not a probability or a verified saving;",
        "the excess is a potential figure from the model's interval. Weights and caps are product",
        f"assumptions: {config.model_dump()}.",
        "",
        f"The top {min(limit, len(ranked))}:",
        "",
        header,
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in ranked[:limit]:
        excess = r["potential_excess_kwh"]
        lines.append(
            f"| {r['rank']} | {r['score']:.2f} | {r['meter_id']} | {r['start']} | "
            f"{r['kind'].replace('_', ' ')} | {r['signature'].replace('_', ' ')} | "
            f"{r['flagged_hours']} | {'n/a' if excess is None else f'{excess:,.1f}'} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.prioritisation",
        description="Rank the alerts of an explanations.json by likely business impact.",
    )
    parser.add_argument("--explanations", type=Path, required=True, help="explanations.json (T020)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.explanations.read_text(encoding="utf-8"))
        config = PriorityConfig()
        ranked = prioritise(payload["events"], config)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    markdown = to_markdown(ranked, config)
    problems = wording_problems(markdown)
    if problems:
        print(f"error: forbidden wording in the summary: {sorted(set(problems))}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    document = {
        "priority_version": PRIORITY_VERSION,
        "config": config.model_dump(),
        "alerts": ranked,
    }
    (args.output / "priorities.json").write_bytes(
        (json.dumps(document, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    (args.output / "priorities.md").write_bytes(markdown.encode("utf-8"))
    print(f"{len(ranked)} alerts ranked -> {args.output}")
    for name in ("priorities.json", "priorities.md"):
        print(f"  {name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
