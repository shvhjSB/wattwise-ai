from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine

from tests.conftest import SYNTHETIC_SAMPLE
from wattwise import operations
from wattwise.core.config import Settings
from wattwise.db.migrate import head_revision
from wattwise.demo import initialize_demo


def test_migrations_are_idempotent_and_do_not_seed_data(schema_engine: Engine) -> None:
    assert operations.migrate_database(schema_engine) == head_revision()
    assert operations.migrate_database(schema_engine) == head_revision()


def test_release_requires_the_exact_model_and_matching_reports(
    schema_engine: Engine,
    tmp_path: Path,
) -> None:
    result = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    settings = Settings(
        environment="test",
        database_url=None,
        registry_root=tmp_path / "models",
        evaluation_root=tmp_path / "evaluation",
        model_data_kind="synthetic",
    )
    checked = operations.check_release(settings, schema_engine, result.model_version)
    assert checked["model_version"] == result.model_version
    assert checked["data_kind"] == "synthetic"
    with pytest.raises(operations.DeploymentError, match="model_version_mismatch"):
        operations.check_release(settings, schema_engine, "not-the-pinned-model")
    assert (settings.registry_root / "CURRENT").read_text().strip() == result.model_version
    (settings.evaluation_root / "chosen.json").unlink()
    with pytest.raises(operations.DeploymentError, match="evaluation_unavailable"):
        operations.check_release(settings, schema_engine, result.model_version)


def test_release_refuses_an_unmigrated_database(schema_engine: Engine, tmp_path: Path) -> None:
    settings = Settings(environment="test", database_url=None, registry_root=tmp_path)
    with pytest.raises(operations.DeploymentError, match="database_schema_outdated"):
        operations.check_release(settings, schema_engine, "unused")


def test_command_failures_do_not_echo_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(database_url=SecretStr("postgresql+psycopg://u:private-test-value@db/w"))
    monkeypatch.setattr(operations, "get_settings", lambda: settings)

    def broken_engine(url: str) -> Engine:
        raise RuntimeError(f"Cannot connect to {url}")

    monkeypatch.setattr(operations, "create_db_engine", broken_engine)
    assert operations.main(["migrate"]) == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert "private-test-value" not in output.err + output.out
    assert "postgresql" not in output.err + output.out
