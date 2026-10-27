"""Excess energy, cost and carbon impact estimates (docs/EVALUATION.md, D038, T021).

Turns the hours above a prediction interval's upper bound (T019) into an energy, cost and
carbon estimate. **Potential, not verified:** an anomaly is not confirmed waste, and nothing in
this module is confirmed by a person. `ImpactStatus.VERIFIED` exists for a future human-feedback
label (T025); this module never sets it.

- `potential_excess_kwh`: kWh strictly above the upper bound, per row. A negative residual (at
  or below the bound) never counts, and an unknown actual or bound gives NaN, not zero.
- `TariffConfig`: a currency and a rate per kWh, explicitly configured by the caller. Without
  one, `estimate_impact` reports kWh only, never a price guessed from somewhere else.
- `estimate_impact`: the total potential excess, converted to cost with a tariff (or `None`) and
  to carbon with an already-resolved `CarbonFactor` (or `None`, "not configured"). Resolving the
  factor (by geography and year) is the caller's job, via `wattwise.data.reference` — this keeps
  the maths here testable without the committed reference tables.

The command line applies this to every T020-detected event on real data, per event's own BDG2
site (so a US and a UK site in the same run each get their own carbon factor, never each
other's). A single tariff, if given, is applied only to the one geography named with
`--geography` — mixing currencies into one total would misstate cost, so cost is never summed
across geographies here.

    uv run python -m wattwise.ml.impact --data ../data/processed/bdg2/cleaned \\
        --enrichment ../data/processed/era5/weather_enrichment.parquet \\
        --geography GB --tariff-currency GBP --tariff-rate 0.14
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from wattwise.data.acquisition import sha256_of
from wattwise.data.reference import CarbonFactor, carbon_factor, geography_for_site
from wattwise.ml.detection import Detector, run_detection
from wattwise.ml.fullscale import downstream_inputs
from wattwise.ml.registry import DEFAULT_ROOT, NoModelError, RegistryError
from wattwise.ml.signatures import METER_PROBLEMS, Signature

# wattwise.ml.explanations imports estimate_impact from here (its evidence bundles carry a
# potential-excess figure, T021); importing it back at module load would be circular, so
# `run_impact` imports it lazily instead.

FloatArray = npt.NDArray[np.float64]

IMPACT_VERSION: Final = "1"
DEFAULT_OUTPUT: Final = Path("../data/processed/detection/impact")


class ImpactStatus(StrEnum):
    """`POTENTIAL`: an estimate from the interval, not confirmed by anyone. `VERIFIED` is for a
    future human-confirmed figure (T025's feedback loop); this module never sets it."""

    POTENTIAL = "potential"
    VERIFIED = "verified"


class TariffConfig(BaseModel):
    """An explicitly configured tariff. Without one, impact estimates show kWh only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = Field(min_length=3, max_length=3)  # ISO 4217, e.g. "USD", "GBP", "EUR"
    rate_per_kwh: float = Field(gt=0)

    @field_validator("currency")
    @classmethod
    def _upper_alpha(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must be an ISO 4217 letter code, e.g. 'USD'")
        return value.upper()


@dataclass(frozen=True)
class Impact:
    """A potential-excess estimate: always traceable to the rows it was computed from, and to
    the tariff and carbon factor (or their absence) that priced it."""

    status: ImpactStatus
    excess_kwh: float
    hours_with_interval: int
    hours_above_upper_bound: int
    cost: float | None
    currency: str | None
    carbon_kg: float | None
    carbon_factor: CarbonFactor | None


def potential_excess_kwh(actual: npt.ArrayLike, upper: npt.ArrayLike) -> FloatArray:
    """kWh above `upper`, per row. 0 at or below the bound (a negative residual never counts);
    NaN where `actual` or `upper` is unknown (not 0: a missing bound is not zero excess)."""
    a = np.asarray(actual, dtype=float)
    u = np.asarray(upper, dtype=float)
    if a.shape != u.shape:
        raise ValueError(f"actual and upper must have the same shape: {a.shape} vs {u.shape}")
    out = np.full(a.shape, np.nan)
    known = np.isfinite(a) & np.isfinite(u)
    out[known] = np.maximum(a[known] - u[known], 0.0)
    return out


def _price(
    excess_kwh: float,
    hours_with_interval: int,
    hours_above_upper_bound: int,
    tariff: TariffConfig | None,
    factor: CarbonFactor | None,
) -> Impact:
    return Impact(
        status=ImpactStatus.POTENTIAL,
        excess_kwh=round(excess_kwh, 4),
        hours_with_interval=hours_with_interval,
        hours_above_upper_bound=hours_above_upper_bound,
        cost=round(excess_kwh * tariff.rate_per_kwh, 4) if tariff is not None else None,
        currency=tariff.currency if tariff is not None else None,
        carbon_kg=round(excess_kwh * factor.kg_co2e_per_kwh, 4) if factor is not None else None,
        carbon_factor=factor,
    )


def estimate_impact(
    actual: npt.ArrayLike,
    upper: npt.ArrayLike,
    tariff: TariffConfig | None = None,
    factor: CarbonFactor | None = None,
) -> Impact:
    """The total potential excess over `actual`'s rows, priced and carbon-costed where
    configured. `tariff=None` gives `cost=None, currency=None` ("kWh only"); `factor=None`
    gives `carbon_kg=None` ("not configured")."""
    excess = potential_excess_kwh(actual, upper)
    known = np.isfinite(excess)
    total = float(excess[known].sum()) if known.any() else 0.0
    above = int((excess[known] > 0).sum()) if known.any() else 0
    return _price(total, int(known.sum()), above, tariff, factor)


# ---------------------------------------------------------------------------
# Command line: every T020-detected event on real data, priced per its own site
# ---------------------------------------------------------------------------


def run_impact(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    features: pd.DataFrame,
    root: Path = DEFAULT_ROOT,
    detector: Detector = Detector.ROLLING_Z,
    geography_filter: str | None = None,
    tariff: TariffConfig | None = None,
) -> dict[str, Any]:
    """Potential excess and carbon for every detected event, each priced with its own BDG2
    site's geography and the event's own year. Cost is only computed for `geography_filter`'s
    events, with `tariff`: summing cost across geographies would mix currencies."""
    from wattwise.ml.explanations import explain  # local: see the module-level note above

    run = run_detection(readings, buildings, features, root, detector=detector)
    bundles = explain(run, readings, features, top=0)  # impact needs the bounds, not the SHAP
    return price_bundles(bundles, buildings, geography_filter, tariff)


def price_bundles(
    bundles: Sequence[Mapping[str, Any]],
    buildings: pd.DataFrame,
    geography_filter: str | None = None,
    tariff: TariffConfig | None = None,
) -> dict[str, Any]:
    """`run_impact` for evidence bundles already written by `wattwise.ml.explanations` (its
    `explanations.json`), so a full-scale run need not detect and explain twice (T044a).

    Events the signatures classify as meter or data problems (`data_fault`, `flatline`) are
    never counted: a meter problem is not consumption (D029, D040). They are listed, with the
    kWh they sit above the bound, and totalled apart."""
    site_of = dict(
        zip(buildings["building_id"].astype(str), buildings["site_id"].astype(str), strict=True)
    )
    events: list[dict[str, Any]] = []
    by_geography: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        event, bundle_impact = bundle["event"], bundle["impact"]
        site = site_of.get(str(event["building_id"]))
        geography = geography_for_site(site) if site else None
        year = pd.Timestamp(event["start"]).year
        # The signature is the single source of the rule, so bundles written before it was
        # enforced (without a `meter_problem` flag) are priced the same way.
        if Signature(bundle["signature"]["primary"]) in METER_PROBLEMS:
            above = bundle_impact.get("kwh_above_bound_not_counted")
            if above is None:
                above = bundle_impact["potential_excess_kwh"]
            events.append(
                {
                    "meter_id": event["meter_id"],
                    "building_id": event["building_id"],
                    "site_id": site,
                    "geography": geography,
                    "year": year,
                    "meter_problem": True,
                    "excess_kwh": None,
                    "kwh_above_bound_not_counted": above,
                    "cost": None,
                    "currency": None,
                    "carbon_kg": None,
                    "carbon_source": None,
                }
            )
            continue
        use_tariff = tariff if geography is not None and geography == geography_filter else None
        impact = _price(
            bundle_impact["potential_excess_kwh"],
            bundle_impact["hours_with_interval"],
            bundle_impact["hours_above_upper_bound"],
            use_tariff,
            carbon_factor(geography, year),
        )
        events.append(
            {
                "meter_id": event["meter_id"],
                "building_id": event["building_id"],
                "site_id": site,
                "geography": geography,
                "year": year,
                "meter_problem": False,
                "excess_kwh": impact.excess_kwh,
                "kwh_above_bound_not_counted": None,
                "cost": impact.cost,
                "currency": impact.currency,
                "carbon_kg": impact.carbon_kg,
                "carbon_source": impact.carbon_factor.source_name if impact.carbon_factor else None,
            }
        )
        bucket = by_geography.setdefault(
            geography or "not configured", {"events": 0, "excess_kwh": 0.0, "carbon_kg": 0.0}
        )
        bucket["events"] += 1
        bucket["excess_kwh"] = round(bucket["excess_kwh"] + impact.excess_kwh, 4)
        if impact.carbon_kg is not None:
            bucket["carbon_kg"] = round(bucket["carbon_kg"] + impact.carbon_kg, 4)
    counted = [e for e in events if not e["meter_problem"]]
    problems = [e for e in events if e["meter_problem"]]
    detectors = sorted({str(b["detector"]["name"]) for b in bundles})
    models = sorted({str(b["model"]["version"]) for b in bundles})
    return {
        "impact_version": IMPACT_VERSION,
        "detector": ", ".join(detectors) or None,
        "model_version": ", ".join(models) or None,
        "events": len(events),
        "events_counted": len(counted),
        "total_potential_excess_kwh": round(sum(e["excess_kwh"] for e in counted), 4),
        "total_potential_carbon_kg": round(
            sum(e["carbon_kg"] for e in counted if e["carbon_kg"] is not None), 4
        ),
        "meter_problem_events": len(problems),
        "meter_problem_kwh_above_bound_not_counted": round(
            sum(e["kwh_above_bound_not_counted"] for e in problems), 4
        ),
        "priced_geography": geography_filter,
        "total_cost": (
            {
                "currency": tariff.currency,
                "value": round(sum(e["cost"] for e in counted if e["cost"] is not None), 4),
                "events": sum(e["cost"] is not None for e in counted),
            }
            if tariff is not None and geography_filter
            else None
        ),
        "by_geography": by_geography,
        "events_detail": events,
    }


def to_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Excess energy, cost and carbon impact (T021)",
        "",
        f"Detector: `{summary['detector']}`; model `{summary['model_version']}`. "
        f"{summary['events']} events, of which {summary['events_counted']} are counted below.",
        "",
        f"**Total potential excess: {summary['total_potential_excess_kwh']:,.1f} kWh** "
        f"(potential, not verified — an anomaly is not confirmed excess consumption).",
        f"**Total potential carbon: {summary['total_potential_carbon_kg']:,.1f} kg CO2e**, "
        "summed per event's own site (never mixing one site's factor into another's).",
    ]
    if summary["meter_problem_events"]:
        lines.append(
            f"**Not counted:** {summary['meter_problem_events']} events are classified as meter "
            f"or data problems (a data fault or a flatline). A meter problem is not consumption, "
            f"so their "
            f"{summary['meter_problem_kwh_above_bound_not_counted']:,.1f} kWh above the bound is "
            "kept out of the totals and out of cost and carbon."
        )
    if summary["priced_geography"]:
        cost = summary["total_cost"]
        stated = (
            f"**Cost: {cost['value']:,.2f} {cost['currency']}** over {cost['events']} events, "
            "at the tariff given. "
            if cost
            else ""
        )
        lines.append(
            f"{stated}Cost is priced only for `{summary['priced_geography']}` (mixing "
            "currencies across geographies would misstate a total)."
        )
    lines += [
        "",
        "| Geography | Events | Potential excess (kWh) | Carbon (kg CO2e) |",
        "|---|---|---|---|",
    ]
    for geography, bucket in sorted(summary["by_geography"].items()):
        lines.append(
            f"| {geography} | {bucket['events']} | {bucket['excess_kwh']:,.1f} | "
            f"{bucket['carbon_kg']:,.1f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.impact",
        description="Potential excess, cost and carbon for every detected event.",
    )
    parser.add_argument("--data", type=Path, required=True, help="prepared canonical tables")
    parser.add_argument("--enrichment", type=Path, help="weather_enrichment.parquet (T007d)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="model registry")
    parser.add_argument(
        "--store", type=Path, help="T042 feature store: read full-scale inputs from it"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--detector", type=Detector, choices=list(Detector), default=Detector.ROLLING_Z
    )
    parser.add_argument("--geography", help="price cost only for this reference geography code")
    parser.add_argument(
        "--tariff-currency", help="ISO 4217 code, with --geography and --tariff-rate"
    )
    parser.add_argument("--tariff-rate", type=float, help="currency per kWh")
    parser.add_argument(
        "--explanations",
        type=Path,
        help="price this explanations.json (wattwise.ml.explanations) instead of re-detecting",
    )
    args = parser.parse_args(argv)
    tariff = None
    if args.tariff_currency or args.tariff_rate is not None:
        if not (args.geography and args.tariff_currency and args.tariff_rate is not None):
            print(
                "error: --geography, --tariff-currency and --tariff-rate are required together",
                file=sys.stderr,
            )
            return 1
        tariff = TariffConfig(currency=args.tariff_currency, rate_per_kwh=args.tariff_rate)
    try:
        if args.explanations:
            payload = json.loads(args.explanations.read_text(encoding="utf-8"))
            buildings = pd.read_parquet(args.data / "buildings.parquet")
            summary = price_bundles(payload["events"], buildings, args.geography, tariff)
        else:
            readings, buildings, features = downstream_inputs(
                args.data, args.enrichment, args.store, args.root
            )
            summary = run_impact(
                readings, buildings, features, args.root, args.detector, args.geography, tariff
            )
    except NoModelError as exc:
        print(f"error: {exc} Train and promote one first.", file=sys.stderr)
        return 1
    except (RegistryError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "impact.json").write_bytes(
        (json.dumps(summary, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    (args.output / "impact.md").write_bytes(to_markdown(summary).encode("utf-8"))
    print(f"{summary['events']} events priced -> {args.output}")
    for name in ("impact.json", "impact.md"):
        print(f"  {name}: {sha256_of(args.output / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
