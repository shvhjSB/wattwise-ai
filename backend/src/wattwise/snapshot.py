"""Record the public demo's API answers for a static site (T050, D068).

The static demo on GitHub Pages has no server. This seeds the synthetic demo into a database,
asks the real API (in read-only mode, in process) every question the pages ask for the preset
views, and writes each answer to a file, with `index.json` mapping each request to its file:

    {"version": 1, "entries": {"<path>?<sorted query>": "<file>.json", ...}}

The key is the decoded path and the query parameters sorted by name and value, joined with `&`
without percent-encoding, so parameter order or URL encoding cannot cause a miss. The frontend
builds the same key (`frontend/src/api/snapshot.ts`). A request that was not recorded (free-text
search, a custom tariff, date filters) is answered in the browser with a plain "not in the static
demo" message, never with invented data.

    uv run --env-file .env python -m wattwise.snapshot --output ../data/processed/snapshot

It uses FastAPI's test client, so it needs the development dependencies (`uv sync`); it is
build tooling, never imported by the running API. The database must be empty or hold only the
synthetic demo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from wattwise.api.main import create_app
from wattwise.core.config import Settings, get_settings
from wattwise.data.quality import QualityCheck
from wattwise.db.engine import create_db_engine
from wattwise.demo import initialize_demo

SNAPSHOT_VERSION: Final = 1
DEFAULT_DATA: Final = Path("../data/sample/synthetic")
API: Final = "/api/v1"
#: The frontend's page sizes (src/api/*.ts and the pages); the snapshot records the same ones.
ALERT_PAGE: Final = 25
METER_ALERT_LIMIT: Final = 200
BUILDING_PAGES: Final = range(20, 201, 20)  # the explorer's "show more" steps
EVALUATION_PAGE: Final = 25
RUN_PAGE: Final = 10
DRIFT_PAGE: Final = 10
QUALITY_PAGE: Final = 25
EXPECTATION_LIMIT: Final = 50_000
REVIEW_STATUSES: Final = (
    "unreviewed",
    "confirmed_waste",
    "expected_behaviour",
    "sensor_or_data_fault",
    "needs_investigation",
)
SEVERITIES: Final = ("high", "medium", "low")
ALERT_KINDS: Final = ("above_expected", "below_expected", "meter_problem")

Params = Mapping[str, str | int]


def snapshot_key(path: str, params: Params | None = None) -> str:
    """The lookup key: the decoded path, then the parameters sorted by name and value."""
    pairs = sorted((str(k), str(v)) for k, v in (params or {}).items())
    query = "&".join(f"{k}={v}" for k, v in pairs)
    return f"{path}?{query}" if query else path


class Recorder:
    """Ask the API and keep every successful answer."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.entries: dict[str, Any] = {}
        self.refused: list[str] = []

    def get(self, path: str, params: Params | None = None) -> Any:
        key = snapshot_key(path, params)
        if key in self.entries:
            return self.entries[key]
        response = self.client.get(path, params=dict(params or {}))
        if response.status_code != 200:
            self.refused.append(f"{response.status_code} {key}")
            return None
        body = response.json()
        self.entries[key] = body
        return body

    def pages(self, path: str, params: Params, size: int) -> Iterator[Any]:
        """Every page of a paged list: offset 0, size, 2 * size... while items remain."""
        offset = 0
        while True:
            body = self.get(path, {**params, "limit": size, "offset": offset})
            if body is None:
                return
            yield body
            offset += size
            if offset >= int(body.get("total", 0)):
                return


