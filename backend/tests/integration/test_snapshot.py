import json
from pathlib import Path

from sqlalchemy import Engine

from tests.conftest import SYNTHETIC_SAMPLE
from wattwise.snapshot import build, snapshot_key


def test_the_key_sorts_parameters_and_keeps_empty_values() -> None:
    assert snapshot_key("/api/v1/alerts", {"offset": 0, "limit": 25, "severity": "high"}) == (
        "/api/v1/alerts?limit=25&offset=0&severity=high"
    )
    assert snapshot_key("/api/v1/models/evaluation", {"q": "", "limit": 25, "offset": 0}) == (
        "/api/v1/models/evaluation?limit=25&offset=0&q="
    )
    assert snapshot_key("/api/v1/health") == "/api/v1/health"


def test_the_snapshot_records_every_preset_view_of_the_synthetic_demo(
    schema_engine: Engine, tmp_path: Path
) -> None:
    output = tmp_path / "snapshot"
    index = build(schema_engine, SYNTHETIC_SAMPLE, output)

    entries: dict[str, str] = index["entries"]
    assert json.loads((output / "index.json").read_text(encoding="utf-8")) == index
    for key, name in entries.items():
        assert key.startswith("/api/v1/")
        body = json.loads((output / name).read_text(encoding="utf-8"))
        assert body is not None, key
    health = json.loads((output / entries["/api/v1/health"]).read_text(encoding="utf-8"))
    assert health["read_only"] is True
    summary = json.loads(
        (output / entries["/api/v1/dashboard/summary"]).read_text(encoding="utf-8")
    )
    assert {d["kind"] for d in summary["datasets"]} == {"synthetic"}
    paths = {key.split("?")[0] for key in entries}
    for needed in (
        "/api/v1/impact/summary",
        "/api/v1/models/metadata",
        "/api/v1/models/metrics",
        "/api/v1/models/evaluation",
        "/api/v1/models/drift",
        "/api/v1/analysis-runs",
        "/api/v1/datasets/synthetic-sample/quality",
        "/api/v1/alerts/1",
    ):
        assert needed in paths, needed
    meters = [p for p in paths if p.endswith("/expectation")]
    assert len(meters) == 4  # every synthetic meter
    assert not any("feedback" in key for key in entries)  # nothing that writes
