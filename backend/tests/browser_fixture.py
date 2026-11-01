"""Isolated synthetic PostgreSQL/API fixture owned by the browser-test runner."""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from tests.conftest import SAMPLE_INFO, SYNTHETIC_SAMPLE
from tests.integration.test_pipeline import WINDOW
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER
from wattwise.db.alerts import load_alerts
from wattwise.db.expectations import compute_expectations, store_expectations
from wattwise.db.load import load_dataset, read_table
from wattwise.db.migrate import upgrade
from wattwise.ml.baselines import SeasonalNaive
from wattwise.ml.detection import run_detection
from wattwise.ml.evaluation import Forecaster, evaluate, write_report
from wattwise.ml.explanations import explain
from wattwise.ml.registry import promote, read_inputs, save, train
from wattwise.ml.splits import Role, SplitConfig, make_split

SCHEMA_NAME = re.compile(r"^e2e_[0-9a-f]{12}$")


def test_database_url() -> str:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    value = os.environ.get("WATTWISE_TEST_DATABASE_URL", "")
    if not value:
        raise ValueError("WATTWISE_TEST_DATABASE_URL is required for browser tests.")
    parsed = make_url(value)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        raise ValueError("Browser tests require a PostgreSQL psycopg database named *_test.")
    return value


def schema_of(state: Path) -> str:
    schema = json.loads(state.read_text(encoding="utf-8"))["schema"]
    if not isinstance(schema, str) or not SCHEMA_NAME.fullmatch(schema):
        raise ValueError("Invalid browser-test schema identifier.")
    return schema


def engine_for(state: Path) -> Engine:
    schema = schema_of(state)
    return create_engine(
        test_database_url(),
        connect_args={"options": f"-csearch_path={schema} -ctimezone=UTC", "connect_timeout": 3},
    )


def prepare(state: Path) -> None:
    url = test_database_url()
    if state.exists():
        raise ValueError("Browser-test state already exists; refusing to overwrite it.")
    schema = f"e2e_{uuid.uuid4().hex[:12]}"
    state.write_text(json.dumps({"schema": schema}), encoding="utf-8")
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        admin.dispose()
    prepared = state.parent / "prepared"
    prepared.mkdir()
    for contract in (BUILDINGS, READINGS, WEATHER):
        read_table(SYNTHETIC_SAMPLE, contract).to_parquet(
            prepared / f"{contract.name}.parquet", index=False
        )
    readings, buildings, features = read_inputs(prepared, None)
    root = state.parent / "models"
    config = SplitConfig(time=WINDOW)
    trained = train(readings, buildings, features, config)
    version = save(trained, root)
    promote(version, root)
    run = run_detection(readings, buildings, features, root)
    bundles = explain(run, readings, features, top=0)
    if not bundles:
        raise ValueError("The synthetic browser fixture must produce alerts.")
    expected, info = compute_expectations(prepared, None, None, root)
    split = make_split(readings, config, buildings)
    part = split.folds[0]
    naive = SeasonalNaive()
    for forecaster, name in ((trained.model, "chosen"), (naive, naive.name)):
        predictions = {
            (part.fold.name, role): forecaster.predict(
                part.rows(role).drop(columns="value"), readings
            )
            for role in (Role.VALIDATION, Role.TEST)
        }
        write_report(
            evaluate(
                split, predictions, Forecaster(name=forecaster.name, params=forecaster.params)
            ),
            state.parent / "evaluation",
            name,
        )
    engine = engine_for(state)
    try:
        with engine.begin() as connection:
            upgrade(connection)
            load_dataset(connection, SAMPLE_INFO, buildings, readings)
            load_alerts(connection, SAMPLE_INFO.dataset_id, bundles)
            store_expectations(connection, SAMPLE_INFO.dataset_id, expected, info)
    finally:
        engine.dispose()
    print(f"Synthetic browser fixture prepared: {len(readings)} rows, {len(bundles)} alerts.")


def cleanup(state: Path) -> None:
    if not state.exists():
        return
    schema = schema_of(state)
    admin = create_engine(test_database_url())
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        admin.dispose()
    print("Browser-test schema removed.")


def serve(state: Path) -> None:
    engine = engine_for(state)
    settings = Settings(
        environment="test",
        database_url=None,
        registry_root=state.parent / "models",
        evaluation_root=state.parent / "evaluation",
        model_data_kind="synthetic",
    )
    try:
        uvicorn.run(create_app(settings, engine=engine), host="127.0.0.1", port=8765)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve", "cleanup"))
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    actions: dict[str, Any] = {"prepare": prepare, "serve": serve, "cleanup": cleanup}
    try:
        actions[args.command](args.state)
    except Exception as exc:
        print(f"Browser fixture failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