def _items(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    return items if isinstance(items, list) else []


def record(client: TestClient) -> Recorder:
    """Every answer the pages need for the preset views."""
    r = Recorder(client)
    r.get(f"{API}/health")
    summary = r.get(f"{API}/dashboard/summary")
    r.get(f"{API}/impact/summary")
    r.get(f"{API}/models/metadata")
    r.get(f"{API}/models/metrics")

    buildings: list[dict[str, Any]] = []
    for limit in BUILDING_PAGES:
        body = r.get(f"{API}/buildings", {"limit": limit, "offset": 0})
        if body is not None and not buildings:
            buildings = _items(body)
    building_ids = [b["building_id"] for b in buildings]
    meter_ids: list[str] = []
    r.get(f"{API}/meters", {"limit": 200})
    for building_id in building_ids:
        r.get(f"{API}/buildings/{building_id}")
        meters = r.get(f"{API}/meters", {"building_id": building_id, "limit": 200})
        meter_ids += [m["meter_id"] for m in _items(meters)]
    for meter_id in meter_ids:
        r.get(f"{API}/meters/{meter_id}")
        r.get(f"{API}/meters/{meter_id}/expectation", {"limit": EXPECTATION_LIMIT})
        r.get(f"{API}/alerts", {"meter_id": meter_id, "limit": METER_ALERT_LIMIT})

    alert_ids: set[int] = set()
    signatures: set[str] = set()
    for body in r.pages(f"{API}/alerts", {}, ALERT_PAGE):
        for alert in _items(body):
            alert_ids.add(int(alert["alert_id"]))
            signatures.add(str(alert["signature"]))
    filters: list[dict[str, str]] = [
        *({"severity": s} for s in SEVERITIES),
        *({"review_status": s} for s in REVIEW_STATUSES),
        *({"kind": k} for k in ALERT_KINDS),
        *({"signature": s} for s in sorted(signatures)),
        *({"building_id": b} for b in building_ids),
        *({"meter_id": m} for m in meter_ids),
    ]
    for single in filters:
        for _ in r.pages(f"{API}/alerts", single, ALERT_PAGE):
            pass
    for alert_id in sorted(alert_ids):
        r.get(f"{API}/alerts/{alert_id}")

    for query in ("", *building_ids):
        for _ in r.pages(f"{API}/models/evaluation", {"q": query}, EVALUATION_PAGE):
            pass
    for _ in r.pages(f"{API}/analysis-runs", {}, RUN_PAGE):
        pass

    drift = r.get(f"{API}/models/drift", {"limit": DRIFT_PAGE, "offset": 0})
    drift_datasets = drift.get("datasets", []) if isinstance(drift, dict) else []
    for dataset_id in [None, *drift_datasets]:
        for period in (None, "week", "month"):
            params: dict[str, str | int] = {}
            if dataset_id is not None:
                params["dataset_id"] = dataset_id
            if period is not None:
                params["period"] = period
            for _ in r.pages(f"{API}/models/drift", params, DRIFT_PAGE):
                pass

    datasets = summary.get("datasets", []) if isinstance(summary, dict) else []
    for dataset in datasets:
        path = f"{API}/datasets/{dataset['dataset_id']}/quality"
        for check in (None, *QualityCheck):
            for warnings in (False, True):
                params = {}
                if check is not None:
                    params["check"] = check.value
                if warnings:
                    params["warnings_only"] = "true"
                for _ in r.pages(path, params, QUALITY_PAGE):
                    pass
    return r


def write(recorder: Recorder, output: Path) -> dict[str, Any]:
    """Write every answer and the index; returns the index. `output` is replaced."""
    if output.exists():
        shutil.rmtree(output)
    (output / "api").mkdir(parents=True)
    entries = {}
    for key, body in sorted(recorder.entries.items()):
        name = f"api/{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}.json"
        (output / name).write_text(
            json.dumps(body, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
        )
        entries[key] = name
    index = {"version": SNAPSHOT_VERSION, "entries": entries}
    (output / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    return index


def build(engine: Engine, data: Path, output: Path) -> dict[str, Any]:
    """Seed the synthetic demo into `engine` and record the snapshot into `output`."""
    with tempfile.TemporaryDirectory() as directory:
        artifacts = Path(directory)
        initialize_demo(engine, data, artifacts, replace_stale=True)
        settings = Settings(
            environment="production",
            database_url=None,
            read_only=True,
            model_data_kind="synthetic",
            registry_root=artifacts / "models",
            evaluation_root=artifacts / "evaluation",
        )
        with TestClient(create_app(settings, engine=engine)) as client:
            recorder = record(client)
    if recorder.refused:
        raise RuntimeError("The API refused snapshot requests: " + "; ".join(recorder.refused[:5]))
    return write(recorder, output)


def _sizes(paths: Iterable[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.is_file())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wattwise.snapshot", description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args(argv)
    url = get_settings().database_url
    if url is None:
        print("error: WATTWISE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_db_engine(url.get_secret_value())
    try:
        index = build(engine, args.data, args.output)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    size = _sizes(args.output.rglob("*"))
    print(f"recorded {len(index['entries'])} answers, {size:,} bytes, into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
